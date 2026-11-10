"""
db/cache.py — UNA sola implementación real de cache-aside sobre `stats_cache`.

Reemplaza `_leerSC`, duplicado (roto) en 5 nodos Code de n8n (WF-B x4, WF-D x1) — el bug real
encontrado en la exploración: el `await $helpers.httpRequest(...)` nunca se asignaba a una
variable, así que la lectura de caché NUNCA tenía HIT en ningún workflow, siempre pegaba a la
API externa real. Acá hay una sola función de lectura y una de escritura, testeadas.

TTL diferenciado por tipo — mismos valores que `_STATS_CACHE_TTL` en db_query.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.partidos import StatsCache

log = logging.getLogger("laplace.cache")

TTL_HORAS_POR_TIPO: dict[str, int] = {
    "team_stats": 48,
    "h2h": 168,  # 7 días
    "standings": 24,
    "predictions": 12,
    "odds": 2,
    # `bsd_event_id` — event_id de BSD resuelto por (local, visitante, fecha), cacheado por
    # gateway.py::_bsd_buscar_event_id (auditoría 2026-09-09: antes de esto, cada llamada a
    # enriquecer_bsd repetía la búsqueda completa). Mismo TTL que fixture_id_cache (24h) —
    # el mismo criterio: el mapeo nombre+fecha -> id externo de un partido no cambia dentro
    # del día.
    "bsd_event_id": 24,
}
TTL_DEFAULT_HORAS = 6

# TTL dinámico de `odds` cerca del kickoff (implementado 2026-09-09, ver
# `TTL_HORAS_ODDS_CERCA_KICKOFF`/`ttl_horas_odds_dinamico` abajo): un TTL fijo de 2h es
# razonable para un partido a días de distancia, pero deja las cuotas desactualizadas hasta 2h
# para un partido que arranca en breve, cuando las cuotas se mueven más rápido. `db/partidos_
# repo.py::leer_kick_off_utc` + `services/odds_fetch.py::obtener_odds_partido` threadean el
# kickoff real hasta acá vía el parámetro `ttl_horas_override` de `guardar_stats_cache`.
TTL_HORAS_ODDS_CERCA_KICKOFF = 0.5  # 30 min — cuando faltan <2h para el kickoff real
VENTANA_HORAS_KICKOFF_CERCANO = 2.0


def ttl_horas_odds_dinamico(kick_off_utc: str | None) -> float | None:
    """`None` = usar el TTL fijo normal de `odds` (2h, `TTL_HORAS_POR_TIPO`). Un valor real
    (0.5) cuando el kickoff real está a menos de `VENTANA_HORAS_KICKOFF_CERCANO` — las cuotas
    cambian más rápido cerca del inicio del partido. Nunca lanza: un `kick_off_utc` ausente o
    mal formado simplemente cae al TTL fijo (comportamiento sin cambios)."""
    if not kick_off_utc:
        return None
    try:
        kickoff = datetime.fromisoformat(kick_off_utc.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
    horas_restantes = (kickoff - utc_ahora()).total_seconds() / 3600
    if 0 <= horas_restantes < VENTANA_HORAS_KICKOFF_CERCANO:
        return TTL_HORAS_ODDS_CERCA_KICKOFF
    return None


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def leer_stats_cache(db: Session, cache_key: str) -> dict | None:
    """Devuelve los datos cacheados si existen y no expiraron; None si no hay HIT.

    A diferencia del `_leerSC` roto de n8n, esto sí funciona: se puede probar con un test
    real (ver backend/tests/test_cache.py).
    """
    row = db.get(StatsCache, cache_key)
    if row is None:
        return None
    if row.expira_en < _now_str():
        return None
    return json.loads(row.datos_json)


def guardar_stats_cache(
    db: Session, cache_key: str, tipo: str, datos: dict, ttl_horas_override: float | None = None
) -> None:
    """Cache-aside write — se llama SOLO después de un fetch real (todo caller ya pasó por
    `leer_stats_cache()` y obtuvo None, cache miss o expirado; nunca se llama en un HIT).

    Triangulación orgánica de datos (2026-09-09, `veces_confirmado`/`ultima_confirmacion_en`):
    NO son 3 llamadas HTTP disparadas acá — eso triplicaría el costo del primer fetch de un
    partido, justo lo contrario del objetivo. La confirmación se acumula entre requests REALES
    de usuarios distintos a lo largo del tiempo: cada vez que un fetch real devuelve el MISMO
    valor que ya estaba cacheado, el contador sube; si el valor cambió, se resetea a 1 y se
    loguea la discrepancia (dato real cambiando, o inconsistencia de la fuente — visible para
    auditoría, no bloqueante). Es 0 llamadas HTTP adicionales — la única llamada de red sigue
    siendo la que ya hacía el caller antes de esta función.

    `ttl_horas_override`: si viene (ej. `ttl_horas_odds_dinamico()` cerca del kickoff), gana
    sobre el TTL fijo de `TTL_HORAS_POR_TIPO` — pensado para `tipo="odds"`, pero cualquier
    caller lo puede usar."""
    ttl_horas = ttl_horas_override if ttl_horas_override is not None else TTL_HORAS_POR_TIPO.get(tipo, TTL_DEFAULT_HORAS)
    ahora = datetime.now()
    ahora_str = ahora.strftime("%Y-%m-%d %H:%M:%S")
    expira = (ahora + timedelta(hours=ttl_horas)).strftime("%Y-%m-%d %H:%M:%S")
    datos_json_nuevo = json.dumps(datos, ensure_ascii=False)

    row = db.get(StatsCache, cache_key)
    if row is None:
        row = StatsCache(
            cache_key=cache_key,
            tipo=tipo,
            datos_json=datos_json_nuevo,
            creado_en=ahora_str,
            expira_en=expira,
            veces_confirmado=1,
            ultima_confirmacion_en=ahora_str,
        )
        db.add(row)
    else:
        try:
            valor_confirma_lo_cacheado = json.loads(row.datos_json) == datos
        except (TypeError, ValueError):
            valor_confirma_lo_cacheado = False

        if valor_confirma_lo_cacheado:
            row.veces_confirmado = (row.veces_confirmado or 1) + 1
        else:
            if row.veces_confirmado and row.veces_confirmado > 1:
                log.info(
                    "stats_cache cache_key=%s tipo=%s: el valor cambió tras %d confirmaciones "
                    "previas — dato real actualizado o fuente inconsistente, contador reseteado",
                    cache_key, tipo, row.veces_confirmado,
                )
            row.veces_confirmado = 1
        row.ultima_confirmacion_en = ahora_str
        row.tipo = tipo
        row.datos_json = datos_json_nuevo
        row.expira_en = expira
    db.commit()


def es_alta_confianza(db: Session, cache_key: str, umbral: int = 3) -> bool:
    """True si el dato cacheado fue confirmado por >= `umbral` fetches reales independientes
    con el mismo valor — uso de auditoría/confianza del dato (no cambia el TTL, ya calibrado
    por tipo en `TTL_HORAS_POR_TIPO`)."""
    row = db.get(StatsCache, cache_key)
    return row is not None and (row.veces_confirmado or 0) >= umbral


def limpiar_stats_cache_expirado(db: Session) -> int:
    """Borra entradas expiradas. Devuelve cuántas filas se borraron."""
    ahora = _now_str()
    filas = db.query(StatsCache).filter(StatsCache.expira_en < ahora).all()
    n = len(filas)
    for fila in filas:
        db.delete(fila)
    db.commit()
    return n
