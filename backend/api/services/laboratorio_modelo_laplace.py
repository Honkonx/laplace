"""laboratorio_modelo_laplace.py — el modelo propio de Laplace dentro del laboratorio de pronósticos.

Registra la variante `laplace_modelo` (congelada antes del partido, sin entrar al consenso), deja su predicción en `ml_predicciones` con el `partido_id` real y compara su evidencia EN VIVO
contra las demás variantes sobre los mismos partidos. Se separó de `laboratorio_pronosticos.py` (superaba las 500 líneas); allí se reexporta con los mismos nombres. Importa el
laboratorio de forma perezosa para no crear un ciclo de importación.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import PronosticoExperimental

log = logging.getLogger("laplace.laboratorio_pronosticos")


def _lab():
    from backend.api.services import laboratorio_pronosticos

    return laboratorio_pronosticos


def _registrar_prediccion_del_modelo(db: Session, salida: dict, partido_id: str, local: str, visitante: str, liga: str) -> None:
    """Deja la predicción del modelo en `ml_predicciones` con el `partido_id` REAL y el corte previo al partido: así `evaluar_sombra` puede medir al modelo activo en vivo.

    Va en la transacción del laboratorio (sin commit propio) y nunca rompe el registro del comparador."""
    modelo = salida.get("modelo")
    if not modelo:
        return
    try:
        from backend.api.ml.laplace import registro

        registro.registrar_prediccion(db, modelo["id"], {"local": local, "visitante": visitante, "liga": liga}, salida, "laboratorio", 0.0, partido_id, confirmar=False)
    except Exception:  # noqa: BLE001
        log.warning("laboratorio: no se pudo guardar la predicción del modelo", exc_info=True)


def registrar_modelo_laplace(db: Session, *, partido_id: str, fecha_partido: str, local: str, visitante: str,
                             liga: str, hora_kickoff: str | None, datos: dict) -> None:
    """Variante `laplace_modelo`: el pronóstico del modelo propio, congelado antes del partido y medido contra los demás comparadores (50 exploratoria, 200 para promover).

    Solo se registra cuando respondió el modelo MISMO (no el respaldo Dixon-Coles, que ya tiene su variante): así la variante mide al modelo y no se contamina."""
    if _lab()._pendiente(db, partido_id, "laplace_modelo"):
        return
    try:
        from backend.api.ml.laplace import servicio

        salida = servicio.pronosticar_partido(None, {"local": local, "visitante": visitante, "liga": liga, "pais": datos.get("pais"), "liga_id": datos.get("liga_id")}, canal="laboratorio")
    except Exception:  # noqa: BLE001 — el laboratorio nunca se rompe por el modelo
        log.warning("laboratorio: el modelo Laplace no respondió", exc_info=True)
        return
    if not salida.get("ok") or salida.get("degradado"):
        return
    p = salida["p1x2"]
    probs = (p["local"], p["empate"], p["visitante"])
    _registrar_prediccion_del_modelo(db, salida, partido_id, local, visitante, liga)
    _lab().registrar_pronostico(
        db, experimento_codigo="laplace_modelo", partido_id=partido_id, fecha_partido=fecha_partido, local=local, visitante=visitante, liga=liga,
        fuente="laplace", variante="laplace_modelo", modelo_version=f"laplace-jerarquico-v1:{(salida.get('modelo') or {}).get('version', '?')}",
        corte_datos_en=_lab()._now(), hora_kickoff=hora_kickoff, datos={"modelo": salida.get("modelo"), "contexto": datos}, pick=_lab()._pick_de(probs),
        prob_local=probs[0], prob_empate=probs[1], prob_visitante=probs[2], marcador_probable=salida["marcadores"][0]["marcador"],
        goles_local_esperados=salida["goles_esperados"]["local"], goles_visitante_esperados=salida["goles_esperados"]["visitante"],
    )


def cruces_de_umbral(previo: int, actual: int) -> list[str]:
    """Umbrales de evidencia que se cruzaron entre dos mediciones (para avisar UNA vez cuando hay casos suficientes)."""
    cruces = []
    if previo < _lab().MUESTRA_MINIMA_EXPLORATORIA <= actual:
        cruces.append("exploratoria")
    if previo < _lab().MUESTRA_MINIMA_PROMOCION <= actual:
        cruces.append("promocion")
    return cruces


def comparar_en_vivo(db: Session, variante: str = "laplace_modelo") -> dict:
    """Evidencia EN VIVO de una variante contra todas las demás sobre los MISMOS partidos ya jugados (no mezcla muestras distintas).

    Es el criterio de `evidencia-historica-antes-de-promover.md`: una ventaja solo cuenta si se ve con los mismos partidos. Menor log loss / RPS es mejor."""
    propias = {f.partido_id: f for f in db.query(PronosticoExperimental).filter(
        PronosticoExperimental.variante == variante, PronosticoExperimental.log_loss.is_not(None)).all()}
    salida = {"variante": variante, "evaluados": len(propias), "partidos_comunes": {}, "propia": None, "otras": {},
              "falta_para_exploratoria": max(0, _lab().MUESTRA_MINIMA_EXPLORATORIA - len(propias)), "falta_para_promocion": max(0, _lab().MUESTRA_MINIMA_PROMOCION - len(propias))}
    if not propias:
        return salida
    otras: dict[str, list[PronosticoExperimental]] = {}
    for f in db.query(PronosticoExperimental).filter(PronosticoExperimental.variante != variante, PronosticoExperimental.log_loss.is_not(None),
                                                      PronosticoExperimental.partido_id.in_(list(propias))).all():
        otras.setdefault(f.variante, []).append(f)

    def media(filas, campo):
        valores = [float(getattr(f, campo)) for f in filas if getattr(f, campo) is not None]
        return round(sum(valores) / len(valores), 4) if valores else None

    salida["propia"] = {"log_loss": media(propias.values(), "log_loss"), "rps": media(propias.values(), "rps")}
    for nombre, filas in sorted(otras.items()):
        comunes = {f.partido_id for f in filas}
        mismas = [propias[p] for p in comunes]
        ll_otra, ll_propia = media(filas, "log_loss"), media(mismas, "log_loss")
        salida["otras"][nombre] = {"partidos_comunes": len(comunes), "log_loss_otra": ll_otra, "log_loss_propia_en_esos_partidos": ll_propia,
                                   "ventaja_log_loss": round(ll_otra - ll_propia, 4) if ll_otra is not None and ll_propia is not None else None}
    return salida


TZ_CHILE = ZoneInfo("America/Santiago")
MARGEN_ANTES_DEL_PARTIDO = timedelta(minutes=30)
HORIZONTE = timedelta(hours=48)
LIMITE_POR_CORRIDA = 400


def _inicio_estimado(p: PartidoDia) -> datetime | None:
    """Inicio del partido en UTC: `kick_off_utc` si viene; si no, `fecha` + `hora_chile`. Esa hora la calcula el gateway como UTC-4 fijo a partir del instante real
    (`gateway_fuentes._timestamp_to_esd`), así que leerla con -4 recupera el instante verdadero. Si aun así quedara después del inicio real, el laboratorio lo rechaza solo
    (`registrar_pronostico` exige corte anterior al inicio) y el partido se omite sin afectar a los demás."""
    if p.kick_off_utc:
        try:
            dt = datetime.fromisoformat(p.kick_off_utc.strip().replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(f"{p.fecha} {p.hora_chile}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=-4))).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def registrar_proximos(db: Session, ahora: datetime | None = None) -> dict:
    """Registra en el laboratorio el pronóstico del modelo Laplace y el de Dixon-Coles histórico para los partidos PRÓXIMOS que el bot ya conoce (`partidos_dia`).

    Así la evidencia en vivo se acumula sola, sin depender de que alguien pida un análisis y sin gastar cuota de ninguna API: solo usa nombres de equipo y liga ya guardados.
    Ambas variantes se registran sobre los mismos partidos para poder compararlas (`comparar_en_vivo`). Idempotente (no repite un partido) y nunca registra un partido que ya empezó
    ni uno que empieza en menos de 30 minutos."""
    lab = _lab()
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hoy = ahora.astimezone(TZ_CHILE).date()
    fechas = {(hoy + timedelta(days=d)).isoformat() for d in (0, 1, 2)}
    resumen = {"candidatos": 0, "registrados": 0, "sin_cobertura": 0, "ya_empezados": 0, "sin_hora": 0}
    from backend.api.services import modelo_historico

    filas = (db.query(PartidoDia).filter(PartidoDia.fecha.in_(fechas), PartidoDia.status == "scheduled").order_by(PartidoDia.fecha, PartidoDia.hora_chile).limit(LIMITE_POR_CORRIDA).all())
    for p in filas:
        if not (p.local and p.visitante and p.match_id):
            continue
        resumen["candidatos"] += 1
        inicio = _inicio_estimado(p)
        if inicio is None:
            resumen["sin_hora"] += 1
            continue
        if inicio <= ahora + MARGEN_ANTES_DEL_PARTIDO or inicio > ahora + HORIZONTE:
            resumen["ya_empezados"] += inicio <= ahora + MARGEN_ANTES_DEL_PARTIDO
            continue
        datos = {"local": p.local, "visitante": p.visitante, "liga": p.liga_nombre or ""}
        comun = dict(partido_id=str(p.match_id), fecha_partido=p.fecha, local=p.local, visitante=p.visitante, liga=p.liga_nombre or "", hora_kickoff=inicio.strftime("%Y-%m-%dT%H:%M:%S"), datos=datos)
        antes = db.query(PronosticoExperimental).filter_by(partido_id=comun["partido_id"], variante="laplace_modelo").count()
        try:
            ok, _ = modelo_historico.validar_historico(datos)
            if ok:
                lab.registrar_historico(db, **comun, historico=modelo_historico.analizar(datos))
            registrar_modelo_laplace(db, **comun)
        except Exception:  # noqa: BLE001 — un partido raro no detiene al resto
            log.warning("laboratorio: no se pudo registrar %s vs %s", p.local, p.visitante, exc_info=True)
            db.rollback()
            continue
        despues = db.query(PronosticoExperimental).filter_by(partido_id=comun["partido_id"], variante="laplace_modelo").count()
        if despues > antes:
            resumen["registrados"] += 1
        else:
            resumen["sin_cobertura"] += 1
    db.commit()
    return resumen
