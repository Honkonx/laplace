"""servicio.py — `pronosticar_partido`: el único punto por el que el bot, el agente, la IA (por API) y la web piden un pronóstico del modelo Laplace.

Contrato (`/api/v1/ml/predict`): entra `{local, visitante, liga?, partido_id?}`, sale `{ok, fuente, degradado, p1x2, goles_esperados, btts, over_under, marcadores,
confianza, modelo}`. Nunca lanza: sin modelo activo cae al Dixon-Coles histórico y lo dice (`degradado: true`); si tampoco, `ok: false` con el motivo.
Sirve el modelo `activo` (por la base, o por el puntero `vigente.json` si no hay sesión: así el motor del bot no depende de la base para leerlo). El modelo en
sombra corre en paralelo y se registra, pero NO responde. Nombres de equipo y liga se resuelven con los mismos alias del histórico (`modelo_historico`).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from backend.api.ml.laplace import apilado, entrenamiento, estado_vivo, goles, incertidumbre, pronostico, registro

log = logging.getLogger(__name__)
CAMPO_MAX = 120
SIN_COBERTURA = "la liga o los equipos están fuera de lo que conoce el modelo"


def _limpio(valor) -> str:
    return str(valor or "").strip()[:CAMPO_MAX]


def _resolver_real(datos: dict, modelo_id: int | None = None) -> tuple[str, str, str] | None:
    """(código de liga, local canónico, visitante canónico) con los alias del histórico; None si no se puede.

    Si falta UN equipo en el histórico (un recién ascendido) pero la memoria del modelo en la base ya lo conoce (`estado_vivo.py`: entró por la capa en vivo o la actual con al menos `N_MIN_EQUIPO` partidos), se
    resuelve con su nombre sin acentos: antes quedaba «sin historial» para siempre porque nada lo agregaba al histórico."""
    try:
        from backend.api.services import modelo_historico

        r = modelo_historico._resolver(datos)  # noqa: SLF001 — mismo resolutor que usa el módulo histórico del consenso
        if r and r[0]:
            return r[0], r[2], r[3]
        nuevo = modelo_historico._resolver_equipo_nuevo(datos)  # noqa: SLF001 — exactamente UN equipo resuelto y el otro sin historial claro
        if nuevo:
            codigo, _modelo, local, visitante = nuevo
            local, visitante = local or estado_vivo.plano(datos["local"]), visitante or estado_vivo.plano(datos["visitante"])
            estado = estado_vivo.estado_de(modelo_id, codigo)
            if estado is not None and estado.conoce(local) and estado.conoce(visitante):
                return codigo, local, visitante
    except Exception as exc:  # noqa: BLE001
        log.warning("no se pudo resolver liga y equipos: %s", exc)
    return None


def _calcular(artefacto: dict, datos: dict, modelo_id: int | None = None) -> tuple[dict | None, str]:
    """Salida del modelo para el partido y, si no hay, el motivo. Con `modelo_id` usa el estado al día de la base (`estado_vivo.py`); sin él (la sombra), el del artefacto."""
    if artefacto.get("familia") == entrenamiento.FAMILIA_JERARQUICA:
        res = _resolver_real(datos, modelo_id)
        if res is None:
            return None, SIN_COBERTURA
        liga, local, visitante = res
        r = entrenamiento.predecir_liga(artefacto, liga, local, visitante, estado_vivo.estado_de(modelo_id, liga))
        if r is None:
            return None, f"el modelo no tiene la liga {liga}"
        extra = {"liga_modelo": liga, "especializado": r["especializado"]}
        if not (r["conoce_local"] and r["conoce_visitante"]):
            return None, "el modelo no conoce a alguno de los equipos"
        salida = {**goles.pronosticar(*r["lambdas"], r["medias"], r["goles"], r["tasas_goles"], p1x2=r["p1x2"]), **extra}
        info_inc = artefacto.get("incertidumbre")
        if info_inc and info_inc.get("covarianza") and not r["especializado"]:  # los intervalos valen para los pesos universales
            estado_liga = estado_vivo.estado_de(modelo_id, liga) or entrenamiento.EstadoLiga.de_dict(artefacto["ligas"][liga]["estado"])
            salida["incertidumbre"] = incertidumbre.intervalo(info_inc["covarianza"], entrenamiento.pesos_de(artefacto, liga), estado_liga.features(local, visitante))
        con_mercado = apilado.aplicar(artefacto.get("apilador_mercado"), r["p1x2"], datos.get("cuotas"))
        if con_mercado:  # aparte del `p1x2` propio: el modelo solo se mide contra sí mismo; esta es la lectura combinada con el mercado
            salida["p1x2_con_mercado"] = dict(zip(("local", "empate", "visitante"), con_mercado))
        return salida, ""
    r = entrenamiento.predecir_1x2(artefacto, datos["local"], datos["visitante"])
    if not (r["conoce_local"] and r["conoce_visitante"]):
        return None, "el modelo no conoce a alguno de los equipos"
    return {**pronostico.pronosticar(*r["lambdas"], p1x2=r["p1x2"]), "validados": []}, ""


def _con_modelo(modelo_info: dict, salida: dict) -> dict:
    return {**salida, "fuente": "modelo_laplace", "degradado": False, "modelo": modelo_info}


def pronostico_propio(entrada: dict) -> dict | None:
    """Salida del modelo Laplace SOLO si el modelo activo cubre el partido, sin respaldo Dixon-Coles y sin registrar nada (la usa el módulo histórico del consenso: llamar a
    `pronosticar_partido` desde allí sería circular, porque su respaldo es ese mismo módulo). None si no hay modelo o no cubre el partido."""
    try:
        info, art, _ = _modelo_vigente(None)
        if art is None:
            return None
        local, visitante = _limpio(entrada.get("local")), _limpio(entrada.get("visitante"))
        if not local or not visitante or local == visitante:
            return None
        datos = {k: entrada[k] for k in ("pais", "liga_id") if entrada.get(k)} | {"local": local, "visitante": visitante, "liga": _limpio(entrada.get("liga"))}
        calculada, _ = _calcular(art, datos, info["id"])
        return {**calculada, "modelo": info} if calculada else None
    except Exception as exc:  # noqa: BLE001 — una pieza independiente: si falla, el consenso sigue sin ella
        log.warning("modelo Laplace no disponible para el módulo histórico: %s", exc)
        return None


def _desde_historico(entrada: dict, motivo: str) -> dict | None:
    try:
        from backend.api.services import modelo_historico

        r = modelo_historico.analizar(entrada)
    except Exception as exc:  # noqa: BLE001 — el servicio degrada ante cualquier falla del respaldo y deja rastro
        log.warning("respaldo Dixon-Coles no disponible: %s", exc)
        return None
    if not r.get("ok"):
        return None
    p = (r["prob_local"], r["prob_empate"], r["prob_visitante"])
    salida = {**pronostico.pronosticar(r["lambda_local"], r["lambda_visit"], p1x2=p), "validados": []}
    return {**salida, "fuente": "dixon_coles_historico", "degradado": True, "motivo_degradado": motivo, "modelo": None}


def _desde_liga(artefacto: dict | None, datos: dict, motivo: str) -> dict | None:
    """Último respaldo cuando ningún equipo tiene historia: la referencia de la LIGA (equipo promedio contra equipo promedio, con la ventaja de local de esa liga).
    Medido con `evaluar_equipo_nuevo_laplace.py` (486 partidos con dos equipos nuevos): RPS 0,2210 frente a 0,2225 de la tasa base, sin diferencia significativa (z = −1,0):
    es una referencia honesta, no un pronóstico de los equipos. Solo si la liga queda identificada sin ambigüedad; nunca se registra ni entra al consenso como voto."""
    if artefacto is None or artefacto.get("familia") != entrenamiento.FAMILIA_JERARQUICA:
        return None
    try:
        from backend.api.services import modelo_historico

        candidatas = [c for c in modelo_historico.ligas_candidatas(datos) if c in artefacto["ligas"]]
        if len(candidatas) != 1:
            return None
        r = entrenamiento.predecir_liga(artefacto, candidatas[0], datos["local"], datos["visitante"])
        if r is None:
            return None
        salida = goles.pronosticar(*r["lambdas"], r["medias"], r["goles"], r["tasas_goles"], p1x2=r["p1x2"])
    except Exception as exc:  # noqa: BLE001 — una pieza independiente: sin ella el consenso sigue
        log.warning("referencia de liga no disponible: %s", exc)
        return None
    return {**salida, "validados": [], "liga_modelo": candidatas[0], "fuente": "referencia_de_liga", "degradado": True, "equipo_sin_historial": True,
            "motivo_degradado": f"{motivo}; ningún equipo tiene historia: referencia de la liga", "modelo": None}


def _modelo_vigente(db: Session | None) -> tuple[dict | None, dict | None, str]:
    """(info, artefacto, motivo) del modelo activo: por la base si hay sesión, si no por el puntero en disco."""
    if db is not None:
        activo = registro.modelo_vigente(db)
        if activo is None:
            return None, None, "no hay un modelo Laplace activo"
        art = registro.cargar_artefacto(activo)
        info = {"id": activo.id, "nombre": activo.nombre, "version": activo.version, "estado": activo.estado}
        return (info, art, "") if art else (None, None, "el artefacto del modelo falta o no coincide con su huella")
    info, art = registro.cargar_vigente_archivo()
    if not art:
        return None, None, "no hay un modelo Laplace activo"
    # el puntero trae la ruta local y la huella: no se exponen en la respuesta (revelarían rutas de la máquina)
    return {k: info[k] for k in ("id", "nombre", "version", "estado")}, art, ""


def pronosticar_partido(db: Session | None, entrada: dict, canal: str = "http") -> dict:
    local, visitante = _limpio(entrada.get("local")), _limpio(entrada.get("visitante"))
    if not local or not visitante or local == visitante:
        return {"ok": False, "motivo": "se necesitan dos equipos distintos"}
    datos = {k: entrada[k] for k in ("pais", "liga_id") if entrada.get(k)} | {"local": local, "visitante": visitante, "liga": _limpio(entrada.get("liga"))}
    if apilado.cuotas_validas(entrada.get("cuotas")):
        datos["cuotas"] = entrada["cuotas"]
    t0 = time.perf_counter()
    salida, motivo, art = None, "no hay un modelo Laplace activo", None
    try:
        info, art, motivo = _modelo_vigente(db)
        if art is not None:
            calculada, motivo = _calcular(art, datos, info["id"])
            salida = _con_modelo(info, calculada) if calculada else None
        if db is not None and canal != "http":
            _correr_sombra(db, datos, canal, _limpio(entrada.get("partido_id")) or None)
    except Exception as exc:  # noqa: BLE001 — la base caída o un artefacto roto no tumba el pronóstico: se degrada
        log.warning("servicio del modelo Laplace: %s", exc)
        salida, motivo = None, "el registro del modelo no está disponible"
    if salida is None:
        salida = _desde_historico(datos, motivo)
    if salida is None:
        salida = _desde_liga(art, datos, motivo)
    if salida is None:
        return {"ok": False, "motivo": motivo, "degradado": True}
    salida["ok"] = True
    # El canal público (`http`) no deja rastro: lo puede llamar cualquiera y cada fila sería almacenamiento gratis para un atacante; los internos sí registran.
    if db is not None and salida["modelo"] and canal != "http":
        try:
            registro.registrar_prediccion(db, salida["modelo"]["id"], datos, salida, canal, (time.perf_counter() - t0) * 1000, _limpio(entrada.get("partido_id")) or None)
        except Exception as exc:  # noqa: BLE001
            log.warning("no se pudo registrar la predicción: %s", exc)
    return salida


def publico(salida: dict) -> dict:
    """Salida para quien llama por API: quita los mercados de goles que NO superaron a la tasa base fuera de muestra (ver `goles.calibrar`); el 1X2 siempre sale."""
    v = set(salida.get("validados") or [])
    r = {k: x for k, x in salida.items() if k not in ("btts", "over_under", "marcadores", "goles_esperados")}
    if "btts" in v:
        r["btts"] = salida["btts"]
    lineas = {linea: x for linea, x in salida.get("over_under", {}).items() if goles.LINEA_DE_INV.get(linea) in v}
    if lineas:
        r["over_under"] = lineas
    if "total" in v:
        r["goles_esperados"], r["marcadores"] = salida["goles_esperados"], salida["marcadores"]
    return r


def ficha_modelo(db: Session | None) -> dict:
    """Ficha pública del modelo activo (versión, variables, cobertura, mercados validados, linaje): sin rutas, sin secretos (MM-03)."""
    info, art, motivo = _modelo_vigente(db)
    if art is None:
        return {"ok": False, "motivo": motivo}
    from backend.api.ml.laplace import tarjeta

    return {"ok": True, "modelo": info, **tarjeta.ficha(art)}


def _etiqueta_fuente(salida: dict) -> str:
    """Cómo se llama la procedencia ante quien lee: el modelo propio, el respaldo Dixon-Coles o la referencia de la liga (ningún equipo con historia)."""
    if salida.get("fuente") == "referencia_de_liga":
        return "referencia de la liga: ningún equipo tiene historia"
    return "respaldo Dixon-Coles" if salida.get("degradado") else "propio"


def resumen_para_consumidores(salida: dict) -> dict | None:
    """Versión compacta y SIN política para el bot, la web y la IA: solo números del modelo y su procedencia (nunca «publicar»)."""
    if not salida.get("ok"):
        return None
    p, v = salida["p1x2"], salida.get("validados") or []
    return {"fuente": salida["fuente"], "degradado": salida["degradado"], "p1x2": {k: round(v_, 4) for k, v_ in p.items()},
            # los mercados de goles solo salen si superaron a la tasa base fuera de muestra (`goles.calibrar`); si no, son None y nadie los muestra
            "goles_esperados": salida["goles_esperados"] if "total" in v else None,
            "btts_si": round(salida["btts"]["si"], 4) if "btts" in v else None,
            "mas_2_5": round(salida["over_under"]["2.5"]["mas"], 4) if "o25" in v else None,
            "marcador_mas_probable": salida["marcadores"][0]["marcador"] if "total" in v else None,
            "p1x2_con_mercado": {k: round(v_, 4) for k, v_ in salida["p1x2_con_mercado"].items()} if salida.get("p1x2_con_mercado") else None,
            "confianza_dispersion": salida["confianza"], "modelo": salida.get("modelo"),
            "etiqueta": _etiqueta_fuente(salida)}


def _correr_sombra(db: Session, datos: dict, canal: str, partido_id: str | None = None) -> None:
    """Ejecuta el modelo en sombra y guarda su salida para evaluarlo después; nunca altera la respuesta."""
    sombra = registro.modelo_sombra(db)
    if sombra is None:
        return
    art = registro.cargar_artefacto(sombra)
    if art is None:
        return
    s, _ = _calcular(art, datos)
    if s is not None:
        registro.registrar_prediccion(db, sombra.id, datos, {**s, "modelo": None}, "sombra" if canal != "laboratorio" else canal, 0.0, partido_id)
