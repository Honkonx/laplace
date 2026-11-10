"""test_ai_client.py — cascada multi-proveedor de IA (Gemini → Groq → OpenRouter → Claude).

`test_cascada_real_contra_groq` es el único test de este archivo que golpea una API real
(Groq) — se salta automáticamente si no hay `GROQ_API_KEY` en el entorno (por ejemplo en CI
sin secretos), para no romper la suite en otra máquina. El resto son mocks puros.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client


@pytest.fixture(autouse=True)
def _sin_backoff(monkeypatch):
    monkeypatch.setattr(ai_client, "BACKOFF_REINTENTO_SEGUNDOS", 0)


def test_generar_texto_ia_usa_groq_si_responde(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")

    async def _fake_post(self, url, **kw):
        assert url == ai_client.GROQ_URL
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hola  "}}]},
                           request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    texto = asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))
    assert texto == "hola"


def test_generar_texto_ia_con_meta_expone_proveedor_y_modelo(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")

    async def _fake_post(self, url, **kw):
        return httpx.Response(200, json={"choices": [{"message": {"content": "respuesta"}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    texto, proveedor, modelo = asyncio.run(ai_client.generar_texto_ia_con_meta("prompt de prueba"))
    assert (texto, proveedor, modelo) == ("respuesta", "groq", settings.GROQ_MODEL)


def test_generar_texto_ia_manda_ai_temperature_default_a_cada_proveedor(monkeypatch):
    """Ningún caller real pasa `temperature` hoy (ver `analisis_completo.py`/`top_picks.py`) —
    confirma que el default cae en `settings.AI_TEMPERATURE` (0.4, no el default ~1.0 del
    proveedor) y que se manda en el body real, no solo que quedó declarado en la función."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")

    capturado = {}

    async def _fake_post(self, url, **kw):
        capturado["json"] = kw["json"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]},
                           request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))
    assert capturado["json"]["temperature"] == settings.AI_TEMPERATURE


def test_generar_texto_ia_permite_override_de_temperature(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")

    capturado = {}

    async def _fake_post(self, url, **kw):
        capturado["json"] = kw["json"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]},
                           request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    asyncio.run(ai_client.generar_texto_ia("prompt de prueba", temperature=0.9))
    assert capturado["json"]["temperature"] == 0.9


def test_generar_texto_ia_cae_a_gemini_si_groq_falla(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "fake")

    async def _fake_post(self, url, **kw):
        req = httpx.Request("POST", url)
        if url == ai_client.GROQ_URL:
            return httpx.Response(429, json={"error": "rate limited"}, request=req)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "desde gemini"}]}}]}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    texto = asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))
    assert texto == "desde gemini"


def test_generar_texto_ia_lanza_error_si_nadie_responde(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))


@pytest.mark.skipif(
    not settings.GROQ_API_KEY or os.environ.get("RUN_LIVE_AI_TESTS") != "1",
    reason="prueba externa: requiere GROQ_API_KEY y RUN_LIVE_AI_TESTS=1",
)
def test_cascada_real_contra_groq():
    """Prueba real (no mock) contra la API de Groq — confirma empíricamente que la key y el
    modelo `GROQ_MODEL` siguen funcionando, no solo que el código compila."""
    texto = asyncio.run(ai_client.generar_texto_ia("Responde solo con la palabra OK", max_tokens=10))
    assert "OK" in texto.upper()
