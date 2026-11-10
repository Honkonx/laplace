"""services/refresco_cuotas.py — Job de refresco de cuotas (The Odds API) y tablas (football-data)
de los partidos de hoy y mañana, respetando la cuota de las APIs.

Motivo (auditoría 2026-10-06, verificado en la BD real): las 79 entradas `odds` de `stats_cache`
y las 9 de `standings` estaban expiradas (la última, del 2026-09-28) porque nada las renovaba
fuera de un análisis pedido por un usuario; el apilador casi no se usaba en vivo.

Presupuesto (The Odds API, plan de ~500 créditos/mes; cada petición con `h2h,totals` en región
`eu` cuesta 2 créditos):
- UNA petición por liga (`odds_fetch.refrescar_odds_liga`): la respuesta trae todos los eventos de
  la liga y queda cacheada para todos sus partidos — no una petición por partido.
- Tope diario de peticiones (`LAPLACE_REFRESCO_ODDS_MAX_DIA`, defecto 4 = ~8 créditos/día ~ 240/mes).
  El tope cuenta TODO el consumo del día registrado por `odds_fetch` (también el de análisis de
  usuarios), no solo el de este job. Las ligas con más partidos próximos van primero.
- Standings (football-data.org, gratis; solo se respeta su TTL de 24h): tope
  `LAPLACE_REFRESCO_STANDINGS_MAX_DIA` (defecto 12).
- Solo partidos aún `scheduled` (sin empezar) con liga mapeada a odds/tabla; lo ya cacheado y
  vigente no se vuelve a pedir.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from backend.api.db.cache import leer_stats_cache
from backend.api.models.partidos import PartidoDia
from backend.api.services import ligas, odds_fetch, standings_fetch

log = logging.getLogger("laplace.refresco_cuotas")

TZ_CHILE = ZoneInfo("America/Santiago")
MAX_PETICIONES_ODDS_DIA_DEFECTO = 4
MAX_PETICIONES_STANDINGS_DIA_DEFECTO = 12
TEMPORADA_STANDINGS = "current"  # la clave que ya usa casi toda la caché real (`standings:PD:current`)
ESTADOS_SIN_EMPEZAR = ("scheduled", "NS")


def _tope_desde_entorno(nombre: str, defecto: int) -> int:
    try:
        return max(0, int(os.getenv(nombre, defecto)))
    except ValueError:
        return defecto


def _resolver_liga(partido: PartidoDia) -> tuple[str | None, str | None]:
    """(tabla, odds_key) de un partido: por `liga_codigo` numérico si está en la tabla curada
    (inequívoco), si no por nombre — misma resolución que el análisis (`resolver_liga_por_id`)."""
    codigo = (partido.liga_codigo or "").strip()
    league_id = int(codigo) if codigo.isdigit() else None
    _avg, tabla, odds_key = ligas.resolver_liga_por_id(league_id, partido.liga_nombre, 2.60)
    return tabla, odds_key


def partidos_a_refrescar(db: Session, ahora: datetime | None = None) -> list[PartidoDia]:
    ahora_chile = ahora or datetime.now(TZ_CHILE)
    fechas = [(ahora_chile + timedelta(days=d)).strftime("%Y-%m-%d") for d in (0, 1)]
    return (
        db.query(PartidoDia)
        .filter(PartidoDia.fecha.in_(fechas), PartidoDia.cache_invalidado == 0, PartidoDia.status.in_(ESTADOS_SIN_EMPEZAR))
        .all()
    )


def _ordenar_por_cantidad(conteo: dict[str, list[PartidoDia]]) -> list[tuple[str, list[PartidoDia]]]:
    return sorted(conteo.items(), key=lambda item: (-len(item[1]), item[0]))


def _agrupar(partidos: list[PartidoDia]) -> tuple[dict[str, list[PartidoDia]], dict[str, list[PartidoDia]]]:
    por_odds: dict[str, list[PartidoDia]] = {}
    por_tabla: dict[str, list[PartidoDia]] = {}
    for partido in partidos:
        tabla, odds_key = _resolver_liga(partido)
        if odds_key:
            por_odds.setdefault(odds_key, []).append(partido)
        if tabla:
            por_tabla.setdefault(tabla, []).append(partido)
    return por_odds, por_tabla


async def _refrescar_odds(db: Session, client: httpx.AsyncClient, por_odds: dict[str, list[PartidoDia]], tope: int) -> dict:
    resumen = {"ligas_candidatas": len(por_odds), "peticiones": 0, "fallidas": 0, "ya_frescas": 0, "omitidas_por_tope": 0}
    ya_gastadas = int(odds_fetch.consumo_odds_hoy(db).get("peticiones", 0))
    for odds_key, partidos in _ordenar_por_cantidad(por_odds):
        if leer_stats_cache(db, odds_fetch._clave_cache_odds_liga(odds_key)) is not None:
            resumen["ya_frescas"] += 1
            continue
        if ya_gastadas + resumen["peticiones"] + resumen["fallidas"] >= tope:
            resumen["omitidas_por_tope"] += 1
            continue
        kick_off = min((p.kick_off_utc for p in partidos if p.kick_off_utc), default=None)
        if await odds_fetch.refrescar_odds_liga(client, db, odds_key, kick_off):
            resumen["peticiones"] += 1
        else:
            resumen["fallidas"] += 1
    return resumen


async def _refrescar_standings(db: Session, client: httpx.AsyncClient, por_tabla: dict[str, list[PartidoDia]], tope: int) -> dict:
    resumen = {"tablas_candidatas": len(por_tabla), "refrescadas": 0, "fallidas": 0, "ya_frescas": 0, "omitidas_por_tope": 0}
    for codigo, _partidos in _ordenar_por_cantidad(por_tabla):
        if leer_stats_cache(db, f"standings:{codigo}:{TEMPORADA_STANDINGS}") is not None:
            resumen["ya_frescas"] += 1
            continue
        if resumen["refrescadas"] + resumen["fallidas"] >= tope:
            resumen["omitidas_por_tope"] += 1
            continue
        datos = await standings_fetch.obtener_standings(client, db, codigo, TEMPORADA_STANDINGS)
        resumen["refrescadas" if datos is not None else "fallidas"] += 1
    return resumen


async def ejecutar_refresco_cuotas(db: Session, client: httpx.AsyncClient, ahora: datetime | None = None) -> dict:
    """Refresca odds y standings de hoy/mañana dentro del presupuesto. Nunca lanza por un fallo de
    fuente: lo cuenta en `fallidas` (el job lo refleja en `scheduler_runs.ok`)."""
    tope_odds = _tope_desde_entorno("LAPLACE_REFRESCO_ODDS_MAX_DIA", MAX_PETICIONES_ODDS_DIA_DEFECTO)
    tope_standings = _tope_desde_entorno("LAPLACE_REFRESCO_STANDINGS_MAX_DIA", MAX_PETICIONES_STANDINGS_DIA_DEFECTO)
    partidos = partidos_a_refrescar(db, ahora)
    por_odds, por_tabla = _agrupar(partidos)
    odds = await _refrescar_odds(db, client, por_odds, tope_odds)
    standings = await _refrescar_standings(db, client, por_tabla, tope_standings)
    consumo = odds_fetch.consumo_odds_hoy(db)
    resumen = {
        "partidos": len(partidos), "tope_odds_dia": tope_odds, "odds": odds, "standings": standings,
        "consumo_odds_hoy": consumo,
        "ok": odds["fallidas"] == 0 and standings["fallidas"] == 0,
    }
    log.info("refresco_cuotas: %s", resumen)
    return resumen


def detalle_corto(resumen: dict) -> str:
    odds, standings = resumen["odds"], resumen["standings"]
    return (
        f"{resumen['partidos']} partidos; odds {odds['peticiones']} pet. gastadas "
        f"({resumen['consumo_odds_hoy'].get('creditos', 0)} créditos hoy, tope {resumen['tope_odds_dia']} pet./día, "
        f"{odds['ya_frescas']} frescas, {odds['omitidas_por_tope']} omitidas por tope, {odds['fallidas']} fallidas); "
        f"standings {standings['refrescadas']} refrescadas ({standings['ya_frescas']} frescas, {standings['fallidas']} fallidas)"
    )
