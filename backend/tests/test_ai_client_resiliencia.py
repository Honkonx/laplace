"""test_ai_client_resiliencia.py — reintento único ante 429/5xx y presupuesto total de tiempo."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client


@pytest.fixture(autouse=True)
def _solo_groq_sin_backoff(monkeypatch):
    monkeypatch.setattr(ai_client, "BACKOFF_REINTENTO_SEGUNDOS", 0)
    for k in ("GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")


def _ok(url):
    return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]},
                          request=httpx.Request("POST", url))


def test_reintenta_una_vez_ante_429_y_se_recupera(monkeypatch):
    llamadas = []

    async def _fake_post(self, url, **kw):
        llamadas.append(url)
        if len(llamadas) == 1:
            return httpx.Response(429, json={}, request=httpx.Request("POST", url))
        return _ok(url)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    assert asyncio.run(ai_client.generar_texto_ia("p")) == "ok"
    assert len(llamadas) == 2


def test_no_reintenta_ante_4xx_distinto_de_429(monkeypatch):
    llamadas = []

    async def _fake_post(self, url, **kw):
        llamadas.append(url)
        return httpx.Response(401, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_client.generar_texto_ia("p"))
    assert len(llamadas) == 1


def test_reintento_limitado_a_uno_ante_5xx_persistente(monkeypatch):
    llamadas = []

    async def _fake_post(self, url, **kw):
        llamadas.append(url)
        return httpx.Response(503, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_client.generar_texto_ia("p"))
    assert len(llamadas) == 2


def test_presupuesto_agotado_no_llama_a_ningun_proveedor(monkeypatch):
    monkeypatch.setattr(ai_client, "PRESUPUESTO_TOTAL_SEGUNDOS", 0.0)
    llamadas = []

    async def _fake_post(self, url, **kw):
        llamadas.append(url)
        return _ok(url)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_client.generar_texto_ia("p"))
    assert llamadas == []


def test_timeout_por_llamada_no_supera_el_presupuesto_restante(monkeypatch):
    monkeypatch.setattr(ai_client, "PRESUPUESTO_TOTAL_SEGUNDOS", 5.0)
    timeouts = []

    async def _fake_post(self, url, **kw):
        timeouts.append(kw["timeout"])
        return _ok(url)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    asyncio.run(ai_client.generar_texto_ia("p"))
    assert timeouts and timeouts[0] <= 5.0
