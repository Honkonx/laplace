"""
services/gateway_bsd.py — Enriquecimiento BSD (xG, odds, ML, lesionados) y resolución del
`event_id` de BSD. Dividido de `gateway.py` sin cambiar comportamiento; `gateway.py` reexporta
estos nombres.
"""
from __future__ import annotations

import logging

import httpx

from backend.api.core.config import settings
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services._http_retry import get_con_reintento_429
from backend.api.services.circuit_breaker import obtener_circuit_breaker
from backend.api.services.gateway_fuentes import BSD_BASE
from backend.api.services.normalizacion import (
    coincide_nombre,
    limpiar_sufijos,
    nombre_equipo_bsd,
    normalizar_nombre,
)

log = logging.getLogger("laplace.gateway")


async def _bsd_buscar_event_id(db, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> str | None:
    """Resuelve el `event_id` de BSD para (local, visitante, fecha) — cacheado en
    `stats_cache` (tipo `bsd_event_id`, TTL ver `db/cache.py::TTL_HORAS_POR_TIPO`).

    Antes de este cambio, cada llamada a `enriquecer_bsd` repetía esta búsqueda completa
    (hasta 2 requests HTTP a BSD) aunque ya se hubiera resuelto el mismo partido minutos
    antes — a diferencia de `buscar_fixture_id`, que sí cacheaba vía `fixture_cache_repo`
    (hallazgo real de la auditoría de esta sesión). Reusa el patrón cache-aside genérico de
    `db/cache.py` (mismo mecanismo que `standings`/`h2h`/`team_stats`) en vez de agregar una
    tabla dedicada tipo `fixture_id_cache` — acá no hay un `match_id` propio para usar como
    clave (la firma es por nombre+fecha, no por partido de la cascada de fixtures), así que
    una clave compuesta sobre el caché genérico es más simple y evita una migración nueva
    solo para esto. Solo se cachea sobre un match encontrado (positivo) — igual criterio que
    `buscar_fixture_id`, que tampoco cachea "no encontrado" (un partido puede aparecer en BSD
    más tarde dentro de la ventana de TTL)."""
    if not settings.BSD_API_KEY:
        return None

    f = (fecha or "").strip()
    fecha_iso = f"{f[:4]}-{f[4:6]}-{f[6:8]}" if (len(f) == 8 and f.isdigit()) else f
    cache_key = f"bsd_event_id:{normalizar_nombre(local)}:{normalizar_nombre(visitante)}:{fecha_iso}"
    cacheado = leer_stats_cache(db, cache_key)
    if cacheado is not None:
        return cacheado.get("event_id")

    breaker_bsd = obtener_circuit_breaker("bsd")
    if not breaker_bsd.permite_llamada():
        log.warning("bsd_buscar_event_id saltado — circuit breaker de bsd abierto")
        return None

    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}
    local_busq = limpiar_sufijos(local)
    visit_busq = limpiar_sufijos(visitante)

    for team_q in (local_busq[:15], visit_busq[:15]):
        url = f"{BSD_BASE}/events/?date_from={fecha_iso}&date_to={fecha_iso}&team_name={team_q}&limit=20"
        try:
            r = await get_con_reintento_429(client, url, log=log, fuente="bsd", headers=headers, timeout=10)
            r.raise_for_status()
        except Exception as exc:
            log.warning("gateway: BSD eventos falló: %s", exc)
            breaker_bsd.registrar_fallo()
            continue
        breaker_bsd.registrar_exito()
        for evento in r.json().get("results", []):
            home = nombre_equipo_bsd(evento.get("home_team"))
            away = nombre_equipo_bsd(evento.get("away_team"))
            if coincide_nombre(home, local_busq) and coincide_nombre(away, visit_busq):
                event_id = evento.get("id") or evento.get("event_id")
                guardar_stats_cache(db, cache_key, "bsd_event_id", {"event_id": event_id})
                return event_id
    return None


async def enriquecer_bsd(db, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict:
    """Busca el partido en BSD y trae xG, odds, predicción ML y jugadores no disponibles.
    `found: False` si no se encuentra o la API key no está configurada — nunca lanza, el
    caller (services/motor.py, cuando integre esto) decide si el análisis sigue sin BSD."""
    breaker_bsd = obtener_circuit_breaker("bsd")
    if not breaker_bsd.permite_llamada():
        log.warning("enriquecer_bsd saltado — circuit breaker de bsd abierto")
        return {"found": False, "motivo": "Circuit breaker de BSD abierto (fallos recientes)", "fuente": "bsd"}

    event_id = await _bsd_buscar_event_id(db, client, local, visitante, fecha)
    if not event_id:
        return {"found": False, "motivo": "Partido no encontrado en BSD", "fuente": "bsd"}

    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}

    async def _get(url: str) -> dict:
        try:
            r = await get_con_reintento_429(client, url, log=log, fuente="bsd", headers=headers, timeout=10)
            r.raise_for_status()
        except Exception as exc:
            log.warning("gateway: BSD consulta falló: %s", exc)
            breaker_bsd.registrar_fallo()
            return {}
        breaker_bsd.registrar_exito()
        return r.json()

    odds_raw = (await _get(f"{BSD_BASE}/events/{event_id}/odds/")).get("odds", {})
    evento = await _get(f"{BSD_BASE}/events/{event_id}/")

    xg_local = evento.get("xg_home") or evento.get("xg_local")
    xg_visit = evento.get("xg_away") or evento.get("xg_visit")

    return {
        "found": True,
        "event_id": event_id,
        "xg_local": xg_local,
        "xg_visit": xg_visit,
        "xg_disponible": xg_local is not None and xg_visit is not None,
        "odds_local": odds_raw.get("home_win"),
        "odds_empate": odds_raw.get("draw"),
        "odds_visit": odds_raw.get("away_win"),
        "odds_disponibles": all(odds_raw.get(k) is not None for k in ("home_win", "draw", "away_win")),
        "fuente": "bsd",
    }
