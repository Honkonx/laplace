"""
services/gateway.py — Cascada de fixtures + enriquecimiento BSD.

Port de gateway_unificado.py (`--modo=ligas` y `--modo=bsd`) — misma cascada
de 4 fuentes (BD → LiveScore6 → BSD → api-football), mismo shape de `Stages`/`Events`
(compatibilidad con lo que ya consumen la app/el bot). Cambios reales vs el original:

  - `http_get` (urllib síncrono) → `httpx.AsyncClient` (async, con timeout explícito por
    request en vez de uno global).
  - `ejecutar_db_query(...)` por subprocess → llamadas directas a
    `db.partidos_repo` (misma sesión SQLAlchemy de la request, sin el riesgo de timeout de
    lanzar un proceso Python nuevo por cada consulta de caché).
  - Excepciones tipadas (`core.exceptions`) en vez de `except Exception` genérico silencioso
    — la cascada sigue tolerando que una fuente falle (eso es intencional, es una cascada de
    fallback), pero ahora se puede distinguir "esta fuente no tiene la API key configurada"
    de "esta fuente devolvió un error real" en los logs.

**No portado todavía** (queda para una ronda siguiente, no es parte del núcleo estadístico):
`--modo=forebet` (scraper HTML con BeautifulSoup — informativo, no entra al consenso) y
`--modo=resultados` (se porta en `services/resultados.py`, no acá).
"""
from __future__ import annotations

# Fachada: el código vive en `gateway_fuentes`, `gateway_cascada`, `gateway_bsd` y
# `gateway_fixture_id`. Los nombres se reexportan acá porque routers, bots, agentes y pruebas
# los usan (y parchean) como `gateway.<nombre>`; los dos diccionarios de estado en memoria son
# los MISMOS objetos que usan los módulos nuevos (no se reasignan).
from backend.api.core.config import settings  # noqa: F401
from backend.api.services._http_retry import CuotaApiFootballError  # noqa: F401  (los tests lo leen como gateway.CuotaApiFootballError)
from backend.api.services.gateway_bsd import _bsd_buscar_event_id, enriquecer_bsd
from backend.api.services.gateway_cascada import (
    _fixtures_locks,
    _fixtures_locks_guard,
    _lock_para_fecha,
    guardar_stages_en_cache,
    obtener_fixtures_cascada,
)
from backend.api.services.gateway_fixture_id import (
    _TTL_DIA_APIF,
    _fixtures_apif_dia,
    _fixtures_apifootball_del_dia,
    _match_equipo,
    buscar_fixture_id,
)
from backend.api.services.gateway_fuentes import (
    APIF_BASE,
    BSD_BASE,
    LIVESCORE6_URL,
    UTC_OFFSET,
    _apifootball_stages,
    _bd_stages,
    _bsd_stages,
    _build_img,
    _livescore6_stages,
    _timestamp_to_esd,
    _timestamp_to_iso,
    _yyyymmdd_to_bd,
    log,
    slug_de_liga,
)

__all__ = [
    "APIF_BASE", "BSD_BASE", "LIVESCORE6_URL", "UTC_OFFSET", "_TTL_DIA_APIF", "CuotaApiFootballError",
    "_apifootball_stages", "_bd_stages", "_bsd_buscar_event_id", "_bsd_stages", "_build_img",
    "_fixtures_apif_dia", "_fixtures_apifootball_del_dia", "_fixtures_locks", "_fixtures_locks_guard",
    "_livescore6_stages", "_lock_para_fecha", "_match_equipo", "_timestamp_to_esd", "_timestamp_to_iso",
    "_yyyymmdd_to_bd", "buscar_fixture_id", "enriquecer_bsd", "guardar_stages_en_cache", "log",
    "obtener_fixtures_cascada", "settings", "slug_de_liga",
]
