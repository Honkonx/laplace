"""Llamadas a herramientas nativas (Gemini y formato OpenAI) con transporte simulado: la IA pide, el servidor ejecuta solo lo registrado."""
import asyncio
import json

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client, ai_herramientas
from backend.api.services.ai_herramientas import Herramienta


def _cliente(handler, monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(ai_herramientas.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def _herramienta(llamadas: list):
    async def ejecutar(args):
        llamadas.append(args)
        return {"p1x2": {"local": 0.5}}

    return Herramienta("laplace_pronosticar", "pronostica", {"type": "object", "properties": {"local": {"type": "string"}}}, ejecutar)


@pytest.fixture(autouse=True)
def _claves(monkeypatch):
    for k in ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setattr(settings, k, "")


def test_gemini_pide_la_herramienta_el_servidor_la_ejecuta_y_la_ia_redacta(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "k")
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", "gemini")
    cuerpos = []

    def handler(req):
        cuerpos.append(json.loads(req.content))
        if len(cuerpos) == 1:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"functionCall": {"name": "laplace_pronosticar", "args": {"local": "A"}}}]}}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "El modelo da 50 % al local."}]}}]})

    _cliente(handler, monkeypatch)
    llamadas = []
    r = asyncio.run(ai_herramientas.consultar("pregunta", [_herramienta(llamadas)]))
    assert r["texto"] == "El modelo da 50 % al local." and r["proveedor"] == "gemini" and llamadas == [{"local": "A"}]
    assert cuerpos[0]["tools"][0]["functionDeclarations"][0]["name"] == "laplace_pronosticar"
    assert "functionResponse" in json.dumps(cuerpos[1]) and r["herramientas_usadas"] == [{"nombre": "laplace_pronosticar", "ok": True}]


def test_formato_openai_groq(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", "groq")
    n = []

    def handler(req):
        n.append(json.loads(req.content))
        if len(n) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "laplace_pronosticar", "arguments": "{\"local\": \"B\"}"}}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Listo."}}]})

    _cliente(handler, monkeypatch)
    llamadas = []
    r = asyncio.run(ai_herramientas.consultar("pregunta", [_herramienta(llamadas)]))
    assert r["texto"] == "Listo." and llamadas == [{"local": "B"}]
    assert n[1]["messages"][-1]["role"] == "tool" and n[1]["messages"][-1]["tool_call_id"] == "c1"


def test_una_herramienta_que_no_esta_registrada_no_se_ejecuta(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", "groq")
    n = []

    def handler(req):
        n.append(json.loads(req.content))
        if len(n) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "borrar_todo", "arguments": "{}"}}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "No pude."}}]})

    _cliente(handler, monkeypatch)
    llamadas = []
    r = asyncio.run(ai_herramientas.consultar("p", [_herramienta(llamadas)]))
    assert llamadas == [] and "desconocida" in n[1]["messages"][-1]["content"] and r["herramientas_usadas"] == [{"nombre": "borrar_todo", "ok": False}]


def test_si_la_ia_no_deja_de_pedir_herramientas_se_corta_y_cae_al_error(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", "groq")
    pide = httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "laplace_pronosticar", "arguments": "{}"}}]}}]})
    _cliente(lambda req: pide, monkeypatch)
    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_herramientas.consultar("p", [_herramienta([])]))


def test_proveedor_sin_soporte_o_sin_clave_lanza_el_error_para_caer_al_texto(monkeypatch):
    monkeypatch.setattr(settings, "AI_ROUTING_AGENTE", "claude")
    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_herramientas.consultar("p", [_herramienta([])]))


def test_los_argumentos_enormes_se_rechazan_sin_ejecutar():
    llamadas = []
    r = asyncio.run(ai_herramientas._ejecutar({"laplace_pronosticar": _herramienta(llamadas)}, "laplace_pronosticar", {"local": "x" * 5000}))
    assert llamadas == [] and "largos" in r["error"]


def test_la_herramienta_del_modelo_devuelve_solo_numeros_del_resumen(monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: {"ok": False, "motivo": "sin modelo"})
    h = ai_herramientas.herramienta_modelo_laplace()
    assert asyncio.run(h.ejecutar({"local": "A", "visitante": "B"})) == {"error": "sin modelo"}
