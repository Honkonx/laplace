"""services/standings_fetch.py — Tabla de posiciones (football-data.org), cacheada 24h.

Port de los nodos `GET Standings` (wfb-008) y `Extraer Forma y Tabla` (wfb-009) de WF-B.
`obtener_standings()` hace el fetch con caché; `extraer_posicion_y_forma()` hace el matching
de nombre de equipo contra la tabla devuelta y arma el texto de resumen para el prompt de
Claude — separados porque el primero es genérico (una tabla completa) y el segundo se llama
dos veces por partido (local y visitante).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services._http_retry import get_con_reintento_429

log = logging.getLogger("laplace.standings")

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"


async def obtener_standings(client: httpx.AsyncClient, db: Session, league_code: str, season: str) -> dict | None:
    """Devuelve el JSON crudo de standings de football-data.org (clave `standings`, lista de
    grupos — normalmente solo el grupo `TOTAL`), o None si la liga no tiene código football-
    data.org, no hay API key, o la fuente falla. Nunca lanza — el caller decide el fallback
    (mismo criterio que WF-B: sin tabla, usa forma/goles recientes)."""
    if not league_code or not settings.FOOTBALL_DATA_KEY:
        return None

    cache_key = f"standings:{league_code}:{season}"
    cacheado = leer_stats_cache(db, cache_key)
    if cacheado is not None:
        return cacheado

    try:
        r = await get_con_reintento_429(
            client, f"{FOOTBALL_DATA_BASE}/competitions/{league_code}/standings", log=log, fuente="football-data",
            headers={"X-Auth-Token": settings.FOOTBALL_DATA_KEY},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.warning("standings fallo league_code=%s", league_code, exc_info=True)
        return None

    guardar_stats_cache(db, cache_key, "standings", data)
    return data


def _forma_wins(form: str | None) -> int:
    """Cuenta victorias ('W') en el string de forma reciente de football-data.org (ej. 'WWDLW')."""
    return (form or "").count("W")


def _coincide_equipo(nombre_tabla: str, nombre_buscado: str) -> bool:
    a = (nombre_tabla or "").lower()
    b = (nombre_buscado or "").lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return any(len(w) > 3 and w in a for w in b.split())


def _fila_equipo(standings: dict, nombre_equipo: str) -> dict | None:
    grupos = standings.get("standings") or []
    if not grupos:
        return None
    tabla = grupos[0].get("table") or []
    buscado = (nombre_equipo or "").strip().lower()
    for fila in tabla:  # primero el nombre EXACTO: «Real Madrid» no debe emparejar con la fila «Real Betis» solo porque comparten «real»
        if buscado and ((fila.get("team") or {}).get("name") or "").strip().lower() == buscado:
            return fila
    for fila in tabla:
        nombre_tabla = (fila.get("team") or {}).get("name", "")
        if _coincide_equipo(nombre_tabla, nombre_equipo):
            return fila
    return None


def extraer_posicion_y_forma(standings: dict | None, nombre_equipo: str) -> tuple[int, int, str]:
    """Devuelve (posicion, victorias_recientes, texto_resumen) para `nombre_equipo` dentro de
    `standings`. Defaults (10, 2, "Sin datos en tabla") si no hay tabla o no matchea — mismos
    defaults que usaba WF-B cuando `standings_info` quedaba en 'Sin datos'."""
    if not standings:
        return 10, 2, f"{nombre_equipo}: Sin datos en tabla"

    fila = _fila_equipo(standings, nombre_equipo)
    if fila is None:
        return 10, 2, f"{nombre_equipo}: Sin datos en tabla"

    posicion = fila.get("position") or 10
    forma = fila.get("form") or ""
    victorias = _forma_wins(forma)
    texto = (
        f"{nombre_equipo}: Pos {posicion}, {fila.get('points', '?')} pts, Forma: {forma or 'N/A'}, "
        f"{fila.get('playedGames', '?')}PJ ({fila.get('won', '?')}G-{fila.get('draw', '?')}E-"
        f"{fila.get('lost', '?')}P), Goles {fila.get('goalsFor', '?')}:{fila.get('goalsAgainst', '?')}, "
        f"DG: {fila.get('goalDifference', '?')}"
    )
    return posicion, victorias, texto
