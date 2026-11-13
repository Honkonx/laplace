"""test_top_picks_pipeline.py — pipeline diario de Top Picks (`services/top_picks.py`) con las fuentes
simuladas: fixtures de API-Football (incluida la respuesta HTTP 200 con `errors` dentro), scoring rápido,
análisis con el motor real, consolidación, y `generar_top_picks_dia` de punta a punta. Sin red, sin claves
reales y sin la base real (SQLite en memoria vía `db_session`); la IA se simula con AsyncMock."""
from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import ia_simple_laboratorio, top_picks
from backend.api.services.ai_client import AnalisisIAError

TS_20UTC = int(dt.datetime(2026, 11, 10, 20, 0, tzinfo=dt.timezone.utc).timestamp())  # 16:00 Chile
AHORA = dt.datetime(2026, 11, 10, 12, 0, tzinfo=top_picks.TZ_CHILE)
FECHA_API, FECHA_DB = "2026-11-10", "20261110"


@pytest.fixture(autouse=True)
def _reloj_del_laboratorio_antes_del_partido(monkeypatch):
    """Los partidos de estas pruebas son del 2026-11-10 a las 16:00 de Chile: con el reloj real (el mismo día, más tarde) el laboratorio rechazaría el corte por ser posterior al inicio."""
    from backend.api.services import laboratorio_pronosticos

    monkeypatch.setattr(laboratorio_pronosticos, "_now", lambda: "2026-11-10T12:00:00Z")


# ---------------------------------------------------------------------------------------------
# Constructores de datos
# ---------------------------------------------------------------------------------------------

def _fixture(fixture_id=1, league_id=39, ts=TS_20UTC, estado="NS", liga="La Liga", local="River", visita="Boca",
             team_local=10, team_visita=20) -> dict:
    return {
        "fixture": {"id": fixture_id, "timestamp": ts, "status": {"short": estado}},
        "league": {"id": league_id, "name": liga, "logo": "l.png", "season": 2026},
        "teams": {"home": {"id": team_local, "name": local, "logo": "h.png"},
                  "away": {"id": team_visita, "name": visita, "logo": "a.png"}},
        "goals": {"home": None, "away": None},
    }


def _candidato(fixture_id=1, score_liga=2, team_local=10, team_visita=20, **extra) -> dict:
    return {
        "fixture_id": fixture_id, "season": 2026, "local": "River", "visitante": "Boca",
        "team_id_local": team_local, "team_id_visitante": team_visita, "liga": "La Liga", "league_id": 39,
        "hora_chile": "16:00", "kick_off_utc": "2026-11-10T20:00:00Z", "fecha_db": FECHA_DB,
        "fecha_display": "10/11/2026", "score_liga": score_liga, **extra,
    }


def _prediccion_api(winner="River", forma_local="WWWWW", forma_visita="LLLLL") -> dict:
    def lado(forma, gf, ga):
        return {"league": {"form": forma, "goals": {"for": {"average": {"total": gf}},
                                                    "against": {"average": {"total": ga}}}}}
    return {"predictions": {"winner": {"name": winner}},
            "teams": {"home": lado(forma_local, "2.2", "0.6"), "away": lado(forma_visita, "0.7", "2.0")}}


def _odds_api(home="1.55", draw="4.00", away="6.00") -> list[dict]:
    return [{"bookmakers": [
        {"bets": [{"name": "Over/Under", "values": []}]},  # casa sin Match Winner: se salta
        {"bets": [{"name": "Match Winner", "values": [
            {"value": "Home", "odd": home}, {"value": "Draw", "odd": draw}, {"value": "Away", "odd": away}]}]},
    ]}]


def _h2h_api(n=6) -> list[dict]:
    return [{"goals": {"home": 3, "away": 0}, "teams": {"home": {"name": "River"}, "away": {"name": "Boca"}}}
            for _ in range(n)]


def _stats_equipo(gf, ga, forma) -> dict:
    return {"goals": {"for": {"average": {"total": gf}}, "against": {"average": {"total": ga}}}, "form": forma}


def _standings_api() -> list[dict]:
    return [{"league": {"standings": [[{"team": {"id": 10}, "rank": 1}, {"team": {"id": 20}, "rank": 18}]]}}]


def _api_falsa(fixtures: list[dict], *, predictions=True, odds=True, h2h=True, stats=True, standings=True):
    """Devuelve un reemplazo de `top_picks._apif_get` que responde por endpoint y registra las llamadas."""
    llamadas: list[str] = []

    async def falsa(_client, endpoint: str) -> dict:
        llamadas.append(endpoint)
        if endpoint.startswith("fixtures?date="):
            return {"response": fixtures}
        if endpoint.startswith("predictions"):
            return {"response": [_prediccion_api()] if predictions else []}
        if endpoint.startswith("odds"):
            return {"response": _odds_api() if odds else []}
        if endpoint.startswith("fixtures/headtohead"):
            return {"response": _h2h_api() if h2h else []}
        if endpoint.startswith("teams/statistics"):
            if not stats:
                return {"response": None}
            local = "team=10" in endpoint
            return {"response": _stats_equipo("2.3", "0.6", "WWWWD") if local else _stats_equipo("0.7", "2.1", "LLDLL")}
        if endpoint.startswith("standings"):
            return {"response": _standings_api() if standings else []}
        return {"response": []}

    falsa.llamadas = llamadas
    return falsa


def _cliente_http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------------------------
# _apif_get, _headers, _hora_chile
# ---------------------------------------------------------------------------------------------

def test_headers_lleva_la_clave_de_api_football(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "clave-de-prueba")
    assert top_picks._headers() == {"x-apisports-key": "clave-de-prueba"}


def test_hora_chile_resta_cuatro_horas_y_da_la_vuelta_a_medianoche():
    assert top_picks._hora_chile(TS_20UTC) == "16:00"
    ts_madrugada = int(dt.datetime(2026, 11, 10, 2, 30, tzinfo=dt.timezone.utc).timestamp())
    assert top_picks._hora_chile(ts_madrugada) == "22:30"  # (2 - 4) % 24


def test_apif_get_ok_devuelve_el_json(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "k")
    vistos = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vistos["url"], vistos["key"] = str(request.url), request.headers.get("x-apisports-key")
        return httpx.Response(200, json={"response": [{"a": 1}]})

    async def correr():
        async with _cliente_http(handler) as client:
            return await top_picks._apif_get(client, "fixtures?date=2026-11-10")

    assert asyncio.run(correr()) == {"response": [{"a": 1}]}
    assert vistos == {"url": f"{top_picks.APIF_BASE}/fixtures?date=2026-11-10", "key": "k"}


def test_apif_get_error_http_o_red_degrada_a_lista_vacia():
    def handler_500(_request):
        return httpx.Response(500, json={"error": "boom"})

    def handler_red(_request):
        raise httpx.ConnectError("sin red")

    async def correr(handler):
        async with _cliente_http(handler) as client:
            return await top_picks._apif_get(client, "x")

    assert asyncio.run(correr(handler_500)) == {"response": []}
    assert asyncio.run(correr(handler_red)) == {"response": []}


def test_apif_get_http_200_con_errors_se_registra_como_fallo_y_degrada_a_sin_partidos(caplog):
    cuerpo = {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
              "response": []}

    async def correr():
        async with _cliente_http(lambda _r: httpx.Response(200, json=cuerpo)) as client:
            return await top_picks._apif_get(client, "fixtures?date=2026-11-10")

    with caplog.at_level("WARNING", logger="laplace.top_picks"):
        resultado = asyncio.run(correr())
    assert resultado == {"response": []}                      # degrada igual que antes...
    assert "Free plans do not have access" in caplog.text     # ...pero el motivo ya no es invisible


# ---------------------------------------------------------------------------------------------
# _traer_y_guardar_fixtures_dia
# ---------------------------------------------------------------------------------------------

def test_traer_y_guardar_fixtures_persiste_todos_los_del_dia_y_traduce_estado(db_session, monkeypatch):
    fixtures = [
        _fixture(fixture_id=1, league_id=39),
        _fixture(fixture_id=2, league_id=99999, liga="Liga Rara", estado="FT"),  # fuera de LIGAS_OK: se guarda igual
    ]
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa(fixtures))

    devueltos = asyncio.run(top_picks._traer_y_guardar_fixtures_dia(db_session, None, FECHA_API))
    db_session.commit()

    assert devueltos == fixtures
    filas = {p.match_id: p for p in db_session.query(PartidoDia).all()}
    assert set(filas) == {"1", "2"}
    assert filas["1"].liga_slug == top_picks.LIGA_SLUG_POR_ID[39]
    assert filas["1"].hora_chile == "16:00"
    assert filas["1"].status == "scheduled"
    assert filas["2"].liga_slug == "liga_99999"
    assert filas["2"].status == "FT"


def test_traer_y_guardar_fixtures_respuesta_200_con_errors_no_guarda_nada(db_session, monkeypatch):
    """HTTP 200 con `errors` y `response: []` (plan sin acceso a la temporada): no hay fixtures, no se
    escribe nada en `partidos_dia` y el pipeline no revienta."""
    async def api(_client, _endpoint):
        return {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
                "results": 0, "response": []}

    monkeypatch.setattr(top_picks, "_apif_get", api)

    assert asyncio.run(top_picks._traer_y_guardar_fixtures_dia(db_session, None, FECHA_API)) == []
    assert db_session.query(PartidoDia).count() == 0


def test_traer_y_guardar_fixtures_con_errors_como_lista_vacia_http_real(db_session):
    """Misma situación pero por el camino HTTP real (httpx.MockTransport): 200 + `errors` + `response: []`."""
    cuerpo = {"errors": {"requests": "You have reached the request limit for the day."}, "response": []}

    async def correr():
        async with _cliente_http(lambda _r: httpx.Response(200, json=cuerpo)) as client:
            return await top_picks._traer_y_guardar_fixtures_dia(db_session, client, FECHA_API)

    assert asyncio.run(correr()) == []
    assert db_session.query(PartidoDia).count() == 0


def test_traer_y_guardar_fixtures_tolera_campos_ausentes(db_session, monkeypatch):
    minimo = {"fixture": {"id": 7}, "league": {}, "teams": {}}
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa([minimo]))

    asyncio.run(top_picks._traer_y_guardar_fixtures_dia(db_session, None, FECHA_API))
    db_session.commit()

    fila = db_session.query(PartidoDia).one()
    assert (fila.match_id, fila.local, fila.visitante, fila.hora_chile) == ("7", "Local", "Visitante", "")
    assert fila.liga_slug == "liga_None"


# ---------------------------------------------------------------------------------------------
# _filtrar_candidatos (casos no cubiertos en test_top_picks.py)
# ---------------------------------------------------------------------------------------------

def test_filtrar_candidatos_descarta_fixture_sin_timestamp():
    assert top_picks._filtrar_candidatos([_fixture(ts=None)], FECHA_DB, "10/11/2026") == []
    assert top_picks._filtrar_candidatos([_fixture(ts=0)], FECHA_DB, "10/11/2026") == []


@pytest.mark.parametrize("estado", ["1H", "HT", "FT", "PST", "CANC", "TBD"])
def test_filtrar_candidatos_solo_admite_estado_ns(estado):
    assert top_picks._filtrar_candidatos([_fixture(estado=estado)], FECHA_DB, "10/11/2026") == []


def test_filtrar_candidatos_hora_limite_siete_chile_incluida():
    # 11:00 UTC -> 07:00 Chile: entra; 10:59 UTC -> 06:59: no.
    entra = int(dt.datetime(2026, 11, 10, 11, 0, tzinfo=dt.timezone.utc).timestamp())
    no_entra = int(dt.datetime(2026, 11, 10, 10, 59, tzinfo=dt.timezone.utc).timestamp())
    assert len(top_picks._filtrar_candidatos([_fixture(ts=entra)], FECHA_DB, "x")) == 1
    assert top_picks._filtrar_candidatos([_fixture(ts=no_entra)], FECHA_DB, "x") == []


def test_filtrar_candidatos_arma_el_dict_completo():
    (c,) = top_picks._filtrar_candidatos([_fixture(fixture_id=55)], FECHA_DB, "10/11/2026")
    assert c == {
        "fixture_id": 55, "season": 2026, "local": "River", "visitante": "Boca", "team_id_local": 10,
        "team_id_visitante": 20, "liga": "La Liga", "league_id": 39, "hora_chile": "16:00",
        "kick_off_utc": "2026-11-10T20:00:00Z", "fecha_db": FECHA_DB, "fecha_display": "10/11/2026",
        "score_liga": 2,
    }


def test_filtrar_candidatos_ordena_premium_antes_que_standard_y_luego_por_hora_desc():
    tarde = int(dt.datetime(2026, 11, 10, 23, 0, tzinfo=dt.timezone.utc).timestamp())  # 19:00 Chile
    fixtures = [
        _fixture(fixture_id=1, league_id=88),           # standard, 16:00
        _fixture(fixture_id=2, league_id=39),           # premium, 16:00
        _fixture(fixture_id=3, league_id=39, ts=tarde),  # premium, 19:00
        _fixture(fixture_id=4, league_id=88, ts=tarde),  # standard, 19:00
    ]
    orden = [c["fixture_id"] for c in top_picks._filtrar_candidatos(fixtures, FECHA_DB, "x")]
    assert orden == [3, 2, 4, 1]
    assert {c["fixture_id"]: c["score_liga"] for c in top_picks._filtrar_candidatos(fixtures, FECHA_DB, "x")} == {
        1: 1, 2: 2, 3: 2, 4: 1}


def test_filtrar_candidatos_lista_vacia():
    assert top_picks._filtrar_candidatos([], FECHA_DB, "x") == []


# ---------------------------------------------------------------------------------------------
# _score_rapido
# ---------------------------------------------------------------------------------------------

def test_score_rapido_suma_predictions_odds_y_h2h(monkeypatch):
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa([]))
    (item,) = asyncio.run(top_picks._score_rapido(None, [_candidato(score_liga=2)]))
    # 2 (liga premium) + 3 (predictions) + 3 (mejor cuota 1,55 en 1,40-2,80) + 1 (h2h >= 3)
    assert item["score_datos"] == 9
    assert item["pick_externo"] == "River"
    assert item["tiene_predictions"] and item["tiene_odds"] and item["tiene_h2h_rapido"]
    assert (item["odd_home_cached"], item["odd_draw_cached"], item["odd_away_cached"]) == (1.55, 4.0, 6.0)
    assert item["prediccion_externa"]["predictions"]["winner"]["name"] == "River"


@pytest.mark.parametrize("local, visita, ajuste", [
    ("1.30", "5.00", 2),   # 1,25 <= mejor < 1,40
    ("1.10", "8.00", -1),  # mejor < 1,25: favorito demasiado corto
    ("3.20", "3.40", 2),   # mejor > 2,80: partido parejo, rama else
    ("1.40", "5.00", 3),   # borde inferior del rango 1,40-2,80
    ("2.80", "2.90", 3),   # borde superior
])
def test_score_rapido_rangos_de_cuota(monkeypatch, local, visita, ajuste):
    async def solo_odds(client, endpoint):
        if endpoint.startswith("odds"):
            return {"response": _odds_api(home=local, away=visita)}
        return {"response": []}

    monkeypatch.setattr(top_picks, "_apif_get", solo_odds)
    (item,) = asyncio.run(top_picks._score_rapido(None, [_candidato(score_liga=1)]))
    assert item["score_datos"] == 1 + ajuste


def test_score_rapido_sin_odds_ni_predictions_resta_uno_y_sin_ids_no_pide_h2h(monkeypatch):
    api = _api_falsa([], predictions=False, odds=False)
    monkeypatch.setattr(top_picks, "_apif_get", api)
    c = _candidato(score_liga=1, team_local=None, team_visita=None)
    (item,) = asyncio.run(top_picks._score_rapido(None, [c]))
    assert item["score_datos"] == 0
    assert item["pick_externo"] is None and item["prediccion_externa"] is None
    assert not any(e.startswith("fixtures/headtohead") for e in api.llamadas)


def test_score_rapido_h2h_con_menos_de_tres_no_cuenta(monkeypatch):
    async def api(_client, endpoint):
        return {"response": _h2h_api(2) if endpoint.startswith("fixtures/headtohead") else []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    (item,) = asyncio.run(top_picks._score_rapido(None, [_candidato(score_liga=2)]))
    assert item["tiene_h2h_rapido"] is False
    assert item["score_datos"] == 2 - 1  # sin odds ni predictions


def test_score_rapido_mercado_sin_match_winner_o_sin_local_no_cuenta_como_odds(monkeypatch):
    async def api(_client, endpoint):
        if endpoint.startswith("odds"):
            return {"response": [{"bookmakers": [{"bets": [{"name": "Match Winner", "values": [
                {"value": "Draw", "odd": "3.0"}]}]}]}]}
        return {"response": []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    (item,) = asyncio.run(top_picks._score_rapido(None, [_candidato()]))
    assert item["tiene_odds"] is False


def test_score_rapido_ordena_por_score_y_corta_en_cap(monkeypatch):
    # Los candidatos con id par tienen datos completos; los impares, nada.
    async def api(_client, endpoint):
        if "fixture=" in endpoint:
            par = int(endpoint.rsplit("=", 1)[1]) % 2 == 0
            if par and endpoint.startswith("predictions"):
                return {"response": [_prediccion_api()]}
            if par and endpoint.startswith("odds"):
                return {"response": _odds_api()}
        return {"response": []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    candidatos = [_candidato(fixture_id=i, team_local=None, team_visita=None) for i in range(1, 9)]
    resultado = asyncio.run(top_picks._score_rapido(None, candidatos))
    assert len(resultado) == top_picks.CAP_SCORING == 5
    assert [r["fixture_id"] for r in resultado[:4]] == [2, 4, 6, 8]  # los de mayor score primero
    assert resultado[0]["score_datos"] > resultado[-1]["score_datos"]


# ---------------------------------------------------------------------------------------------
# _contar_forma, _estadisticas_desde_prediccion
# ---------------------------------------------------------------------------------------------

def test_contar_forma():
    assert top_picks._contar_forma("") == 2
    assert top_picks._contar_forma(None) == 2
    assert top_picks._contar_forma("WWWWWWLL") == 3  # solo cuenta los últimos 5 ("WWWLL")
    assert top_picks._contar_forma("LLWWW") == 3


def test_estadisticas_desde_prediccion_recorta_forma_a_cinco():
    prediccion = _prediccion_api(forma_local="LLLWWWWW")
    gf, ga, wins, forma = top_picks._estadisticas_desde_prediccion(prediccion, "home")
    assert (gf, ga, wins, forma) == (2.2, 0.6, 5, "WWWWW")


@pytest.mark.parametrize("prediccion", [
    None,
    {},
    {"teams": {"home": {}}},
    {"teams": {"home": {"league": {"goals": {"for": {"average": {"total": None}},
                                              "against": {"average": {"total": "1.0"}}}}}}},
    {"teams": {"home": {"league": {"goals": {"for": {"average": {"total": "abc"}},
                                              "against": {"average": {"total": "1.0"}}}}}}},
    {"teams": {"home": {"league": {"goals": {"for": {"average": {"total": "-1"}},
                                              "against": {"average": {"total": "1.0"}}}}}}},
])
def test_estadisticas_desde_prediccion_incompleta_o_invalida_devuelve_none(prediccion):
    assert top_picks._estadisticas_desde_prediccion(prediccion, "home") is None


# ---------------------------------------------------------------------------------------------
# _analizar_candidato
# ---------------------------------------------------------------------------------------------

def _scored(**extra) -> dict:
    return _candidato(**{
        "prediccion_externa": _prediccion_api(), "pick_externo": "River",
        "odd_home_cached": 1.55, "odd_draw_cached": 4.0, "odd_away_cached": 6.0, **extra})


def test_analizar_candidato_con_todas_las_fuentes_usa_motor_real(db_session, monkeypatch):
    api = _api_falsa([])
    monkeypatch.setattr(top_picks, "_apif_get", api)

    r = asyncio.run(top_picks._analizar_candidato(db_session, None, _scored(), FECHA_API))

    d = r["datos_motor"]
    assert d["fuente_goles"] == "stats_equipo_real" and d["forma_datos_reales"] is True
    assert (d["goles_local_avg"], d["goles_contra_local_avg"]) == (2.3, 0.6)
    assert (d["goles_visit_avg"], d["goles_contra_visit_avg"]) == (0.7, 2.1)
    assert (d["forma_local_wins"], d["forma_visit_wins"]) == (4, 0)
    assert (d["pos_local"], d["pos_visit"]) == (1, 18)
    assert d["h2h_disponible"] and d["h2h_total"] == 6 and d["h2h_local_wins"] == 6
    assert d["odds_disponibles"] is True and d["odds_local"] == 1.55
    assert d["partido_id"] == "1" and d["fecha"] == FECHA_API
    assert r["stats_local_str"] == "Goles/P: 2.3 | Rec: 0.6 | Forma: WWWWD"
    assert r["h2h_resumen"].count("\n") == 4 and r["h2h_resumen"].startswith("River 3-0 Boca")
    assert r["calidad_datos"]["eligible"] is True
    assert set(r["calidad_datos"]["sources"]) >= {"estadisticas_equipo", "tabla", "h2h", "mercado"}
    assert r["resultado_motor"]["consenso"]["pick_final"] == "Local"
    assert r["prob_pick"] > 0.5
    assert r["score_calidad"] == r["resultado_motor"]["consenso"]["score_consenso"]
    assert r["estadistico"] is r["resultado_motor"]["modulos"]["poisson"]
    assert r["local"] == "River" and r["fixture_id"] == 1  # conserva los campos del candidato


def test_analizar_candidato_cachea_stats_y_h2h_entre_llamadas(db_session, monkeypatch):
    api = _api_falsa([])
    monkeypatch.setattr(top_picks, "_apif_get", api)
    asyncio.run(top_picks._analizar_candidato(db_session, None, _scored(), FECHA_API))
    antes = len([e for e in api.llamadas if e.startswith(("teams/statistics", "fixtures/headtohead"))])
    db_session.commit()
    asyncio.run(top_picks._analizar_candidato(db_session, None, _scored(), FECHA_API))
    despues = len([e for e in api.llamadas if e.startswith(("teams/statistics", "fixtures/headtohead"))])
    assert antes == 3  # stats local, stats visita, h2h
    assert despues == antes  # la segunda vuelta sale de `stats_cache`


def test_analizar_candidato_sin_stats_usa_fallback_de_predictions(db_session, monkeypatch):
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa([], stats=False, h2h=False, standings=False))

    r = asyncio.run(top_picks._analizar_candidato(db_session, None, _scored(), FECHA_API))

    d = r["datos_motor"]
    assert d["forma_datos_reales"] is True and d["fuente_goles"] == "stats_equipo_real"
    assert (d["goles_local_avg"], d["goles_contra_local_avg"], d["forma_local_wins"]) == (2.2, 0.6, 5)
    assert (d["goles_visit_avg"], d["goles_contra_visit_avg"], d["forma_visit_wins"]) == (0.7, 2.0, 0)
    assert r["stats_local_str"].endswith("(predictions)") and r["stats_visit_str"].endswith("(predictions)")
    assert d["h2h_disponible"] is False and r["h2h_resumen"] == "Sin historial directo."
    assert (d["pos_local"], d["pos_visit"]) == (10, 10)  # sin tabla: valores neutros


def test_analizar_candidato_sin_ninguna_fuente_cae_a_defaults_y_liga_generico(db_session, monkeypatch):
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa([], stats=False, h2h=False, standings=False))
    c = _scored(prediccion_externa=None, odd_home_cached=0.0, odd_draw_cached=0.0, odd_away_cached=0.0)

    r = asyncio.run(top_picks._analizar_candidato(db_session, None, c, FECHA_API))

    d = r["datos_motor"]
    assert d["fuente_goles"] == "liga_generico" and d["forma_datos_reales"] is False
    assert (d["goles_local_avg"], d["goles_visit_avg"]) == (1.3, 1.0)
    assert d["odds_disponibles"] is False and d["odds_local"] is None
    assert r["stats_local_str"] == "Sin datos"
    assert r["calidad_datos"]["eligible"] is False
    assert r["calidad_datos"]["source_count"] == 0


def test_analizar_candidato_sin_ids_de_equipo_no_pide_stats_ni_h2h(db_session, monkeypatch):
    api = _api_falsa([])
    monkeypatch.setattr(top_picks, "_apif_get", api)
    c = _scored(team_id_local=None, team_id_visitante=None)
    asyncio.run(top_picks._analizar_candidato(db_session, None, c, FECHA_API))
    assert not any(e.startswith(("teams/statistics", "fixtures/headtohead")) for e in api.llamadas)
    assert any(e.startswith("standings?league=39&season=2026") for e in api.llamadas)


def test_analizar_candidato_stats_con_gf_ausente_conserva_forma_pero_no_marca_reales(db_session, monkeypatch):
    async def api(_client, endpoint):
        if endpoint.startswith("teams/statistics"):
            return {"response": {"goals": {"for": {"average": {}}, "against": {"average": {}}}, "form": "WWWDL"}}
        return {"response": []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    r = asyncio.run(top_picks._analizar_candidato(
        db_session, None, _scored(prediccion_externa=None, odd_home_cached=0), FECHA_API))
    assert r["datos_motor"]["forma_local_wins"] == 3 and r["datos_motor"]["forma_datos_reales"] is False
    assert r["stats_local_str"] == "Goles/P: ? | Rec: ? | Forma: WWWDL"


def test_analizar_candidato_h2h_con_un_solo_partido_no_esta_disponible(db_session, monkeypatch):
    async def api(_client, endpoint):
        return {"response": _h2h_api(1) if endpoint.startswith("fixtures/headtohead") else []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    r = asyncio.run(top_picks._analizar_candidato(
        db_session, None, _scored(prediccion_externa=None, odd_home_cached=0), FECHA_API))
    assert r["h2h_disponible"] is False and r["datos_motor"]["h2h_total"] == 0


def test_analizar_candidato_h2h_de_dos_cuenta_empates_y_visitantes_pero_no_es_fuente_de_calidad(db_session, monkeypatch):
    partidos = [
        {"goals": {"home": 1, "away": 1}, "teams": {"home": {"name": "River"}, "away": {"name": "Boca"}}},
        {"goals": {"home": 0, "away": 2}, "teams": {"home": {"name": "River"}, "away": {"name": "Boca"}}},
    ]

    async def api(_client, endpoint):
        return {"response": partidos if endpoint.startswith("fixtures/headtohead") else []}

    monkeypatch.setattr(top_picks, "_apif_get", api)
    r = asyncio.run(top_picks._analizar_candidato(
        db_session, None, _scored(prediccion_externa=None, odd_home_cached=0), FECHA_API))
    d = r["datos_motor"]
    assert (d["h2h_empates"], d["h2h_visit_wins"], d["h2h_local_wins"], d["h2h_total"]) == (1, 1, 0, 2)
    assert "h2h" not in r["calidad_datos"]["sources"]  # exige >= 3 partidos


def test_analizar_candidato_season_ausente_usa_el_anio_actual(db_session, monkeypatch):
    api = _api_falsa([])
    monkeypatch.setattr(top_picks, "_apif_get", api)
    asyncio.run(top_picks._analizar_candidato(db_session, None, _scored(season=None), FECHA_API))
    assert any(f"season={dt.datetime.now().year}" in e for e in api.llamadas if e.startswith("standings"))


# ---------------------------------------------------------------------------------------------
# _probabilidad_del_pick, _clave_ranking, _consolidar_pick
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pick, esperado", [("Local", 0.6), ("Empate", 0.1), ("Visitante", 0.3)])
def test_probabilidad_del_pick_toma_la_del_resultado_elegido(pick, esperado):
    consenso = {"pick_final": pick, "prob_ponderada": {"local": 0.6, "empate": 0.1, "visitante": 0.3}}
    assert top_picks._probabilidad_del_pick(consenso) == esperado


@pytest.mark.parametrize("consenso", [
    {}, {"pick_final": "Sin datos"}, {"pick_final": "Local"},
    {"pick_final": "Local", "prob_ponderada": None}, {"pick_final": "Empate", "prob_ponderada": {"local": 0.5}},
])
def test_probabilidad_del_pick_sin_estimacion_es_cero(consenso):
    assert top_picks._probabilidad_del_pick(consenso) == 0.0


def test_clave_ranking_ordena_por_probabilidad_y_desempata_por_score():
    a = {"prob_pick": 0.70, "score_calidad": 40}
    b = {"prob_pick": 0.70, "score_calidad": 55}
    c = {"prob_pick": 0.55, "score_calidad": 99}  # mucho acuerdo pero probabilidad baja: no gana
    assert top_picks._clave_ranking(a) == (0.70, 40)
    assert sorted([a, c, b], key=top_picks._clave_ranking, reverse=True) == [b, a, c]


def test_consolidar_pick_sin_pick_ia_sintetiza_sin_datos():
    resultado = {"local": "River", "visitante": "Boca", "consenso": {
        "pick_final": "Local", "score_consenso": 70, "confianza_final": "ALTA"}}
    combinado = top_picks._consolidar_pick(resultado, {"pick": None})
    assert combinado["pick_unificado"] == "River" and combinado["nivel_ia"] == "SOLO_ESTADISTICO"
    assert combinado["texto_claude"] == "PICK: Sin datos"
    assert combinado["confianza_final"] == "ALTA"


def test_consolidar_pick_confianza_baja_del_consenso_limita_el_score():
    resultado = {"local": "River", "visitante": "Boca", "consenso": {
        "pick_final": "Local", "score_consenso": 90, "confianza_final": "BAJA"}}
    combinado = top_picks._consolidar_pick(resultado, {"pick": "River"})
    assert combinado["nivel_ia"] == "COINCIDEN"
    assert combinado["score_consolidado"] <= 44 and combinado["confianza_final"] == "BAJA"


# ---------------------------------------------------------------------------------------------
# generar_top_picks_dia de punta a punta
# ---------------------------------------------------------------------------------------------

TEXTO_IA = """PICK: River
RAZÓN: Mejor forma y ventaja de local
CONFIANZA: 80
---
PICK: River
RAZÓN: Dominio del historial directo
CONFIANZA: 75
---
PICK: Boca
RAZÓN: Sin datos relevantes
CONFIANZA: 60"""


@pytest.fixture()
def ia_canal(monkeypatch):
    """IA del canal simulada; la IA simple del laboratorio apagada salvo que el test la active."""
    mock = AsyncMock(return_value=TEXTO_IA)
    monkeypatch.setattr(top_picks, "generar_texto_ia", mock)
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_ACTIVA", False)
    return mock


def _tres_fixtures() -> list[dict]:
    return [_fixture(fixture_id=i, team_local=10 + i, team_visita=20 + i, local=f"Local{i}", visita=f"Visita{i}")
            for i in (1, 2, 3)]


def _api_con_ids_por_partido(fixtures):
    """Variante de `_api_falsa` donde cada partido tiene sus propios ids de equipo (las respuestas de
    stats/standings deben corresponder a los ids de cada fixture)."""
    base = _api_falsa(fixtures)

    async def api(client, endpoint):
        if endpoint.startswith("teams/statistics"):
            es_local = int(endpoint.split("team=")[1]) < 20
            return {"response": _stats_equipo("2.3", "0.6", "WWWWD") if es_local else _stats_equipo("0.7", "2.1", "LLDLL")}
        if endpoint.startswith("standings"):
            return {"response": [{"league": {"standings": [[
                {"team": {"id": 11}, "rank": 1}, {"team": {"id": 12}, "rank": 1}, {"team": {"id": 13}, "rank": 1},
                {"team": {"id": 21}, "rank": 18}, {"team": {"id": 22}, "rank": 18}, {"team": {"id": 23}, "rank": 18},
            ]]}}]}
        return await base(client, endpoint)

    api.llamadas = base.llamadas
    return api


def test_generar_top_picks_dia_sin_fixtures_devuelve_sin_candidatos(db_session, monkeypatch, ia_canal):
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa([]))
    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))
    assert resultado == {"fecha_display": "10/11/2026", "sin_candidatos": True}
    ia_canal.assert_not_awaited()


def test_generar_top_picks_dia_solo_ligas_no_curadas_o_ya_jugados_es_sin_candidatos(db_session, monkeypatch, ia_canal):
    fixtures = [_fixture(fixture_id=1, league_id=99999), _fixture(fixture_id=2, estado="FT")]
    api = _api_falsa(fixtures)
    monkeypatch.setattr(top_picks, "_apif_get", api)
    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))
    db_session.commit()
    assert resultado["sin_candidatos"] is True
    assert db_session.query(PartidoDia).count() == 2  # igual quedaron guardados para la acción `juegos`
    assert not any(e.startswith("predictions") for e in api.llamadas)  # no se gastó la cascada cara


def test_generar_top_picks_dia_con_errors_http_200_equivale_a_sin_candidatos(db_session, ia_canal):
    cuerpo = {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
              "response": []}

    async def correr():
        async with _cliente_http(lambda _r: httpx.Response(200, json=cuerpo)) as client:
            return await top_picks.generar_top_picks_dia(db_session, client, AHORA)

    assert asyncio.run(correr())["sin_candidatos"] is True


def test_generar_top_picks_dia_de_punta_a_punta_publica_picks_validos(db_session, monkeypatch, ia_canal):
    fixtures = _tres_fixtures()
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(fixtures))

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado["sin_candidatos"] is False and resultado["sin_picks_validos"] is False
    assert (resultado["fecha_display"], resultado["fecha_db"]) == ("10/11/2026", FECHA_DB)
    picks = resultado["picks"]
    assert 1 <= len(picks) <= 3
    for p in picks:
        assert p["pick_final"] == p["local"]  # cuotas, stats, h2h y tabla favorecen al local
        assert p["confianza_final"] in ("ALTA", "MEDIA")
        assert p["modulos_consenso"] and p["prob_consenso"]
        assert p["odds_texto"].startswith(f"{p['local']} @1.55")
        assert p["pick_externo"] == "River"
    assert resultado["score_min"] == min(p["score_consolidado"] for p in picks)
    assert resultado["baja_confianza"] == (resultado["score_min"] < top_picks.UMBRAL_BAJA_CONFIANZA)
    ia_canal.assert_awaited_once()
    assert ia_canal.await_args.kwargs["rol"] == "canal"
    # Las variantes del motor quedaron congeladas en el laboratorio (sombra), antes de la IA.
    assert db_session.query(PronosticoExperimental).count() > 0
    assert db_session.query(PronosticoExperimental).filter_by(variante="api_football_prediction").count() == 3


def test_generar_top_picks_dia_sobrantes_son_los_analizados_despues_del_tercero(db_session, monkeypatch, ia_canal):
    fixtures = [_fixture(fixture_id=i, team_local=10 + i, team_visita=20 + i) for i in range(1, 8)]
    api = _api_falsa(fixtures)
    monkeypatch.setattr(top_picks, "_apif_get", api)

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    # Se analiza CAP_ANALIZADOS = 5; quedan 2 (índices 3 y 4) como sobrantes.
    assert len(resultado["sobrantes"]) == 2
    assert all(set(s) == {"fixture_id", "local", "visitante", "liga", "hora_chile"} for s in resultado["sobrantes"])
    assert all(isinstance(s["fixture_id"], str) for s in resultado["sobrantes"])


def test_generar_top_picks_dia_sin_datos_suficientes_devuelve_sin_picks_validos_y_no_llama_a_la_ia(
        db_session, monkeypatch, ia_canal):
    fixtures = [_fixture(fixture_id=1)]
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa(
        fixtures, predictions=False, odds=False, h2h=False, stats=False, standings=False))

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado == {
        "fecha_display": "10/11/2026", "fecha_db": FECHA_DB, "sin_candidatos": False, "sin_picks_validos": True,
        "picks": [], "baja_confianza": False, "score_min": None, "sobrantes": [],
    }
    ia_canal.assert_not_awaited()


def test_generar_top_picks_dia_ia_caida_degrada_a_solo_estadistico(db_session, monkeypatch):
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_ACTIVA", False)
    monkeypatch.setattr(top_picks, "generar_texto_ia", AsyncMock(side_effect=AnalisisIAError("todos fallaron")))
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado["picks"], "con IA caída el consenso estadístico igual publica"
    for p in resultado["picks"]:
        assert p["nivel_ia"] == "SOLO_ESTADISTICO"
        assert p["razon_ia"] == "IA no disponible"
        assert p["score_ia"] == 0
        assert p["pick_final"] == p["local"]


def test_generar_top_picks_dia_ia_responde_menos_bloques_que_picks(db_session, monkeypatch):
    """Si la IA devuelve un solo bloque para tres picks, los restantes se consolidan como sin IA."""
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_ACTIVA", False)
    monkeypatch.setattr(top_picks, "generar_texto_ia", AsyncMock(return_value="PICK: Local1\nRAZÓN: x\nCONFIANZA: 70"))
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    niveles = [p["nivel_ia"] for p in resultado["picks"]]
    assert len(niveles) >= 2
    assert niveles.count("SOLO_ESTADISTICO") >= len(niveles) - 1
    assert resultado["picks"][-1]["razon_ia"] == ""


def _forzar_consolidado(monkeypatch, confianza: str, score: int):
    def falso(resultado_motor, ia):
        pick = resultado_motor["consenso"]["pick_final"]
        return {"pick_claude": "x", "pick_estadistico": pick, "pick_unificado": resultado_motor["local"],
                "nivel_ia": "COINCIDEN", "score_consolidado": score, "confianza_final": confianza,
                "texto_claude": ""}
    monkeypatch.setattr(top_picks, "_consolidar_pick", falso)


def test_generar_top_picks_dia_confianza_baja_exige_confirmacion_del_admin(db_session, monkeypatch, ia_canal):
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))
    _forzar_consolidado(monkeypatch, "MEDIA", 50)  # publicable pero por debajo de UMBRAL_BAJA_CONFIANZA (65)

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado["picks"] and resultado["score_min"] == 50
    assert resultado["baja_confianza"] is True


def test_generar_top_picks_dia_confianza_alta_no_pide_confirmacion(db_session, monkeypatch, ia_canal):
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))
    _forzar_consolidado(monkeypatch, "ALTA", 80)

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado["baja_confianza"] is False and resultado["score_min"] == 80


def test_generar_top_picks_dia_descarta_picks_en_baja_tras_consolidar(db_session, monkeypatch, ia_canal):
    cinco = [_fixture(fixture_id=i, team_local=10 + i, team_visita=20 + i) for i in range(1, 6)]
    monkeypatch.setattr(top_picks, "_apif_get", _api_falsa(cinco))
    _forzar_consolidado(monkeypatch, "BAJA", 30)

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert resultado["sin_picks_validos"] is True and resultado["picks"] == []
    assert resultado["score_min"] is None and resultado["baja_confianza"] is False
    assert resultado["sobrantes"]  # los analizados fuera del top 3 siguen reportándose


def test_generar_top_picks_dia_con_ia_simple_activa_registra_la_hipotesis_en_el_laboratorio(
        db_session, monkeypatch, ia_canal):
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_ACTIVA", True)
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_MAX_PARTIDOS", 2)
    hipotesis = {"pick": "local", "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2,
                 "marcador_probable": "1-0"}
    simple = AsyncMock(return_value=(hipotesis, "{crudo}", "groq", "modelo-x"))
    monkeypatch.setattr(ia_simple_laboratorio, "generar_hipotesis", simple)
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))

    asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert simple.await_count == 2  # tope LAB_IA_SIMPLE_MAX_PARTIDOS
    filas = db_session.query(PronosticoExperimental).filter_by(variante="ia_simple").all()
    assert len(filas) == 2 and all(f.fuente == "ia:groq" and f.modelo_version == "modelo-x" for f in filas)


def test_generar_top_picks_dia_ia_simple_que_falla_no_impide_publicar(db_session, monkeypatch, ia_canal):
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_ACTIVA", True)
    monkeypatch.setattr(settings, "LAB_IA_SIMPLE_MAX_PARTIDOS", 5)
    efectos = [AnalisisIAError("sin cuota"), ValueError("la IA no devolvió JSON"), AnalisisIAError("otra vez")]
    simple = AsyncMock(side_effect=efectos)
    monkeypatch.setattr(ia_simple_laboratorio, "generar_hipotesis", simple)
    monkeypatch.setattr(top_picks, "_apif_get", _api_con_ids_por_partido(_tres_fixtures()))

    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None, AHORA))

    assert simple.await_count == 3
    assert resultado["picks"]  # la IA simple es un comparador de sombra, no condición para publicar
    assert db_session.query(PronosticoExperimental).filter_by(variante="ia_simple").count() == 0


def test_generar_top_picks_dia_usa_ahora_de_chile_por_defecto(db_session, monkeypatch, ia_canal):
    api = _api_falsa([])
    monkeypatch.setattr(top_picks, "_apif_get", api)
    resultado = asyncio.run(top_picks.generar_top_picks_dia(db_session, None))
    hoy = dt.datetime.now(top_picks.TZ_CHILE)
    assert resultado["fecha_display"] == hoy.strftime("%d/%m/%Y")
    assert api.llamadas[0] == f"fixtures?date={hoy.strftime('%Y-%m-%d')}"
