"""
services/gateway_fixture_id.py — Resolución del `fixture_id` de api-football por nombre+fecha, con
la caché en memoria de los partidos del día. Dividido de `gateway.py` sin cambiar comportamiento;
`gateway.py` reexporta estos nombres.
"""
from __future__ import annotations

import logging
import time

import httpx

from backend.api.core.config import settings
from backend.api.db import fixture_cache_repo
from backend.api.services._http_retry import cuerpo_api_football, get_con_reintento_429
from backend.api.services.circuit_breaker import obtener_circuit_breaker
from backend.api.services.gateway_cascada import _lock_para_fecha
from backend.api.services.gateway_fuentes import APIF_BASE, _yyyymmdd_to_bd
from backend.api.services.normalizacion import normalizar_nombre

log = logging.getLogger("laplace.gateway")


# ─── Resolución de fixture_id de api-football por nombre+fecha ────────────────
# Port de wfb-006 (`Extraer Info Partido`) — matchea el partido (identificado por nombre desde
# la cascada de fixtures, que no trae IDs de api-football) contra `/fixtures?date=` para poder
# usar los endpoints de api-football que sí requieren su propio fixture_id (odds, H2H,
# standings de equipo). Cacheado por `match_id` (24h informal, ver fixture_cache_repo).


def _match_equipo(nombre_api: str, nombre_buscado: str) -> bool:
    a, b = normalizar_nombre(nombre_api), normalizar_nombre(nombre_buscado)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return True
    return a.split(" ")[0] == b.split(" ")[0]


# api-football devuelve TODOS los partidos de un día en una sola petición. Antes cada análisis repetía esa
# petición (100/día y 10/min en el plan gratis, medido el 2026-10-09: 429 al analizar varios partidos seguidos); ahora
# se pide una vez por día y se reutiliza durante `_TTL_DIA_APIF` segundos, con un solo vuelo por fecha.
_TTL_DIA_APIF = 3 * 3600
_fixtures_apif_dia: dict[str, tuple[float, list[dict]]] = {}


async def _fixtures_apifootball_del_dia(client: httpx.AsyncClient, fecha_bd: str) -> list[dict]:
    ahora = time.monotonic()
    cacheado = _fixtures_apif_dia.get(fecha_bd)
    if cacheado and ahora - cacheado[0] < _TTL_DIA_APIF:
        return cacheado[1]
    async with await _lock_para_fecha(f"apif:{fecha_bd}"):
        cacheado = _fixtures_apif_dia.get(fecha_bd)
        if cacheado and time.monotonic() - cacheado[0] < _TTL_DIA_APIF:
            return cacheado[1]
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/fixtures", log=log, fuente="api-football",
            params={"date": fecha_bd, "timezone": "America/Santiago"},
            headers={"x-apisports-key": settings.SPORTS_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        # HTTP 200 con `errors` = cuota agotada o plan sin acceso: antes se leía como "sin partidos" sin avisar.
        fixtures = cuerpo_api_football(r).get("response", [])
        if len(_fixtures_apif_dia) > 8:
            _fixtures_apif_dia.clear()
        _fixtures_apif_dia[fecha_bd] = (time.monotonic(), fixtures)
        return fixtures


async def buscar_fixture_id(
    db, client: httpx.AsyncClient, match_id: str, local: str, visitante: str, fecha_raw: str
) -> dict:
    """Devuelve {apifootball_fixture_id, apifootball_league_id, apifootball_season,
    apifootball_team_home, apifootball_team_away} — todos None si no matchea o falla. Usa
    caché por match_id antes de llamar a la API (evita 1 request por partido en cada
    análisis repetido del mismo día).

    Bug real encontrado 2026-09-10 (investigación de por qué la mayoría de los picks daban
    "Empate"): el parámetro se llamaba `fecha_bd` pero en realidad recibía `fecha_raw` sin
    convertir (`YYYYMMDD`, el formato de LiveScore6) — ambos callers reales
    (`analisis_completo.py::_enriquecer_partido`, `laplace_agents/seleccion.py`) pasan la fecha
    cruda del job/fixture, nunca el formato "bd" (`Y-m-d`) que el nombre sugería. api-football
    espera `Y-m-d` en `GET /fixtures?date=` — con el formato crudo, la API devolvía HTTP 200 con
    `response: []` (nunca un 4xx, así que `raise_for_status()` nunca lo detectaba) — CERO
    partidos matcheaban, siempre, en toda la historia del proyecto (confirmado:
    `fixture_id_cache` tenía 0 filas reales). Verificado en vivo con la API real: `date=20260910`
    → 0 resultados; `date=2026-09-10` → 173 partidos reales. Esto desactivaba en cascada la
    resolución de liga por `league_id` numérico (`ligas.resolver_liga_por_id`) y el fallback de
    datos reales por equipo (`h2h_fetch._desde_stats_equipo`/`team_stats_fetch`) — ver
    `INVESTIGACION_MOTOR_PREDICCION_2026-09.md` §1.5. Fix: renombrado el
    parámetro a `fecha_raw` (honesto sobre lo que realmente recibe) y convertido con el mismo
    helper `_yyyymmdd_to_bd()` que ya usan el resto de las funciones de este archivo (línea 52)
    — nunca se había usado acá, esta función quedó afuera de ese patrón por error al escribirla.
    Se sigue guardando `fecha_raw` tal cual en `fixture_id_cache` (no es la clave de caché, solo
    un campo de referencia sin ningún lector real, confirmado en `db/fixture_cache_repo.py`)."""
    fecha_bd = _yyyymmdd_to_bd(fecha_raw) if fecha_raw and len(fecha_raw) == 8 else fecha_raw
    vacio = {
        "apifootball_fixture_id": None,
        "apifootball_league_id": None,
        "apifootball_season": None,
        "apifootball_team_home": None,
        "apifootball_team_away": None,
    }

    cacheado = fixture_cache_repo.leer_fixture_cache(db, match_id)
    if cacheado.get("hit") and cacheado.get("apifootball_fixture_id"):
        return {
            "apifootball_fixture_id": cacheado["apifootball_fixture_id"],
            "apifootball_league_id": cacheado["league_id"],
            "apifootball_season": cacheado["season"],
            "apifootball_team_home": cacheado["team_home_id"],
            "apifootball_team_away": cacheado["team_away_id"],
        }

    if not settings.SPORTS_API_KEY:
        return vacio

    breaker_apif = obtener_circuit_breaker("api-football")
    if not breaker_apif.permite_llamada():
        log.warning("buscar_fixture_id saltado match_id=%s — circuit breaker de api-football abierto", match_id)
        return vacio

    try:
        fixtures = await _fixtures_apifootball_del_dia(client, fecha_bd)
    except Exception:
        breaker_apif.registrar_fallo()
        log.warning("buscar_fixture_id fallo match_id=%s", match_id, exc_info=True)
        return vacio
    breaker_apif.registrar_exito()

    for f in fixtures:
        home = ((f.get("teams") or {}).get("home") or {}).get("name", "")
        away = ((f.get("teams") or {}).get("away") or {}).get("name", "")
        if _match_equipo(home, local) and _match_equipo(away, visitante):
            resultado = {
                "apifootball_fixture_id": (f.get("fixture") or {}).get("id"),
                "apifootball_league_id": (f.get("league") or {}).get("id"),
                "apifootball_season": (f.get("league") or {}).get("season"),
                "apifootball_team_home": ((f.get("teams") or {}).get("home") or {}).get("id"),
                "apifootball_team_away": ((f.get("teams") or {}).get("away") or {}).get("id"),
            }
            fixture_cache_repo.guardar_fixture_cache(
                db,
                match_id,
                fecha_raw,
                resultado["apifootball_fixture_id"],
                league_id=resultado["apifootball_league_id"],
                season=resultado["apifootball_season"],
                team_home_id=resultado["apifootball_team_home"],
                team_away_id=resultado["apifootball_team_away"],
            )
            return resultado
    return vacio
