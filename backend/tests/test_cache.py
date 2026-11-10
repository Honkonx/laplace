"""test_cache.py — verifica que db/cache.py SÍ tiene HIT real (el bug encontrado en n8n:
`_leerSC` nunca asignaba el resultado de httpRequest, entonces el caché de stats_cache nunca
pegaba en ningún workflow — acá se prueba explícitamente que la lectura funciona)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx

from backend.api.core.config import settings
from backend.api.db.cache import (
    TTL_HORAS_ODDS_CERCA_KICKOFF,
    es_alta_confianza,
    guardar_stats_cache,
    leer_stats_cache,
    ttl_horas_odds_dinamico,
)
from backend.api.models.partidos import StatsCache


def test_guardar_y_leer_cache_hit(db_session):
    guardar_stats_cache(db_session, "standings:39:2026", "standings", {"tabla": [1, 2, 3]})

    resultado = leer_stats_cache(db_session, "standings:39:2026")

    assert resultado is not None  # ESTO es lo que fallaba en n8n — siempre daba None
    assert resultado == {"tabla": [1, 2, 3]}


def test_cache_miss_si_no_existe(db_session):
    assert leer_stats_cache(db_session, "no-existe") is None


def test_cache_expirado_no_cuenta_como_hit(db_session):
    fila = StatsCache(
        cache_key="odds:vieja",
        tipo="odds",
        datos_json='{"x": 1}',
        creado_en=(datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
        expira_en=(datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),  # ya expiró
    )
    db_session.add(fila)
    db_session.commit()

    assert leer_stats_cache(db_session, "odds:vieja") is None


def test_ttl_diferenciado_por_tipo(db_session):
    from backend.api.db.cache import TTL_HORAS_POR_TIPO

    guardar_stats_cache(db_session, "h2h:key", "h2h", {"a": 1})
    guardar_stats_cache(db_session, "odds:key", "odds", {"b": 2})

    fila_h2h = db_session.get(StatsCache, "h2h:key")
    fila_odds = db_session.get(StatsCache, "odds:key")

    # h2h TTL 168h debe expirar mucho después que odds TTL 2h
    assert fila_h2h.expira_en > fila_odds.expira_en
    assert TTL_HORAS_POR_TIPO["h2h"] == 168
    assert TTL_HORAS_POR_TIPO["odds"] == 2


def test_ttl_bsd_event_id_es_24h_igual_que_fixture_id_cache():
    """Punto 4 de la auditoría 2026-09-09: `bsd_event_id` (cacheado por
    gateway.py::_bsd_buscar_event_id) usa el mismo TTL que fixture_id_cache (24h) — el
    mapeo nombre+fecha -> id externo de un partido no cambia dentro del día."""
    from backend.api.db.cache import TTL_HORAS_POR_TIPO

    assert TTL_HORAS_POR_TIPO["bsd_event_id"] == 24


# ─── Triangulación de datos (2026-09-09) ──────────────────────────────────────────────────
# Acumula evidencia entre requests REALES de usuarios distintos a lo largo del tiempo — NO
# son 3 llamadas HTTP disparadas en el primer fetch (eso triplicaría el costo de API del
# primer request de un partido, ver docstring de `guardar_stats_cache`).


def test_veces_confirmado_arranca_en_1_al_primer_guardado(db_session):
    guardar_stats_cache(db_session, "h2h:equipoA:equipoB", "h2h", {"goles": 3})

    fila = db_session.get(StatsCache, "h2h:equipoA:equipoB")
    assert fila.veces_confirmado == 1
    assert fila.ultima_confirmacion_en is not None
    assert es_alta_confianza(db_session, "h2h:equipoA:equipoB") is False


def test_veces_confirmado_sube_cuando_un_fetch_real_posterior_devuelve_el_mismo_valor(db_session):
    """Simula 3 fetches reales independientes (3 requests de usuarios distintos a lo largo
    del tiempo, cada uno con cache miss/expirado real) que devuelven el MISMO dato — el
    contador debe subir a 3 y quedar marcado de alta confianza."""
    cache_key = "team_stats:10:39:2026"
    guardar_stats_cache(db_session, cache_key, "team_stats", {"goles_favor": 1.8})
    guardar_stats_cache(db_session, cache_key, "team_stats", {"goles_favor": 1.8})
    guardar_stats_cache(db_session, cache_key, "team_stats", {"goles_favor": 1.8})

    fila = db_session.get(StatsCache, cache_key)
    assert fila.veces_confirmado == 3
    assert es_alta_confianza(db_session, cache_key, umbral=3) is True


def test_veces_confirmado_se_resetea_a_1_cuando_el_valor_cambia(db_session):
    """Si un fetch real posterior trae un valor DISTINTO (el dato cambió de verdad, o la
    fuente es inconsistente), el contador de confirmaciones se resetea — no debe acumular
    falsa confianza sobre un valor que ya no es el vigente."""
    cache_key = "standings:PD:2026"
    guardar_stats_cache(db_session, cache_key, "standings", {"posicion": 3})
    guardar_stats_cache(db_session, cache_key, "standings", {"posicion": 3})
    fila = db_session.get(StatsCache, cache_key)
    assert fila.veces_confirmado == 2

    guardar_stats_cache(db_session, cache_key, "standings", {"posicion": 4})
    fila = db_session.get(StatsCache, cache_key)
    assert fila.veces_confirmado == 1


def test_triangulacion_no_agrega_llamadas_http_al_primer_fetch_de_un_partido(db_session):
    """Confirma que la triangulación NO dispara llamadas HTTP adicionales — el primer fetch
    real de un dato de un partido debe seguir siendo UNA sola llamada de red, tal como antes
    de este cambio. `guardar_stats_cache` en sí nunca hace red (solo escribe en BD); esto
    prueba el flujo completo end-to-end vía un servicio de fetch real (team_stats_fetch)."""
    from backend.api.services import team_stats_fetch

    original_key = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(200, json={"response": {"goals": {"for": {"average": {"total": "1.80"}}}}})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await team_stats_fetch.enriquecer_stats_equipo(client, db_session, team_id=10, league_id=39, season=2026)

    try:
        resultado = asyncio.run(_run())
    finally:
        settings.SPORTS_API_KEY = original_key

    assert resultado is not None
    assert llamadas["n"] == 1, f"el primer fetch de un partido debe hacer 1 sola llamada HTTP, se hicieron {llamadas['n']}"

    fila = db_session.get(StatsCache, "team_stats:10:39:2026")
    assert fila.veces_confirmado == 1


# ─── TTL dinámico de odds cerca del kickoff (2026-09-09) ───────────────────────────────────


def test_ttl_odds_dinamico_sin_kickoff_usa_ttl_fijo():
    assert ttl_horas_odds_dinamico(None) is None
    assert ttl_horas_odds_dinamico("") is None


def test_ttl_odds_dinamico_kickoff_lejano_usa_ttl_fijo():
    lejano = (datetime.utcnow() + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ttl_horas_odds_dinamico(lejano) is None


def test_ttl_odds_dinamico_kickoff_cercano_usa_ttl_corto():
    cercano = (datetime.utcnow() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ttl_horas_odds_dinamico(cercano) == TTL_HORAS_ODDS_CERCA_KICKOFF


def test_ttl_odds_dinamico_kickoff_ya_pasado_usa_ttl_fijo():
    """Un partido que ya arrancó (kickoff en el pasado) no es "cercano" — usa el TTL fijo
    normal, no el corto (evita reintepretar un partido en curso como "por arrancar")."""
    pasado = (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ttl_horas_odds_dinamico(pasado) is None


def test_ttl_odds_dinamico_formato_invalido_no_revienta():
    assert ttl_horas_odds_dinamico("no-es-una-fecha") is None


def test_guardar_stats_cache_respeta_ttl_override(db_session):
    guardar_stats_cache(db_session, "odds:test123", "odds", {"x": 1}, ttl_horas_override=TTL_HORAS_ODDS_CERCA_KICKOFF)
    fila = db_session.get(StatsCache, "odds:test123")
    esperado = (datetime.now() + timedelta(hours=TTL_HORAS_ODDS_CERCA_KICKOFF)).strftime("%Y-%m-%d %H:%M")
    assert fila.expira_en.startswith(esperado[:15])
