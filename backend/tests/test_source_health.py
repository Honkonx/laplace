"""Contrato del monitor de fuentes: persiste datos seguros y cuida cuotas mensuales."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.models.metricas import EstadoFuenteDeportiva
from backend.api.services import source_health


def test_monitor_diario_no_consulta_the_odds_api(db_session, monkeypatch):
    llamadas: list[str] = []

    async def respuesta(request: httpx.Request) -> httpx.Response:
        llamadas.append(str(request.url))
        return httpx.Response(200, headers={"x-requests-remaining": "99"}, json={"response": []})

    monkeypatch.setattr(source_health.settings, "LIVESCORE6_KEY", "test")
    monkeypatch.setattr(source_health.settings, "SPORTS_API_KEY", "test")
    monkeypatch.setattr(source_health.settings, "FOOTBALL_DATA_KEY", "test")
    monkeypatch.setattr(source_health.settings, "BSD_API_KEY", "test")
    monkeypatch.setattr(source_health.settings, "THE_ODDS_API_KEY", "test")
    monkeypatch.setattr(source_health.settings, "ODDSPAPI_SHARP_KEY", "")

    transport = httpx.MockTransport(respuesta)
    async def ejecutar() -> list[dict]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await source_health.verificar_fuentes(db_session, client)

    resultados = asyncio.run(ejecutar())

    assert "the-odds-api" not in {item["fuente"] for item in resultados}
    assert all("api.the-odds-api.com" not in url for url in llamadas)
    assert db_session.get(EstadoFuenteDeportiva, "api-football").cuota_restante == "99"


def test_verificacion_manual_incluye_the_odds_api_sin_persistir_clave_en_detalle(db_session, monkeypatch):
    async def respuesta(request: httpx.Request) -> httpx.Response:
        if "api.the-odds-api.com" in str(request.url):
            assert request.url.params.get("apiKey") == "clave-prueba"
        return httpx.Response(200, json={"response": []})

    monkeypatch.setattr(source_health.settings, "LIVESCORE6_KEY", "")
    monkeypatch.setattr(source_health.settings, "SPORTS_API_KEY", "")
    monkeypatch.setattr(source_health.settings, "FOOTBALL_DATA_KEY", "")
    monkeypatch.setattr(source_health.settings, "BSD_API_KEY", "")
    monkeypatch.setattr(source_health.settings, "THE_ODDS_API_KEY", "clave-prueba")
    monkeypatch.setattr(source_health.settings, "ODDSPAPI_SHARP_KEY", "")

    transport = httpx.MockTransport(respuesta)
    async def ejecutar() -> list[dict]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await source_health.verificar_fuentes(db_session, client, incluir_cuota_costosa=True)

    resultados = asyncio.run(ejecutar())

    odds = next(item for item in resultados if item["fuente"] == "the-odds-api")
    assert odds["saludable"] is True
    fila = db_session.get(EstadoFuenteDeportiva, "the-odds-api")
    assert fila.detalle is None
    assert "clave-prueba" not in str(fila.detalle)
