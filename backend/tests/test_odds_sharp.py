"""test_odds_sharp.py — odds de casas sharps (Pinnacle/SBOBet/Singbet) vía OddsPapi.
Usa httpx.MockTransport (mismo patrón que test_odds_fetch.py) — nunca llama a la API real."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import odds_sharp


@pytest.fixture(autouse=True)
def _reset_settings():
    original = settings.ODDSPAPI_SHARP_KEY
    yield
    settings.ODDSPAPI_SHARP_KEY = original


def test_coincide_nombres_exactos_y_por_alias():
    assert odds_sharp._coincide("Real Madrid", "Real Madrid") is True
    # substring: mismo nombre con sufijo distinto
    assert odds_sharp._coincide("Real Madrid", "Real Madrid CF") is True
    # match por primera palabra >=4 letras (mismo criterio que normalizacion.coincide_nombre)
    assert odds_sharp._coincide("Atletico Madrid", "Atletico de Madrid") is True
    assert odds_sharp._coincide("Boca Juniors", "River Plate") is False


def test_calcular_prob_impl_normaliza_a_1():
    p_l, p_e, p_v, overround = odds_sharp.calcular_prob_impl(1.90, 3.60, 4.20)
    assert abs((p_l + p_e + p_v) - 1.0) < 0.0001
    assert overround > 1.0


def test_calcular_divergencia_detecta_value_sobre_umbral():
    """VALUE_UMBRAL=5.0pp — divergencia Poisson vs mercado >= 5pp y coincide con pick_poisson
    -> value_signal True."""
    value_pick, value_pct, value_signal = odds_sharp._calcular_divergencia(
        prob_impl_l=0.40, prob_impl_e=0.30, prob_impl_v=0.30,
        prob_p_l=0.50, prob_p_e=0.25, prob_p_v=0.25,
        pick_poisson="Local",
    )
    assert value_pick == "Local"
    assert value_pct == 10.0
    assert value_signal is True


def test_calcular_divergencia_sin_pick_poisson_coincidente_no_dispara_signal():
    value_pick, value_pct, value_signal = odds_sharp._calcular_divergencia(
        prob_impl_l=0.40, prob_impl_e=0.30, prob_impl_v=0.30,
        prob_p_l=0.50, prob_p_e=0.25, prob_p_v=0.25,
        pick_poisson="Visitante",
    )
    assert value_pick == "Local"
    assert value_signal is False


def test_calcular_divergencia_sin_datos_poisson_devuelve_none():
    value_pick, value_pct, value_signal = odds_sharp._calcular_divergencia(
        prob_impl_l=0.40, prob_impl_e=0.30, prob_impl_v=0.30,
        prob_p_l=None, prob_p_e=None, prob_p_v=None,
        pick_poisson=None,
    )
    assert value_pick is None
    assert value_pct == 0.0
    assert value_signal is False


def test_obtener_odds_sharp_sin_key_configurada_no_llama_red():
    settings.ODDSPAPI_SHARP_KEY = ""

    async def _run():
        async with httpx.AsyncClient() as client:
            return await odds_sharp.obtener_odds_sharp(client, "Local FC", "Visit FC", "2026-06-01")

    resultado = asyncio.run(_run())
    assert resultado["ok"] is True
    assert resultado["found"] is False
    assert "ODDSPAPI_SHARP_KEY" in resultado["motivo"]


def test_obtener_odds_sharp_encuentra_partido_en_primer_sharp():
    settings.ODDSPAPI_SHARP_KEY = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["bookmaker_slug"] == "pinnacle"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "home_team": "Arsenal",
                        "away_team": "Chelsea",
                        "odds": {"home": 1.85, "draw": 3.60, "away": 4.10},
                    }
                ]
            },
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_sharp.obtener_odds_sharp(client, "Arsenal", "Chelsea", "2026-06-01")

    resultado = asyncio.run(_run())
    assert resultado["found"] is True
    assert resultado["bookmaker"] == "pinnacle"
    assert resultado["odds_local"] == 1.85


def test_obtener_odds_sharp_partido_no_encontrado_en_ningun_sharp():
    settings.ODDSPAPI_SHARP_KEY = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_sharp.obtener_odds_sharp(client, "Equipo X", "Equipo Y", "2026-06-01")

    resultado = asyncio.run(_run())
    assert resultado["found"] is False
    assert resultado["motivo"] == "Partido no encontrado en OddsPapi"


def test_obtener_odds_sharp_401_devuelve_motivo_api_key_invalida():
    settings.ODDSPAPI_SHARP_KEY = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await odds_sharp.obtener_odds_sharp(client, "Equipo X", "Equipo Y", "2026-06-01")

    resultado = asyncio.run(_run())
    assert resultado["found"] is False
    assert "401" in resultado["motivo"]
