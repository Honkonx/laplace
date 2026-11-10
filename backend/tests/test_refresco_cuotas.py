"""Job de refresco de odds/standings de hoy y mañana con tope diario (auditoría 2026-10-06)."""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime

import httpx
import pytest

from backend.api import main
from backend.api.core.config import settings
from backend.api.db import cache
from backend.api.models.partidos import PartidoDia
from backend.api.services import odds_fetch, refresco_cuotas

AHORA = datetime(2026, 10, 6, 7, 15, tzinfo=refresco_cuotas.TZ_CHILE)


@pytest.fixture(autouse=True)
def _claves(monkeypatch):
    monkeypatch.setattr(settings, "THE_ODDS_API_KEY", "fake")
    monkeypatch.setattr(settings, "FOOTBALL_DATA_KEY", "fake")


def _partido(db, fecha, match_id, liga, local, visitante, status="scheduled", codigo=None):
    db.add(PartidoDia(
        fecha=fecha, match_id=match_id, liga_nombre=liga, liga_codigo=codigo, local=local, visitante=visitante,
        status=status, creado_en="2026-10-06 00:00:00", kick_off_utc="2099-01-01T20:00:00", cache_invalidado=0,
    ))


def _handler(contador):
    def handler(request: httpx.Request) -> httpx.Response:
        ruta = request.url.path
        if "/odds/" in ruta:
            contador["odds"].append(ruta)
            return httpx.Response(200, json=[], headers={"x-requests-remaining": "400"})
        contador["standings"].append(ruta)
        return httpx.Response(200, json={"standings": [{"table": []}]})
    return handler


def _correr(db):
    contador = {"odds": [], "standings": []}

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(contador))) as client:
            return await refresco_cuotas.ejecutar_refresco_cuotas(db, client, AHORA)

    return asyncio.run(_run()), contador


def test_una_peticion_por_liga_no_por_partido_y_solo_scheduled(db_session):
    for i, (local, visit) in enumerate([("Arsenal", "Chelsea"), ("Liverpool", "Everton"), ("Fulham", "Brentford")]):
        _partido(db_session, "2026-10-06", f"pl{i}", "Premier League", local, visit, codigo="39")
    _partido(db_session, "2026-10-07", "pd1", "LaLiga", "Real Madrid", "Sevilla", codigo="140")
    _partido(db_session, "2026-10-06", "pd2", "LaLiga", "Girona", "Betis", status="FT", codigo="140")  # ya terminó
    _partido(db_session, "2026-10-09", "x", "Premier League", "A", "B", codigo="39")  # fuera de hoy/mañana
    db_session.commit()

    resumen, contador = _correr(db_session)

    assert resumen["partidos"] == 4
    assert len(contador["odds"]) == 2  # PL y LaLiga: una petición por liga
    assert resumen["odds"]["peticiones"] == 2
    assert resumen["consumo_odds_hoy"]["peticiones"] == 2 and resumen["consumo_odds_hoy"]["creditos"] == 4
    assert len(contador["standings"]) == 2  # PL y PD
    assert resumen["ok"] is True


def test_tope_diario_respeta_consumo_previo_y_prioriza_liga_con_mas_partidos(db_session, monkeypatch):
    monkeypatch.setenv("LAPLACE_REFRESCO_ODDS_MAX_DIA", "1")
    for i in range(3):
        _partido(db_session, "2026-10-06", f"pl{i}", "Premier League", f"L{i}", f"V{i}", codigo="39")
    _partido(db_session, "2026-10-06", "pd", "LaLiga", "Real Madrid", "Sevilla", codigo="140")
    db_session.commit()

    resumen, contador = _correr(db_session)

    assert len(contador["odds"]) == 1 and "soccer_epl" in contador["odds"][0]  # la liga con más partidos
    assert resumen["odds"]["omitidas_por_tope"] == 1

    # segunda corrida el mismo día: el tope ya está agotado y la caché de liga sigue vigente
    resumen2, contador2 = _correr(db_session)
    assert contador2["odds"] == []
    assert resumen2["consumo_odds_hoy"]["peticiones"] == 1


def test_cache_vigente_no_se_vuelve_a_pedir(db_session):
    _partido(db_session, "2026-10-06", "pl", "Premier League", "Arsenal", "Chelsea", codigo="39")
    db_session.commit()
    cache.guardar_stats_cache(db_session, odds_fetch._clave_cache_odds_liga("soccer_epl"), "odds", [])
    cache.guardar_stats_cache(db_session, "standings:PL:current", "standings", {"standings": []})

    resumen, contador = _correr(db_session)

    assert contador == {"odds": [], "standings": []}
    assert resumen["odds"]["ya_frescas"] == 1 and resumen["standings"]["ya_frescas"] == 1


def test_fallo_de_fuente_se_cuenta_y_marca_no_ok(db_session):
    _partido(db_session, "2026-10-06", "pl", "Premier League", "Arsenal", "Chelsea", codigo="39")
    db_session.commit()

    async def _run():
        transporte = httpx.MockTransport(lambda r: httpx.Response(500))
        async with httpx.AsyncClient(transport=transporte) as client:
            return await refresco_cuotas.ejecutar_refresco_cuotas(db_session, client, AHORA)

    resumen = asyncio.run(_run())
    assert resumen["odds"]["fallidas"] == 1 and resumen["ok"] is False


def test_lifespan_registra_el_job_de_refresco_de_cuotas():
    fuente = inspect.getsource(main.lifespan)
    assert "_job_refresco_cuotas" in fuente and 'id="refresco_cuotas"' in fuente
