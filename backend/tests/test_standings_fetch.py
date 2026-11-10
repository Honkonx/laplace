"""test_standings_fetch.py — matching de equipo en la tabla + defaults cuando no hay tabla."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.core.config import settings
from backend.api.services import standings_fetch


def test_extraer_posicion_y_forma_sin_tabla():
    pos, wins, texto = standings_fetch.extraer_posicion_y_forma(None, "Arsenal")
    assert pos == 10
    assert wins == 2
    assert "Sin datos" in texto


def test_extraer_posicion_y_forma_con_match():
    standings = {
        "standings": [
            {
                "table": [
                    {
                        "team": {"name": "Arsenal FC"},
                        "position": 2,
                        "points": 60,
                        "form": "WWDWL",
                        "playedGames": 28,
                        "won": 18,
                        "draw": 6,
                        "lost": 4,
                        "goalsFor": 55,
                        "goalsAgainst": 25,
                        "goalDifference": 30,
                    }
                ]
            }
        ]
    }

    pos, wins, texto = standings_fetch.extraer_posicion_y_forma(standings, "Arsenal")

    assert pos == 2
    assert wins == 3  # "WWDWL" -> 3 W
    assert "Pos 2" in texto


def test_obtener_standings_reintenta_tras_429_y_devuelve_datos(db_session):
    """Punto 1 de la auditoría 2026-09-09: un 429 real de football-data.org ya no se trata
    igual que cualquier otro fallo — se reintenta una vez (helper `_http_retry`) antes de
    devolver None. Acá el reintento tiene éxito y `obtener_standings` sí trae datos."""
    original = settings.FOOTBALL_DATA_KEY
    settings.FOOTBALL_DATA_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"standings": [{"table": []}]})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await standings_fetch.obtener_standings(client, db_session, "PD", "2026")

    try:
        resultado = asyncio.run(_run())
    finally:
        settings.FOOTBALL_DATA_KEY = original

    assert llamadas["n"] == 2, "debió reintentar una vez tras el 429 antes de rendirse"
    assert resultado == {"standings": [{"table": []}]}
