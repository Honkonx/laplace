"""
services/analisis_completo_enriquecimiento.py — Arma el dict `d` que espera el motor (standings, odds, H2H, BSD) para un partido. Dividido de `analisis_completo.py` sin cambiar
comportamiento; `analisis_completo.py` reexporta estos nombres.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.db import partidos_repo
from backend.api.services import bsd_predictions, gateway, h2h_fetch, ligas, odds_fetch, standings_fetch, tabla_propia
from backend.api.services import calidad_datos as calidad_datos_svc

log = logging.getLogger("laplace.analisis")


def _texto_odds(odds: dict, local: str, visitante: str) -> str:
    if odds.get("odds_disponibles"):
        return (
            f"{local} @{odds['odds_local']} | Empate @{odds['odds_empate']} | "
            f"{visitante} @{odds['odds_visit']} [{odds.get('odds_source', '')}]"
        )
    return odds.get("odds_info_externo") or "Sin odds disponibles — análisis estadístico puro."


async def _standings_o_none(
    client: httpx.AsyncClient, db: Session, tabla_codigo: str | None, fixture_info: dict
) -> list | None:
    if not tabla_codigo:
        return None
    return await standings_fetch.obtener_standings(
        client, db, tabla_codigo, str(fixture_info.get("apifootball_season") or "current")
    )


async def _bsd_prediccion_segura(client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    """Wrapper de bsd_predictions.obtener_prediccion_externa_bsd que nunca deja que un fallo de
    BSD bloquee el resto del consenso — bsd_ml es un módulo opcional más (mismo criterio que
    h2h/odds/tabla cuando sus propios validar_* dicen que no hay datos suficientes:
    `motor.py::validar_bsd` lo saltea si `bsd_prediccion` queda en None). La función interna ya
    atrapa sus propios errores de red y devuelve None — este wrapper es una segunda red de
    seguridad defensiva ante cualquier excepción no prevista."""
    try:
        return await bsd_predictions.obtener_prediccion_externa_bsd(client, local, visitante, fecha)
    except Exception:
        log.warning(
            "BSD prediction (bsd_ml) fallo local=%s visitante=%s — se omite del consenso",
            local, visitante, exc_info=True,
        )
        return None


async def _bsd_xg_seguro(db: Session, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    """Wrapper de `gateway.enriquecer_bsd()` — trae xG real de BSD para el partido (mismo
    criterio defensivo que `_bsd_prediccion_segura`: nunca deja que un fallo de BSD bloquee el
    resto del consenso). Solo se usan los campos `xg_local`/`xg_visit`/`xg_disponible` de acá —
    `odds_local`/`odds_empate`/`odds_visit` de `enriquecer_bsd()` se ignoran a propósito, la
    cascada real de odds ya vive en `odds_fetch.obtener_odds_partido` (incluye su propia fuente
    BSD, `_bsd_odds`) y no hace falta un segundo camino.

    Hallazgo real 2026-09-09/10 (`INVESTIGACION_MOTOR_PREDICCION_2026-09.md`
    §1.4): `pronostico.py::calcular_lambdas()` ya sabía mezclar xG real (peso 0.30) y
    `gateway.py::enriquecer_bsd()` ya sabía traerlo de BSD — pero ningún caller de producción
    llamaba a `enriquecer_bsd()`, así que `xg_usado` era `False` siempre. Conectado acá."""
    try:
        return await gateway.enriquecer_bsd(db, client, local, visitante, fecha)
    except Exception:
        log.warning(
            "BSD xG fallo local=%s visitante=%s — se omite del consenso (mismo peso 0 que si "
            "xg_local/xg_visit nunca llegan, ver pronostico.calcular_lambdas)",
            local, visitante, exc_info=True,
        )
        return None


async def _enriquecer_partido(db: Session, client: httpx.AsyncClient, partido: dict, match_id: str, fecha: str) -> dict:
    """Arma el dict `d` que espera `services/motor.py` — cascada de standings/odds/H2H/BSD,
    equivalente a wfb-007 (Mapear Liga) + wfb-008..wfb-015 de WF-B (+ wfb-031 para BSD).

    standings/odds/H2H/BSD(pick)/BSD(xG) son 5 fuentes HTTP independientes una vez resuelto
    `fixture_info` — antes corrían con `await` secuenciales (latencia real = suma de todas);
    acá corren en paralelo vía `asyncio.gather` (latencia real = la del más lento de todas)."""
    local, visitante, liga = partido["local"], partido["visitante"], partido["liga"]

    fixture_info = await gateway.buscar_fixture_id(db, client, match_id, local, visitante, fecha)
    # Resolución por league_id numérico (2026-09-09) — prioriza el id real de api-football
    # (inequívoco) sobre el nombre de texto libre (potencialmente ambiguo, ver
    # ligas.CLAVES_AMBIGUAS_EN_ORIGEN). Cae a mapear_liga()/get_liga_avg() de siempre cuando el
    # id no está en la tabla curada — mismo comportamiento que antes para esos casos.
    liga_avg, tabla_codigo, odds_key = ligas.resolver_liga_por_id(
        fixture_info.get("apifootball_league_id"), liga, 2.60
    )
    kick_off_utc = partidos_repo.leer_kick_off_utc(db, match_id, fecha)

    standings, odds, h2h, bsd_prediccion, bsd_xg = await asyncio.gather(
        _standings_o_none(client, db, tabla_codigo, fixture_info),
        odds_fetch.obtener_odds_partido(
            client, db, local, visitante, odds_key, fixture_info.get("apifootball_fixture_id"), fecha,
            kick_off_utc,
        ),
        h2h_fetch.obtener_h2h(
            client, db,
            fixture_info.get("apifootball_team_home"), fixture_info.get("apifootball_team_away"),
            local, visitante, liga, liga_avg,
            league_id=fixture_info.get("apifootball_league_id"), season=fixture_info.get("apifootball_season"),
        ),
        _bsd_prediccion_segura(client, local, visitante, fecha),
        _bsd_xg_seguro(db, client, local, visitante, fecha),
    )

    pos_local = pos_visit = 10
    forma_local_wins = forma_visit_wins = None
    tabla_datos_reales = False
    forma_datos_reales = False
    standings_info = "Datos de tabla no disponibles para esta liga."
    if not standings:  # sin API-Football ni football-data.org: la tabla sale de los resultados propios si la liga es completa y los datos son recientes
        standings = await asyncio.to_thread(tabla_propia.construir, local, visitante, liga)
    if standings:
        pos_local, forma_local_wins, txt_local = standings_fetch.extraer_posicion_y_forma(standings, local)
        pos_visit, forma_visit_wins, txt_visit = standings_fetch.extraer_posicion_y_forma(standings, visitante)
        standings_info = f"LOCAL {txt_local} | VISITANTE {txt_visit}" + (" (tabla con resultados propios)" if standings.get("fuente") == "resultados_propios" else "")
        tabla_datos_reales = "Sin datos en tabla" not in txt_local and "Sin datos en tabla" not in txt_visit
        forma_datos_reales = tabla_datos_reales and "Forma: N/A" not in txt_local and "Forma: N/A" not in txt_visit
        if not tabla_datos_reales:
            # Solo uno de los dos equipos figura en la tabla: la posición por defecto del otro (10) no es un dato.
            # Con una real y otra inventada el módulo `tabla` comparaba contra un 10 falso (auditoría 2026-10-09, C4).
            pos_local = pos_visit = 10
            forma_local_wins = forma_visit_wins = None

    # Los defaults permiten que el pipeline siga operando cuando un proveedor cae, pero no son
    # evidencia suficiente para publicar probabilidades. Antes eran tratados como datos reales y
    # producían la misma predicción para partidos distintos. La puerta (única, compartida con
    # Top Picks: `calidad_datos.calcular_calidad_datos`) cuenta canales independientes — odds y
    # BSD son un solo canal de mercado — y reconoce `historico` cuando valida la liga y equipos.
    fuentes_crudas = {
        "tabla": tabla_datos_reales,
        "odds": bool(odds.get("odds_disponibles", False)),
        "h2h": bool(h2h.get("h2h_disponible", False) and h2h.get("h2h_total", 0) >= 3),
        "estadisticas_equipo": h2h.get("fuente_goles") == "stats_equipo_real",
        "xg": bool((bsd_xg or {}).get("xg_local") and (bsd_xg or {}).get("xg_visit")),
        "bsd": bool(bsd_prediccion),
    }

    datos = {
        "local": local, "visitante": visitante, "liga": liga,
        "partido": f"{local} vs {visitante}", "partido_id": match_id,
        # Id numérico de API-Football: desambigua la liga para el módulo `historico` sin depender del texto.
        "liga_id": fixture_info.get("apifootball_league_id"),
        "pos_local": pos_local, "pos_visit": pos_visit,
        "forma_local_wins": forma_local_wins, "forma_visit_wins": forma_visit_wins,
        "forma_datos_reales": forma_datos_reales,
        "standings_info": standings_info,
        "odds_local": odds.get("odds_local"), "odds_empate": odds.get("odds_empate"),
        "odds_visit": odds.get("odds_visit"), "odds_disponibles": odds.get("odds_disponibles", False),
        "odds_info": _texto_odds(odds, local, visitante),
        "goles_local_avg": h2h["goles_local_avg"], "goles_visit_avg": h2h["goles_visit_avg"],
        "goles_contra_local_avg": h2h["goles_contra_local_avg"], "goles_contra_visit_avg": h2h["goles_contra_visit_avg"],
        "fuente_goles": h2h.get("fuente_goles", "liga_generico"),
        "liga_goles_avg": liga_avg,
        "h2h_local_wins": h2h["h2h_local_wins"], "h2h_visit_wins": h2h["h2h_visit_wins"],
        "h2h_empates": h2h["h2h_empates"], "h2h_total": h2h["h2h_total"],
        "h2h_disponible": h2h["h2h_disponible"], "h2h_resumen": h2h["h2h_resumen"],
        "total_h2h": h2h["h2h_total"],
        "bsd_prediccion": bsd_prediccion,
        "xg_local": (bsd_xg or {}).get("xg_local"),
        "xg_visit": (bsd_xg or {}).get("xg_visit"),
    }
    datos["calidad_datos"] = calidad_datos_svc.calcular_calidad_datos(fuentes_crudas, datos)
    return datos
