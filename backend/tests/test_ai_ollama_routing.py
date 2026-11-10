"""test_ai_ollama_routing.py — proveedor Ollama Cloud y enrutamiento por rol de
`services/ai_client.py`. Todo con mocks de httpx: no hay llamadas de red reales."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client


@pytest.fixture(autouse=True)
def _sin_proveedores(monkeypatch):
    """Aísla del `.env` real: ningún proveedor configurado salvo lo que cada test active."""
    for campo in ("GROQ_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
                  "OLLAMA_API_KEY", "OLLAMA_LOCAL_MODEL", "AI_ROUTING_BOT", "AI_ROUTING_CANAL",
                  "AI_ROUTING_AGENTE", "AI_ROUTING_LABORATORIO"):
        monkeypatch.setattr(settings, campo, "")
    monkeypatch.setattr(settings, "OLLAMA_LOCAL_URL", "http://localhost:11434")
    monkeypatch.setattr(settings, "OLLAMA_CLOUD_MODEL", "gpt-oss:120b")


def _respuesta_ollama(url: str, contenido: str, thinking: str | None = None) -> httpx.Response:
    mensaje = {"role": "assistant", "content": contenido}
    if thinking is not None:
        mensaje["thinking"] = thinking
    return httpx.Response(200, json={"message": mensaje}, request=httpx.Request("POST", url))


def _respuesta_openai(url: str, contenido: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": contenido}}]},
                          request=httpx.Request("POST", url))


def _mockear_post(monkeypatch, fabrica) -> list[dict]:
    llamadas: list[dict] = []

    async def _fake_post(self, url, **kw):
        llamadas.append({"url": url, **kw})
        return fabrica(url, kw)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    return llamadas


def test_ollama_cloud_usa_bearer_y_solo_content(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "clave-falsa")
    llamadas = _mockear_post(monkeypatch, lambda url, kw: _respuesta_ollama(url, "  respuesta cloud ", "razonando..."))

    texto, proveedor, modelo = asyncio.run(ai_client.generar_texto_ia_con_meta("hola", max_tokens=50))

    assert (texto, proveedor, modelo) == ("respuesta cloud", "ollama_cloud", "gpt-oss:120b")
    llamada = llamadas[0]
    assert llamada["url"] == ai_client.OLLAMA_CLOUD_URL
    assert llamada["headers"] == {"Authorization": "Bearer clave-falsa"}
    assert llamada["timeout"] == 30
    assert llamada["json"]["stream"] is False
    assert llamada["json"]["options"] == {"temperature": settings.AI_TEMPERATURE, "num_predict": ai_client.OLLAMA_NUM_PREDICT_MINIMO}


def test_ollama_local_heredado_no_entra_en_la_cascada(monkeypatch):
    """Laplace opera contra Ollama Cloud aunque exista configuración local heredada."""
    monkeypatch.setattr(settings, "OLLAMA_LOCAL_MODEL", "llama3.2:3b")
    monkeypatch.setattr(settings, "OLLAMA_LOCAL_URL", "http://127.0.0.1:11434/")
    assert "ollama_local" not in ai_client.orden_proveedores("bot")
    assert "ollama_local" not in ai_client._PROVEEDORES


def test_ollama_content_vacio_pasa_al_siguiente(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "k")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(settings, "AI_ROUTING_BOT", "ollama_cloud,groq")

    def fabrica(url, kw):
        if url == ai_client.OLLAMA_CLOUD_URL:
            return _respuesta_ollama(url, "", "solo pensó")
        return _respuesta_openai(url, "groq")

    _mockear_post(monkeypatch, fabrica)
    assert asyncio.run(ai_client.generar_texto_ia("hola")) == "groq"


def test_orden_por_defecto_por_rol():
    general = ("gemini", "groq", "ollama_cloud", "openrouter", "claude")
    assert ai_client.orden_proveedores("bot") == general
    assert ai_client.orden_proveedores("canal") == general
    assert ai_client.orden_proveedores("laboratorio") == general
    assert ai_client.orden_proveedores("agente") == (
        "ollama_cloud", "groq", "gemini", "openrouter", "claude"
    )


def test_rol_agente_prueba_ollama_cloud_antes_que_groq(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "k")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    llamadas = _mockear_post(monkeypatch, lambda url, kw: _respuesta_ollama(url, "agente"))

    _, proveedor, _ = asyncio.run(ai_client.generar_texto_ia_con_meta("hola", rol="agente"))

    assert proveedor == "ollama_cloud"
    assert [c["url"] for c in llamadas] == [ai_client.OLLAMA_CLOUD_URL]


def test_rol_bot_prueba_groq_antes_que_ollama_cloud(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", "k")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    _mockear_post(monkeypatch, lambda url, kw: _respuesta_openai(url, "groq"))

    _, proveedor, _ = asyncio.run(ai_client.generar_texto_ia_con_meta("hola", rol="bot"))

    assert proveedor == "groq"


def test_orden_custom_por_entorno_ignora_desconocidos_y_duplicados(monkeypatch, caplog):
    monkeypatch.setattr(settings, "AI_ROUTING_CANAL", " Groq, inventado ,ollama_cloud,groq,, ")
    with caplog.at_level("WARNING", logger="laplace.ai_client"):
        orden = ai_client.orden_proveedores("canal")
    assert orden == ("groq", "ollama_cloud")
    assert any("inventado" in m for m in caplog.messages)


@pytest.mark.parametrize("valor", ["", "  ,, ", "inventado,otro"])
def test_orden_invalido_o_vacio_cae_al_default(monkeypatch, valor):
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", valor)
    assert ai_client.orden_proveedores("agente") == ai_client.ROUTING_DEFAULT["agente"]


def test_rol_desconocido_usa_orden_de_bot():
    assert ai_client.orden_proveedores("no-existe") == ai_client.ROUTING_DEFAULT["bot"]
