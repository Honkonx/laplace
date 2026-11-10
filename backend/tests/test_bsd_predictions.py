"""test_bsd_predictions.py — matching por tokens y mapeo de outcome->pick."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import bsd_predictions


@pytest.fixture(autouse=True)
def _reset_bsd_key():
    original = settings.BSD_API_KEY
    yield
    settings.BSD_API_KEY = original


def test_sin_api_key_devuelve_none():
    settings.BSD_API_KEY = ""

    async def _run():
        async with httpx.AsyncClient() as client:
            return await bsd_predictions.obtener_prediccion_externa_bsd(client, "River", "Boca", "2026-06-01")

    assert asyncio.run(_run()) is None


def test_match_por_tokens_y_mapeo_outcome():
    settings.BSD_API_KEY = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "event": {"home_team": {"name": "River Plate"}, "away_team": {"name": "Boca Juniors"}},
                        "outcome": "home",
                        "confidence": 0.72,
                    }
                ]
            },
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await bsd_predictions.obtener_prediccion_externa_bsd(client, "River Plate", "Boca Juniors", "2026-06-01")

    resultado = asyncio.run(_run())

    assert resultado["disponible"] is True
    assert resultado["pick"] == "Local"
    assert resultado["pick_nombre"] == "River Plate"
    assert resultado["confianza_pct"] == 72


def test_validar_bsd_sin_prediccion_en_el_payload():
    """`d` sin 'bsd_prediccion' -> False (mismo criterio que h2h/odds/tabla: si no hay datos
    ya resueltos, el módulo se saltea, sin hacer I/O acá)."""
    ok, motivo = bsd_predictions.validar_bsd({})
    assert ok is False
    assert "no disponible" in motivo.lower()


def test_validar_bsd_no_disponible():
    ok, motivo = bsd_predictions.validar_bsd({"bsd_prediccion": {"disponible": False}})
    assert ok is False


def test_validar_bsd_ok():
    ok, motivo = bsd_predictions.validar_bsd(
        {"bsd_prediccion": {"disponible": True, "pick": "Local", "confianza_pct": 72}}
    )
    assert ok is True
    assert motivo == "ok"


def test_analizar_bsd_devuelve_shape_esperado_para_consenso():
    d = {
        "partido_id": "1", "local": "River Plate", "visitante": "Boca Juniors", "liga": "Liga Profesional",
        "bsd_prediccion": {
            "disponible": True, "pick": "Local", "pick_nombre": "River Plate",
            "confianza_pct": 72, "fuente": "bsd_ml",
        },
    }
    resultado = bsd_predictions.analizar(d)

    assert resultado["ok"] is True
    assert resultado["fuente"] == "bsd_ml"
    assert resultado["pick"] == "Local"
    assert resultado["confianza_score"] == 72
    assert resultado["confianza"] == "ALTA"
    suma = resultado["prob_local"] + resultado["prob_empate"] + resultado["prob_visitante"]
    assert abs(suma - 1.0) < 0.001
    assert resultado["prob_local"] > resultado["prob_empate"]
    assert resultado["prob_local"] > resultado["prob_visitante"]


def test_obtener_prediccion_bsd_reintenta_tras_429_y_devuelve_datos():
    """Completa la ronda de reintento 429 (`_http_retry`) que ya tenían gateway/odds/standings/
    h2h/team_stats pero bsd_predictions había quedado afuera — auditoría 2026-09-09. Acá el
    reintento tiene éxito y `obtener_prediccion_externa_bsd` sí trae datos (no None)."""
    settings.BSD_API_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "event": {"home_team": {"name": "River Plate"}, "away_team": {"name": "Boca Juniors"}},
                        "outcome": "home",
                        "confidence": 0.72,
                    }
                ]
            },
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await bsd_predictions.obtener_prediccion_externa_bsd(client, "River Plate", "Boca Juniors", "2026-06-01")

    resultado = asyncio.run(_run())

    assert llamadas["n"] == 2, "debió reintentar una vez tras el 429 antes de rendirse"
    assert resultado is not None
    assert resultado["disponible"] is True
    assert resultado["pick"] == "Local"


def test_analizar_bsd_acota_confianza_extrema_a_10_90():
    """confianza_pct=100 (overconfidence del modelo externo) se acota a 90, no eclipsa el
    resto del consenso — mismo espíritu que el cap [10,95] de confianza_score de los demás
    módulos (decisión de diseño, bsd_ml nunca estuvo conectado antes)."""
    d = {"local": "A", "visitante": "B", "liga": "L", "partido_id": "1",
         "bsd_prediccion": {"disponible": True, "pick": "Visitante", "confianza_pct": 100}}
    resultado = bsd_predictions.analizar(d)
    assert resultado["confianza_score"] == 90
    assert resultado["prob_visitante"] == 0.9


def test_score_tokens_no_confunde_clubes_con_un_solo_token_en_comun():
    assert bsd_predictions._score_tokens("Manchester City", "Manchester United") == 0.0
    assert bsd_predictions._score_tokens("Real Sociedad", "Real Madrid") == 0.0


def test_score_tokens_exige_token_exacto_no_substring():
    assert bsd_predictions._score_tokens("Inter", "Internazionale") == 0.0
    assert bsd_predictions._score_tokens("River Plate", "River Plate") == 1.0
    assert bsd_predictions._score_tokens("Atletico Madrid", "Atletico") == 0.5  # un nombre de un solo token sí identifica
