"""test_ai_metrics.py — instrumentación de costo/latencia por proveedor de IA
(`services/ai_metrics.py`) y su integración real con la cascada de `services/ai_client.py`.

`conftest.py::_resetear_estado_global_entre_tests` (autouse) limpia el acumulador in-memory
antes/después de cada test."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import ai_client, ai_metrics


def test_registrar_intento_acumula_exitos_y_fallos():
    ai_metrics.registrar_intento("groq", exitoso=True, latencia_ms=80.0, modelo="modelo-x")
    ai_metrics.registrar_intento("groq", exitoso=False, latencia_ms=120.0, modelo="modelo-x", error="timeout")
    ai_metrics.registrar_intento("groq", exitoso=True, latencia_ms=100.0, modelo="modelo-x")

    resumen = ai_metrics.resumen_metricas()["groq"]
    assert resumen["intentos"] == 3
    assert resumen["exitosos"] == 2
    assert resumen["fallidos"] == 1
    assert resumen["latencia_promedio_ms"] == 100.0  # (80+120+100)/3


def test_resumen_metricas_vacio_sin_intentos():
    assert ai_metrics.resumen_metricas() == {}


def test_resetear_limpia_el_acumulador():
    ai_metrics.registrar_intento("gemini", exitoso=True, latencia_ms=50.0)
    ai_metrics.resetear()
    assert ai_metrics.resumen_metricas() == {}


def test_registrar_intento_nunca_lanza_aunque_algo_interno_falle(monkeypatch):
    """La instrumentación no debe poder tumbar la cascada real de IA que está midiendo."""

    def _log_info_roto(*a, **kw):
        raise RuntimeError("logging roto, no debería propagar")

    monkeypatch.setattr(ai_metrics.log, "info", _log_info_roto)
    ai_metrics.registrar_intento("groq", exitoso=True, latencia_ms=10.0)  # no debe lanzar


def test_ms_desde_devuelve_un_valor_positivo():
    inicio = time.perf_counter()
    assert ai_metrics.ms_desde(inicio) >= 0.0


# ─── Integración real con ai_client.py (la cascada realmente instrumenta cada intento) ────


def test_generar_texto_ia_registra_metrica_de_groq_en_exito(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")

    async def _fake_post(self, url, **kw):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hola"}}]},
                               request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))

    resumen = ai_metrics.resumen_metricas()["groq"]
    assert resumen["intentos"] == 1
    assert resumen["exitosos"] == 1
    assert resumen["fallidos"] == 0
    assert resumen["latencia_promedio_ms"] is not None


def test_generar_texto_ia_registra_metrica_de_fallo_y_del_proveedor_siguiente(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "fake")

    async def _fake_post(self, url, **kw):
        req = httpx.Request("POST", url)
        if url.startswith("https://generativelanguage.googleapis.com/"):
            return httpx.Response(429, json={"error": "rate limited"}, request=req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "desde groq"}}]}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))

    resumen = ai_metrics.resumen_metricas()
    assert resumen["gemini"]["fallidos"] == 1
    assert resumen["gemini"]["exitosos"] == 0
    assert resumen["groq"]["exitosos"] == 1


def test_proveedor_sin_api_key_no_registra_metrica(monkeypatch):
    """Sin key configurada, la función devuelve None de inmediato sin intentar ninguna
    request real — no debe contarse como un "intento" (no hubo latencia real que medir)."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    with pytest.raises(ai_client.AnalisisIAError):
        asyncio.run(ai_client.generar_texto_ia("prompt de prueba"))

    assert ai_metrics.resumen_metricas() == {}
