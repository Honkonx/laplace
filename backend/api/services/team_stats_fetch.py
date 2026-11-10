"""services/team_stats_fetch.py — Estadísticas de temporada de un equipo (api-football).

Port de wfb-032 (`Enriquecer Stats Equipo`) de WF-B — reemplaza los `goles_*_avg` genéricos
(promedio de liga) por el promedio real de temporada del equipo como local/visitante, cuando
hay `league_id`+`season`+`team_id` disponibles (vienen de `services/gateway.py::
buscar_fixture_id`). Cacheado 24h — las estadísticas de un equipo no cambian más de una vez
por jornada.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services._http_retry import CuotaApiFootballError, cuerpo_api_football, get_con_reintento_429

log = logging.getLogger("laplace.team_stats")

APIF_BASE = "https://v3.football.api-sports.io"
_temporadas_sin_acceso: set = set()  # temporadas que el plan de api-football en uso no deja consultar


async def enriquecer_stats_equipo(
    client: httpx.AsyncClient, db: Session, team_id: int, league_id: int, season: int
) -> dict | None:
    """Devuelve el JSON crudo de `teams/statistics` (goles a favor/en contra por partido,
    forma reciente) o None si faltan IDs, no hay API key, o la fuente falla."""
    if not (team_id and league_id and season and settings.SPORTS_API_KEY):
        return None
    if season in _temporadas_sin_acceso:
        return None  # el plan gratis ya rechazó esta temporada: no se gasta otra petición del día en repetirlo

    cache_key = f"team_stats:{team_id}:{league_id}:{season}"
    cacheado = leer_stats_cache(db, cache_key)
    if cacheado is not None:
        return cacheado

    try:
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/teams/statistics", log=log, fuente="api-football",
            params={"team": team_id, "league": league_id, "season": season},
            headers={"x-apisports-key": settings.SPORTS_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        data = cuerpo_api_football(r).get("response")
    except CuotaApiFootballError as exc:
        # Medido el 2026-10-19: el plan gratis solo sirve temporadas 2022-2024 ("do not have access to this season").
        # Antes cada análisis de 2026 gastaba 2 de las 100 peticiones diarias en un error que se leía como "sin datos".
        if "access to this season" in str(exc):
            _temporadas_sin_acceso.add(season)
        log.warning("team_stats sin acceso team_id=%s season=%s: %s", team_id, season, exc)
        return None
    except Exception:
        log.warning("team_stats fallo team_id=%s", team_id, exc_info=True)
        return None

    if not data:
        return None
    guardar_stats_cache(db, cache_key, "team_stats", data)
    return data


def extraer_goles_promedio(stats: dict | None) -> tuple[float | None, float | None]:
    """(goles_a_favor_promedio, goles_en_contra_promedio) desde la respuesta de
    `teams/statistics`, o (None, None) si no hay datos."""
    if not stats:
        return None, None
    a_favor = ((stats.get("goals") or {}).get("for") or {}).get("average", {}).get("total")
    en_contra = ((stats.get("goals") or {}).get("against") or {}).get("average", {}).get("total")
    try:
        return (float(a_favor) if a_favor is not None else None, float(en_contra) if en_contra is not None else None)
    except (TypeError, ValueError):
        return None, None
