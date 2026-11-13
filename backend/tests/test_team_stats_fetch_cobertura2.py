"""Cobertura de `team_stats_fetch`: respuestas válidas, `errors` dentro de un HTTP 200, cuota agotada y red caída."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.db.cache import leer_stats_cache
from backend.api.services import team_stats_fetch as tsf

STATS = {"goals": {"for": {"average": {"total": "1.8"}}, "against": {"average": {"total": "0.9"}}}}


def _cliente(handler, llamadas: list):
    def envoltura(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(envoltura))


def _correr(db, handler, team=1, league=2, season=2024):
    llamadas: list = []

    async def _go():
        async with _cliente(handler, llamadas) as client:
            return await tsf.enriquecer_stats_equipo(client, db, team, league, season)

    return asyncio.run(_go()), llamadas


@pytest.fixture(autouse=True)
def _con_clave(monkeypatch):
    monkeypatch.setattr(tsf.settings, "SPORTS_API_KEY", "clave-de-prueba")


def test_respuesta_valida_devuelve_datos_y_los_cachea(db_session):
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(200, json={"errors": [], "response": STATS}))
    assert datos == STATS
    assert len(llamadas) == 1
    assert llamadas[0].url.params["team"] == "1"
    assert llamadas[0].url.params["league"] == "2"
    assert llamadas[0].url.params["season"] == "2024"
    assert llamadas[0].headers["x-apisports-key"] == "clave-de-prueba"
    assert leer_stats_cache(db_session, "team_stats:1:2:2024") == STATS


def test_segunda_llamada_sale_del_cache_sin_red(db_session):
    _correr(db_session, lambda r: httpx.Response(200, json={"errors": [], "response": STATS}))
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(500))
    assert datos == STATS
    assert llamadas == []


@pytest.mark.parametrize("args", [(0, 2, 2024), (1, 0, 2024), (1, 2, 0)])
def test_faltan_ids_devuelve_none_sin_red(db_session, args):
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(200, json={}), *args)
    assert datos is None
    assert llamadas == []


def test_sin_api_key_devuelve_none_sin_red(db_session, monkeypatch):
    monkeypatch.setattr(tsf.settings, "SPORTS_API_KEY", "")
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(200, json={}))
    assert datos is None
    assert llamadas == []


def test_errors_en_http_200_no_se_lee_como_sin_resultados_ni_se_cachea(db_session):
    cuerpo = {"errors": {"requests": "You have reached the request limit for the day"}, "response": []}
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(200, json=cuerpo))
    assert datos is None
    assert len(llamadas) == 1
    assert leer_stats_cache(db_session, "team_stats:1:2:2024") is None
    assert 2024 not in tsf._temporadas_sin_acceso  # cuota diaria: no marca la temporada como inaccesible


def test_plan_sin_acceso_a_la_temporada_la_recuerda_y_no_repite_la_peticion(db_session):
    cuerpo = {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."}, "response": []}
    datos, llamadas = _correr(db_session, lambda r: httpx.Response(200, json=cuerpo), season=2026)
    assert datos is None
    assert len(llamadas) == 1
    assert 2026 in tsf._temporadas_sin_acceso

    datos2, llamadas2 = _correr(db_session, lambda r: httpx.Response(200, json={"response": STATS}), team=9, season=2026)
    assert datos2 is None
    assert llamadas2 == []


def test_red_caida_devuelve_none(db_session):
    def cae(request):
        raise httpx.ConnectError("sin red", request=request)

    datos, llamadas = _correr(db_session, cae)
    assert datos is None
    assert len(llamadas) == 1
    assert leer_stats_cache(db_session, "team_stats:1:2:2024") is None


def test_http_500_devuelve_none(db_session):
    datos, _ = _correr(db_session, lambda r: httpx.Response(500, json={}))
    assert datos is None


def test_timeout_devuelve_none(db_session):
    def lento(request):
        raise httpx.ReadTimeout("timeout", request=request)

    datos, _ = _correr(db_session, lento)
    assert datos is None


@pytest.mark.parametrize("vacio", [[], {}, None])
def test_response_vacio_devuelve_none_y_no_cachea(db_session, vacio):
    datos, _ = _correr(db_session, lambda r: httpx.Response(200, json={"errors": [], "response": vacio}))
    assert datos is None
    assert leer_stats_cache(db_session, "team_stats:1:2:2024") is None


def test_cuerpo_no_json_devuelve_none(db_session):
    datos, _ = _correr(db_session, lambda r: httpx.Response(200, content=b"<html>no es json</html>"))
    assert datos is None


def test_extraer_goles_promedio_valores_y_casos_borde():
    assert tsf.extraer_goles_promedio(STATS) == (1.8, 0.9)
    assert tsf.extraer_goles_promedio({}) == (None, None)
    assert tsf.extraer_goles_promedio({"goals": None}) == (None, None)
    assert tsf.extraer_goles_promedio({"goals": {"for": {"average": {"total": "2.0"}}}}) == (2.0, None)
    assert tsf.extraer_goles_promedio({"goals": {"against": {"average": {"total": 1}}}}) == (None, 1.0)


def test_extraer_goles_promedio_valor_no_numerico():
    stats = {"goals": {"for": {"average": {"total": "abc"}}, "against": {"average": {"total": "1.0"}}}}
    assert tsf.extraer_goles_promedio(stats) == (None, None)


def test_extraer_goles_promedio_tolera_average_nulo():
    """api-football puede mandar `average: null`; antes fallaba con AttributeError."""
    from backend.api.services.team_stats_fetch import extraer_goles_promedio

    assert extraer_goles_promedio({"goals": {"for": {"average": None}, "against": {"average": None}}}) == (None, None)
    assert extraer_goles_promedio({"goals": {"for": {"average": {"total": "1.5"}}, "against": {"average": None}}}) == (1.5, None)
