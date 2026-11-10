"""test_odds_fetch.py — cascada de cuotas: hit en The Odds API, fallback a api-football,
y caso sin ninguna fuente disponible (devuelve odds_disponibles=False, no lanza)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import odds_fetch


@pytest.fixture(autouse=True)
def _reset_settings():
    original = (settings.THE_ODDS_API_KEY, settings.ODDSPAPI_KEY, settings.SPORTS_API_KEY, settings.BSD_API_KEY)
    yield
    settings.THE_ODDS_API_KEY, settings.ODDSPAPI_KEY, settings.SPORTS_API_KEY, settings.BSD_API_KEY = original


def test_coincide_equipos_via_alias():
    assert odds_fetch._coincide_equipos("Manchester City", "Man City") is True
    assert odds_fetch._coincide_equipos("River Plate", "CA River Plate") is True
    assert odds_fetch._coincide_equipos("Boca Juniors", "River Plate") is False


def test_the_odds_api_hit(db_session):
    settings.THE_ODDS_API_KEY = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "bookmakers": [
                        {
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Arsenal", "price": 1.8},
                                        {"name": "Draw", "price": 3.6},
                                        {"name": "Chelsea", "price": 4.2},
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ],
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_fetch.obtener_odds_partido(
                client, db_session, "Arsenal", "Chelsea", "soccer_epl", "fx1", "2026-06-01"
            )

    resultado = asyncio.run(_run())

    assert resultado["odds_disponibles"] is True
    assert resultado["odds_source"] == "the_odds_api"
    assert resultado["odds_local"] == 1.8


def test_cache_key_incluye_fecha_evita_colision_entre_partidos_sin_fixture_id(db_session):
    """Punto 2 de la auditoría 2026-09-09 (bug real): sin `fixture_id` (cobertura de ligas
    real es baja), la cache_key de fallback era `odds:{odds_key}:{local}` — sin la fecha, dos
    partidos del MISMO equipo local en fechas distintas dentro de la ventana de TTL de 2h
    colisionaban en la misma entrada de caché. Acá "Arsenal" juega dos partidos distintos
    (vs Chelsea el 2026-06-01, vs Liverpool el 2026-06-08) sin fixture_id en ninguno de los
    dos — deben resolver cada uno su propio fetch y no heredar las cuotas del otro."""
    settings.THE_ODDS_API_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            eventos = [{
                "home_team": "Arsenal", "away_team": "Chelsea",
                "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                    {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
                ]}]}],
            }]
        else:
            eventos = [{
                "home_team": "Arsenal", "away_team": "Liverpool",
                "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                    {"name": "Arsenal", "price": 2.1}, {"name": "Draw", "price": 3.4}, {"name": "Liverpool", "price": 3.3},
                ]}]}],
            }]
        return httpx.Response(200, json=eventos)

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            r1 = await odds_fetch.obtener_odds_partido(
                client, db_session, "Arsenal", "Chelsea", "soccer_epl", None, "2026-06-01"
            )
            r2 = await odds_fetch.obtener_odds_partido(
                client, db_session, "Arsenal", "Liverpool", "soccer_epl", None, "2026-06-08"
            )
            return r1, r2

    resultado_1, resultado_2 = asyncio.run(_run())

    assert llamadas["n"] == 2, (
        "cada fecha distinta debe hacer su propio fetch de red — con la colisión de caché "
        f"original hubiera sido 1 (el 2do partido reusaba la cache del 1ro), se hicieron {llamadas['n']}"
    )
    assert resultado_1["odds_disponibles"] is True
    assert resultado_1["odds_visit"] == 4.2  # Chelsea
    assert resultado_2["odds_disponibles"] is True
    assert resultado_2["odds_visit"] == 3.3  # Liverpool — distinto del partido anterior


def test_sin_ninguna_fuente_devuelve_no_disponible(db_session):
    settings.THE_ODDS_API_KEY = ""
    settings.ODDSPAPI_KEY = ""
    settings.SPORTS_API_KEY = ""
    settings.BSD_API_KEY = ""

    async def _run():
        async with httpx.AsyncClient() as client:
            return await odds_fetch.obtener_odds_partido(
                client, db_session, "Equipo A", "Equipo B", None, None, "2026-06-01"
            )

    resultado = asyncio.run(_run())

    assert resultado["odds_disponibles"] is False
    assert resultado["odds_source"] == "ninguna"


def _casa(titulo: str, h: float, d: float, a: float) -> dict:
    return {"title": titulo, "markets": [{"key": "h2h", "outcomes": [
        {"name": "Arsenal", "price": h}, {"name": "Draw", "price": d}, {"name": "Chelsea", "price": a},
    ]}]}


def test_consenso_usa_mediana_de_varias_casas_y_descarta_atipica(db_session):
    """La primera casa NO manda: con 5 casas, una atípica (1.2/9/15) se descarta y la mediana
    sale de las otras cuatro; la misma respuesta trae todas, así que es 1 sola petición."""
    settings.THE_ODDS_API_KEY = "fake-key"
    llamadas = {"n": 0}
    eventos = [{"home_team": "Arsenal", "away_team": "Chelsea", "bookmakers": [
        _casa("Rara", 1.2, 9.0, 15.0),
        _casa("A", 1.80, 3.60, 4.20), _casa("B", 1.85, 3.50, 4.10),
        _casa("C", 1.78, 3.65, 4.30), _casa("D", 1.82, 3.55, 4.15),
    ]}]

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(200, json=eventos, headers={"x-requests-remaining": "490"})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_fetch.obtener_odds_partido(
                client, db_session, "Arsenal", "Chelsea", "soccer_epl", "fx9", "2026-06-01"
            )

    r = asyncio.run(_run())
    assert llamadas["n"] == 1
    assert r["odds_n_casas"] == 4 and r["odds_n_casas_descartadas"] == 1
    assert "Rara" not in r["odds_casas"]
    assert r["odds_local"] == 1.81 and r["odds_empate"] == 3.575 and r["odds_visit"] == 4.175
    assert r["odds_consenso"] == "mediana"
    consumo = odds_fetch.consumo_odds_hoy(db_session)
    assert consumo["peticiones"] == 1 and consumo["creditos"] == 2 and consumo["restante_api"] == "490"


def test_consenso_una_sola_casa_conserva_contrato():
    r = odds_fetch.consenso_cuotas([{"casa": "X", "local": 2.0, "empate": 3.3, "visit": 3.8}])
    assert r["odds_local"] == 2.0 and r["odds_disponibles"] is True
    assert r["odds_source"] == "the_odds_api" and r["odds_n_casas"] == 1
    assert odds_fetch.consenso_cuotas([]) is None


def test_liga_cacheada_evita_peticion_por_partido(db_session):
    """Dos partidos de la misma liga en la misma respuesta: una sola petición de red."""
    settings.THE_ODDS_API_KEY = "fake-key"
    llamadas = {"n": 0}
    eventos = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "bookmakers": [_casa("A", 1.8, 3.6, 4.2)]},
        {"home_team": "Liverpool", "away_team": "Everton", "bookmakers": [{"title": "A", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Liverpool", "price": 1.5}, {"name": "Draw", "price": 4.0}, {"name": "Everton", "price": 6.0}]}]}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(200, json=eventos)

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            r1 = await odds_fetch.obtener_odds_partido(client, db_session, "Arsenal", "Chelsea", "soccer_epl", "f1", "2026-06-01")
            r2 = await odds_fetch.obtener_odds_partido(client, db_session, "Liverpool", "Everton", "soccer_epl", "f2", "2026-06-01")
            return r1, r2

    r1, r2 = asyncio.run(_run())
    assert llamadas["n"] == 1
    assert r1["odds_local"] == 1.8 and r2["odds_local"] == 1.5


def test_bsd_verifica_ambos_equipos_y_fecha(db_session):
    """Bug de la auditoría: se tomaba results[0] sin mirar al visitante. Acá el primero es otro
    partido del mismo local y debe ignorarse."""
    settings.BSD_API_KEY = "fake"
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request.url.path)
        if request.url.path.endswith("/events/"):
            return httpx.Response(200, json={"results": [
                {"id": 1, "home_team": {"name": "Arsenal"}, "away_team": "Liverpool", "event_date": "2026-06-01T15:00:00Z"},
                {"id": 2, "home_team": "Arsenal", "away_team": {"name": "Chelsea"}, "event_date": "2026-06-01T18:00:00Z"},
            ]})
        assert "/events/2/odds/" in request.url.path
        return httpx.Response(200, json={"odds": {"home_win": 1.9, "draw": 3.5, "away_win": 4.0}})

    async def _run(visitante: str):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_fetch._bsd_odds(client, "Arsenal", visitante, "2026-06-01")

    r = asyncio.run(_run("Chelsea"))
    assert r["odds_source"] == "bsd" and r["odds_local"] == 1.9
    assert asyncio.run(_run("Fulham")) is None


def test_bsd_descarta_evento_de_otra_fecha():
    ev = [{"id": 5, "home_team": "Arsenal", "away_team": "Chelsea", "event_date": "2026-07-01T15:00:00Z"}]
    assert odds_fetch._evento_bsd_del_partido(ev, "Arsenal", "Chelsea", "2026-06-01") is None
    assert odds_fetch._evento_bsd_del_partido(ev, "Arsenal", "Chelsea", "2026-07-01")["id"] == 5


def test_fallo_de_the_odds_api_no_filtra_la_api_key_en_el_log(db_session, caplog):
    """The Odds API recibe la clave como `?apiKey=` y el mensaje de HTTPStatusError trae la URL completa:
    el log de un fallo no debe imprimirla (revisión de seguridad 2026-10-07)."""
    import logging

    settings.THE_ODDS_API_KEY = "CLAVE-SECRETA-DE-PRUEBA-123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid key"})

    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_fetch._pedir_eventos_the_odds_api(client, db_session, "soccer_epl", None, ["clave-test"])

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(_go()) is None
    # El logger de httpx (INFO) imprime la URL completa; en producción `configurar_logging` lo sube a WARNING.
    volcado = "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in caplog.records if r.name == "laplace.odds_fetch")
    assert "CLAVE-SECRETA-DE-PRUEBA-123" not in volcado
    assert "401" in volcado


def test_no_gasta_creditos_si_el_partido_esta_fuera_de_la_ventana_de_la_peticion(db_session):
    """The Odds API cobra créditos por petición y la ventana pedida es de -12 h a +36 h: un partido de dentro de
    10 días no puede venir en la respuesta (auditoría 2026-10-09)."""
    from datetime import datetime, timedelta, timezone

    settings.THE_ODDS_API_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "the-odds-api" in request.url.host:
            llamadas["n"] += 1
        return httpx.Response(200, json=[])

    lejano = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    cercano = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await odds_fetch.obtener_odds_partido(client, db_session, "A", "B", "soccer_epl", None, "2026-12-01", lejano)
            antes = llamadas["n"]
            await odds_fetch.obtener_odds_partido(client, db_session, "C", "D", "soccer_epl", None, "2026-12-02", cercano)
            return antes, llamadas["n"]

    antes, despues = asyncio.run(_run())
    assert antes == 0 and despues == 1
