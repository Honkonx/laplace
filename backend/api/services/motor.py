"""
services/motor.py — Orquesta los módulos de análisis + consenso, dado un partido ya
enriquecido con datos (goles, tabla, H2H, odds, predicción BSD).

Reemplaza la parte de `datos.py` que corría los módulos en `ThreadPoolExecutor` y armaba el
diccionario para `consenso.py` — la parte de datos.py que buscaba los datos externos (BSD,
cascada de fixtures, Forebet) todavía no se portó (queda para `services/gateway.py`, Parte 2
de esta migración) — este motor recibe el payload YA armado, mismo contrato que hoy recibe
pronostico.py por argv.

`pronostico` y `form_recent` corren siempre (no tienen `validar_*`). `h2h`, `odds`,
`tabla_pos` y `bsd_ml` corren solo si sus propios `validar_*` dicen que hay datos suficientes
— mismo criterio de "skip" que aplicaba datos.py antes de lanzar el ThreadPoolExecutor. `bsd_ml`
depende de una llamada HTTP real (`bsd_predictions.obtener_prediccion_externa_bsd`) que se
resuelve UPSTREAM en `services/analisis_completo.py` (en paralelo con standings/odds/H2H vía
asyncio.gather) — acá solo se lee `d["bsd_prediccion"]`, ya resuelto o None; este motor sigue
siendo síncrono y sin I/O propio, igual que antes de conectar bsd_ml.
"""
from __future__ import annotations

import logging

from backend.api.services import bsd_predictions as bsd_predictions_svc
from backend.api.services import consenso as consenso_svc
from backend.api.services import form_recent as form_recent_svc
from backend.api.services import h2h as h2h_svc
from backend.api.services import modelo_historico as modelo_historico_svc
from backend.api.services import odds as odds_svc
from backend.api.services import pronostico as pronostico_svc
from backend.api.services import tabla_pos as tabla_pos_svc


# Valores de relleno que `top_picks` usaba cuando no había estadísticas reales de los equipos
# (goles_local, goles_visit, contra_local, contra_visit). Sin `fuente_goles` explícita se
# reconocen para no tratarlos como evidencia: en la BD real (2026-09-27) generaron 6 de 11 picks
# "Empate" idénticos con λ distintos de la liga.
PROMEDIOS_RELLENO = (1.3, 1.0, 1.0, 1.3)
_CAMPOS_PROMEDIOS = ("goles_local_avg", "goles_visit_avg", "goles_contra_local_avg", "goles_contra_visit_avg")


def _tiene_xg(d: dict) -> bool:
    try:
        return float(d.get("xg_local") or 0) > 0 and float(d.get("xg_visit") or 0) > 0
    except (TypeError, ValueError):
        return False


def razon_omitir_poisson(d: dict) -> str | None:
    """Razón por la que el módulo Poisson no puede estimar con estos datos (None si puede).
    Un Poisson sobre promedios de relleno o ausentes no es una estimación: es la media de la
    liga disfrazada, y no debe votar ni mostrarse."""
    fuente_goles = d.get("fuente_goles")
    if fuente_goles == "liga_generico":
        return "Sin goles específicos de los equipos (solo promedio genérico de liga)"
    if fuente_goles == "h2h_real" and int(d.get("h2h_total") or 0) < 3:
        return "H2H específico insuficiente para estimar goles (menos de 3 partidos)"
    if fuente_goles is None and not _tiene_xg(d):
        valores = tuple(d.get(campo) for campo in _CAMPOS_PROMEDIOS)
        if all(v is None for v in valores):
            return "Sin promedios de goles de los equipos"
        try:
            if tuple(round(float(v), 2) for v in valores) == PROMEDIOS_RELLENO:
                return "Promedios de goles de relleno (sin estadísticas reales de los equipos)"
        except (TypeError, ValueError):
            return "Promedios de goles no numéricos"
    return None


def ejecutar_modulos(d: dict) -> tuple[dict[str, dict], dict[str, str]]:
    """Corre todos los módulos aplicables. Devuelve (resultados, modulos_skip) — mismo
    shape que armaba datos.py: resultados[modulo] = dict del análisis, modulos_skip[modulo]
    = razón por la que no corrió."""
    resultados: dict[str, dict] = {}
    modulos_skip: dict[str, str] = {}

    # El promedio genérico de una liga no contiene información de los dos equipos y producía la
    # misma tripleta para partidos distintos. Se conserva para auditoría upstream, pero no puede
    # votar ni generar un pick público. Poisson corre cuando tiene H2H, stats de equipo o xG.
    razon_poisson = razon_omitir_poisson(d)
    if razon_poisson:
        modulos_skip["poisson"] = razon_poisson
    else:
        resultados["poisson"] = pronostico_svc.analizar(d)
    if d.get("forma_datos_reales", False):
        resultados["forma"] = form_recent_svc.analizar(d)
    else:
        modulos_skip["forma"] = "Sin forma reciente real para ambos equipos"

    ok_h2h, razon_h2h = h2h_svc.validar_h2h(d)
    if ok_h2h:
        resultados["h2h"] = h2h_svc.analizar(d)
    else:
        modulos_skip["h2h"] = razon_h2h

    ok_odds, razon_odds = odds_svc.validar_odds(d)
    if ok_odds:
        resultados["odds"] = odds_svc.analizar(d)
    else:
        modulos_skip["odds"] = razon_odds

    ok_tabla, razon_tabla = tabla_pos_svc.validar_tabla(d)
    if ok_tabla:
        resultados["tabla"] = tabla_pos_svc.analizar(d)
    else:
        modulos_skip["tabla"] = razon_tabla

    # Dixon-Coles entrenado con histórico real (`services/modelo_historico.py`): participa solo si
    # la liga y ambos equipos están en sus artefactos; si no, queda registrado en `modulos_skip`.
    ok_historico, razon_historico = modelo_historico_svc.validar_historico(d)
    if ok_historico:
        resultados["historico"] = modelo_historico_svc.analizar(d)
    else:
        modulos_skip["historico"] = razon_historico

    ok_bsd, razon_bsd = bsd_predictions_svc.validar_bsd(d)
    if ok_bsd:
        resultados["bsd_ml"] = bsd_predictions_svc.analizar(d)
    else:
        modulos_skip["bsd_ml"] = razon_bsd

    return resultados, modulos_skip


log = logging.getLogger(__name__)


def _pronostico_modelo_laplace(d: dict) -> dict | None:
    """Resumen del modelo Laplace para este partido, o None. Nunca rompe el análisis: el modelo es una pieza independiente."""
    try:
        from backend.api.ml.laplace import servicio

        salida = servicio.pronosticar_partido(None, {"local": d.get("local", ""), "visitante": d.get("visitante", ""), "liga": d.get("liga", ""),
                                                      "pais": d.get("pais"), "liga_id": d.get("liga_id"),
                                                      "cuotas": [d.get("odds_local"), d.get("odds_empate"), d.get("odds_visit")] if d.get("odds_disponibles") else None}, canal="bot")
        return servicio.resumen_para_consumidores(salida)
    except Exception:  # noqa: BLE001
        log.warning("modelo Laplace no disponible para este partido", exc_info=True)
        return None


def analizar_partido(d: dict) -> dict:
    """Punto de entrada único: corre todos los módulos + consenso. Equivalente a lo que
    hacía `datos.py` (menos el fetch de datos externos, que todavía vive en
    gateway_unificado.py hasta portarse en la Parte 2)."""
    resultados, modulos_skip = ejecutar_modulos(d)

    partido = {
        "local": d.get("local", ""),
        "visitante": d.get("visitante", ""),
        "liga": d.get("liga", ""),
        "partido_id": d.get("partido_id", ""),
    }
    consenso = consenso_svc.calcular_consenso(resultados, partido)

    return {
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
        "modulos": resultados,
        "modulos_skip": modulos_skip,
        "consenso": consenso,
        # Pronóstico del modelo propio, INFORMATIVO: no entra al consenso (empata con Dixon-Coles, que ya está) y no cambia el pick.
        "modelo_laplace": _pronostico_modelo_laplace(d),
    }
