"""Un proveedor de IA que responde 401, 402, 403 o 404 (clave sin créditos, sin permiso o modelo que ya no existe) se salta unos minutos en vez de gastar un intento por mensaje (hallazgo del 2026-11-13: Ollama Cloud
devolvía 402 y OpenRouter 404 con su modelo por defecto). Un 429 o un 5xx NO lo apartan: eso sí se arregla esperando. Todo con la red simulada."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(ai_client, "BACKOFF_REINTENTO_SEGUNDOS", 0)
    for clave in ("GOOGLE_API_KEY", "GROQ_API_KEY", "OLLAMA_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setattr(settings, clave, "")
    monkeypatch.setattr(settings, "AI_ROUTING_BOT", "groq,gemini")
    ai_client.reiniciar_enfriamientos()
    yield
    ai_client.reiniciar_enfriamientos()


def _red(monkeypatch, groq_estado: int, llamadas: list[str]):
    async def falso(self, url, **kw):
        nombre = "groq" if url == ai_client.GROQ_URL else "gemini"
        llamadas.append(nombre)
        if nombre == "groq":
            return httpx.Response(groq_estado, json={"error": "x"} if groq_estado != 200 else {"choices": [{"message": {"content": "de groq"}}]}, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "de gemini"}]}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", falso)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "fake")


@pytest.mark.parametrize("estado", [401, 402, 403, 404])
def test_un_error_de_configuracion_aparta_al_proveedor_y_la_cascada_sigue(monkeypatch, estado):
    llamadas: list[str] = []
    _red(monkeypatch, estado, llamadas)
    assert asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))[1] == "gemini"
    assert llamadas == ["groq", "gemini"]
    assert asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))[1] == "gemini"
    assert llamadas == ["groq", "gemini", "gemini"]                      # la segunda vez ni se intentó groq


@pytest.mark.parametrize("estado", [429, 500, 503])
def test_un_error_pasajero_no_aparta_al_proveedor(monkeypatch, estado):
    llamadas: list[str] = []
    _red(monkeypatch, estado, llamadas)
    asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))
    asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))
    assert llamadas.count("groq") >= 2                                    # se volvió a intentar (con su reintento corto)


def test_pasado_el_enfriamiento_se_vuelve_a_intentar(monkeypatch):
    llamadas: list[str] = []
    _red(monkeypatch, 402, llamadas)
    asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))
    ai_client._FUERA_HASTA["groq"] = 0.0                                   # venció el plazo
    asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))
    assert llamadas.count("groq") == 2


def test_una_respuesta_sin_texto_no_rompe_y_deja_seguir(monkeypatch):
    async def falso(self, url, **kw):
        if url == ai_client.GROQ_URL:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "reasoning": "pensando…"}}]}, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "de gemini"}]}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", falso)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "fake")
    assert asyncio.run(ai_client.generar_texto_ia_con_meta("hola"))[:2] == ("de gemini", "gemini")
