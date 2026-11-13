"""Regresión: un HTTP 200 de API-Football con `errors` dentro no se toma por «sin resultados» en la verificación de resultados."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.core.config import settings
from backend.api.services import resultados


def _correr(handler, ids):
    async def f():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await resultados._consultar_fixtures_apifootball(client, ids)  # noqa: SLF001
    return asyncio.run(f())


def test_un_200_con_errors_se_registra_y_no_devuelve_resultados(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "clave-de-prueba")
    cuerpo = {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."}, "response": []}
    with caplog.at_level("WARNING"):
        assert _correr(lambda _r: httpx.Response(200, json=cuerpo), ["1"]) == {}
    assert "Free plans do not have access" in caplog.text


def test_un_lote_con_error_no_impide_leer_el_siguiente(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "clave-de-prueba")
    llamadas = []
    ok = {"errors": [], "response": [{"fixture": {"id": 21, "status": {"short": "FT"}, "date": "2026-11-10T20:00:00+00:00"},
                                      "teams": {"home": {"name": "A"}, "away": {"name": "B"}}, "league": {"name": "L"}, "goals": {"home": 2, "away": 1}}]}

    def handler(request):
        llamadas.append(request.url.params.get("ids"))
        return httpx.Response(200, json={"errors": {"rateLimit": "x"}, "response": []} if len(llamadas) == 1 else ok)

    ids = [str(i) for i in range(1, 22)]  # 21 ids = dos lotes de 20 y 1
    resultado = _correr(handler, ids)
    assert len(llamadas) == 2 and list(resultado) == ["21"] and resultado["21"]["goles_local"] == 2
