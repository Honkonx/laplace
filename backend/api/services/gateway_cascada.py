"""
services/gateway_cascada.py — Cascada de fixtures BD → LiveScore6 → BSD → api-football, con
single-flight por fecha, y la persistencia de los stages en `partidos_dia`. Dividido de
`gateway.py` sin cambiar comportamiento; `gateway.py` reexporta estos nombres.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from backend.api.db import partidos_repo
from backend.api.services import ligas_ident
from backend.api.services.gateway_fuentes import (
    _apifootball_stages,
    _bd_stages,
    _bsd_stages,
    _build_img,
    _livescore6_stages,
    _yyyymmdd_to_bd,
)

log = logging.getLogger("laplace.gateway")


# ─── Single-flight por fecha ───────────────────────────────────────────────────
# Auditoría real (2026-09-09): sin lock, 2 requests casi simultáneas para la misma fecha
# leían la caché ANTES de que la primera terminara de escribirla — ambas veían "sin caché"
# y disparaban la cascada completa de red en paralelo (llamadas duplicadas e innecesarias
# a APIs externas con cuota limitada). El backend corre en un solo proceso/event loop
# (confirmado por otra auditoría de esta sesión) — un asyncio.Lock en memoria alcanza, no
# hace falta un lock distribuido (Redis, etc.) para esto hoy.
_fixtures_locks: dict[str, asyncio.Lock] = {}
_fixtures_locks_guard = asyncio.Lock()


async def _lock_para_fecha(fecha_raw: str) -> asyncio.Lock:
    """Devuelve el asyncio.Lock de `fecha_raw`, creándolo si es la primera vez — la
    creación del lock en sí queda protegida por `_fixtures_locks_guard` para que dos
    corutinas no puedan crear cada una su propio Lock para la misma fecha."""
    async with _fixtures_locks_guard:
        lock = _fixtures_locks.get(fecha_raw)
        if lock is None:
            lock = asyncio.Lock()
            _fixtures_locks[fecha_raw] = lock
        return lock


async def obtener_fixtures_cascada(db, client: httpx.AsyncClient, fecha_raw: str) -> tuple[list[dict], str]:
    """Cascada BD → LiveScore6 → BSD → api-football. Devuelve (stages, nombre_fuente) —
    la primera fuente que responda con datos gana, igual que gateway_unificado.py.

    Single-flight por fecha: si la BD no tiene caché, se toma el lock de esa fecha antes de
    llamar a las fuentes de red. Un segundo caller que pida la misma fecha mientras el primero
    sigue en la cascada espera en el lock — al entrar, vuelve a leer la BD (que el primero ya
    dejó escrita, ver `guardar_stages_en_cache` más abajo) en vez de repetir la cascada."""
    stages = _bd_stages(db, fecha_raw)
    if stages:
        return stages, "bd"

    lock = await _lock_para_fecha(fecha_raw)
    async with lock:
        # Re-chequeo dentro del lock: si otra corutina ganó la carrera y ya guardó en
        # caché mientras esperábamos, usamos eso en vez de repetir la cascada de red.
        stages = _bd_stages(db, fecha_raw)
        if stages:
            return stages, "bd"

        fuentes = [
            ("livescore6", lambda: _livescore6_stages(client, fecha_raw)),
            ("bsd", lambda: _bsd_stages(client, fecha_raw)),
            ("api-football", lambda: _apifootball_stages(client, fecha_raw)),
        ]
        for nombre, fn in fuentes:
            try:
                stages = await fn()
                if stages:
                    log.info("fixtures fuente=%s stages=%d", nombre, len(stages))
                    guardar_stages_en_cache(db, fecha_raw, stages, nombre)
                    return stages, nombre
            except Exception as e:  # noqa: BLE001 — cascada de fallback intencional, cada fuente puede fallar
                log.warning("fixtures fuente=%s fallo: %s", nombre, str(e)[:150])
        log.error("todas las fuentes de fixtures fallaron fecha=%s", fecha_raw)
        return [], "none"


def guardar_stages_en_cache(db, fecha_raw: str, stages: list[dict], fuente: str) -> int:
    """Persiste los stages obtenidos de una fuente externa en `partidos_dia`, para que la
    próxima consulta del mismo día pegue en 'bd' sin llamar a la API externa de nuevo."""
    if fuente == "bd" or not stages:
        return 0
    fecha_bd = _yyyymmdd_to_bd(fecha_raw)
    partidos = []
    for stage in stages:
        liga_nombre = stage.get("Snm") or "Otras"
        pais = str(stage.get("Cnm") or stage.get("pais") or "").strip()
        liga_slug = stage.get("liga_slug") or ligas_ident.slug_competicion(liga_nombre, pais)
        liga_logo = _build_img(stage.get("Img") or stage.get("Logo") or stage.get("CompImg") or stage.get("badgeUrl") or "")
        for ev in stage.get("Events", []):
            match_id = str(ev.get("Eid", "")).strip()
            if not match_id:
                continue
            esd = str(ev.get("Esd", "") or "")
            hora_str = f"{esd[8:10]}:{esd[10:12]}" if len(esd) >= 12 else ""
            partidos.append(
                {
                    "match_id": match_id,
                    "liga_slug": liga_slug,
                    "liga_nombre": liga_nombre,
                    "liga_pais": pais or None,
                    "liga_logo": liga_logo,
                    "local": ev.get("T1", [{}])[0].get("Nm", "Local"),
                    "visitante": ev.get("T2", [{}])[0].get("Nm", "Visit"),
                    "hora_chile": hora_str,
                    "kick_off_utc": ev.get("kick_off_utc", ""),
                    "logo_local": _build_img(ev.get("T1", [{}])[0].get("Img", "")),
                    "logo_visitante": _build_img(ev.get("T2", [{}])[0].get("Img", "")),
                    "status": "scheduled",
                }
            )
    return partidos_repo.guardar_ligas_cache(db, fecha_bd, partidos) if partidos else 0
