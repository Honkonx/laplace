"""test_telegram_client.py — cliente HTTP delgado para la API de Telegram. Usa
httpx.MockTransport (nunca llama a api.telegram.org real)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import telegram_client


@pytest.fixture(autouse=True)
def _reset_settings():
    original = settings.TELEGRAM_BOT_TOKEN
    settings.TELEGRAM_BOT_TOKEN = "test-token-123"
    yield
    settings.TELEGRAM_BOT_TOKEN = original


@pytest.fixture(autouse=True)
def _sin_espera_real(monkeypatch):
    """`enviar_mensaje` ahora reintenta con `asyncio.sleep()` entre intentos (2026-09-09, ver
    `_REINTENTO_DELAYS`) — sin este parche cada test que agota los reintentos tardaría
    `sum(_REINTENTO_DELAYS)` segundos reales. Se registra cada espera pedida en `esperas` para
    que los tests de reintento puedan verificar cuántas veces y con qué backoff se esperó,
    sin dormir de verdad."""
    esperas: list[float] = []

    async def _sleep_fake(segundos: float) -> None:
        esperas.append(segundos)

    monkeypatch.setattr(telegram_client.asyncio, "sleep", _sleep_fake)
    return esperas


def test_url_arma_endpoint_con_token_y_metodo():
    url = telegram_client._url("sendMessage")
    assert url == "https://api.telegram.org/bottest-token-123/sendMessage"


def test_enviar_mensaje_exitoso_devuelve_true():
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(client, "12345", "Hola mundo")

    resultado = asyncio.run(_run())
    assert resultado is True
    assert "sendMessage" in capturado["url"]
    assert b'"chat_id":"12345"' in capturado["body"]
    assert b'"text":"Hola mundo"' in capturado["body"]


def test_enviar_mensaje_incluye_reply_markup_solo_si_se_pasa():
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["body"] = request.read()
        return httpx.Response(200, json={"ok": True})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(
                client, "1", "Con botones", reply_markup={"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}
            )

    asyncio.run(_run())
    assert b'"reply_markup"' in capturado["body"]


def test_enviar_mensaje_error_http_devuelve_false_no_lanza(_sin_espera_real):
    """Caso límite: Telegram devuelve 400 (chat_id inválido, etc.) — el cliente nunca se
    traga el error en silencio como los `catch(e) {}` de n8n, pero tampoco lo propaga: el
    caller decide qué hacer a partir del bool devuelto (falla persistente -> ya agotó los
    reintentos, ver `test_enviar_mensaje_agota_reintentos_y_devuelve_false` más abajo)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(client, "chat-invalido", "texto")

    resultado = asyncio.run(_run())
    assert resultado is False


def test_enviar_mensaje_timeout_devuelve_false_no_lanza(_sin_espera_real):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(client, "1", "texto")

    resultado = asyncio.run(_run())
    assert resultado is False


def test_enviar_mensaje_agota_reintentos_y_devuelve_false(_sin_espera_real):
    """Cubre el reintento con backoff agregado 2026-09-09 (`_REINTENTO_DELAYS`): si TODOS los
    intentos fallan, se hacen exactamente `len(_REINTENTO_DELAYS) + 1` llamadas HTTP reales
    (1 intento inicial + reintentos), con una espera entre cada una que seguí el backoff
    configurado, y solo al final devuelve False."""
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        raise httpx.ConnectTimeout("timeout simulado")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(client, "1", "texto")

    resultado = asyncio.run(_run())
    assert resultado is False
    assert intentos["n"] == len(telegram_client._REINTENTO_DELAYS) + 1
    assert _sin_espera_real == list(telegram_client._REINTENTO_DELAYS)


def test_enviar_mensaje_reintenta_y_tiene_exito_en_intento_posterior(_sin_espera_real):
    """Caso central del fix: el primer intento falla (timeout transitorio), el segundo
    intento (tras el primer backoff) tiene éxito — el mensaje NO se pierde, a diferencia del
    comportamiento anterior (un solo intento, sin reintento)."""
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise httpx.ConnectTimeout("timeout simulado en el primer intento")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await telegram_client.enviar_mensaje(client, "1", "texto")

    resultado = asyncio.run(_run())
    assert resultado is True
    assert intentos["n"] == 2
    # Solo se esperó UNA vez (antes del 2do intento, que ya tuvo éxito) — no siguió reintentando
    # de más tras el éxito.
    assert _sin_espera_real == [telegram_client._REINTENTO_DELAYS[0]]


def test_responder_callback_no_lanza_si_falla():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await telegram_client.responder_callback(client, "cbq-1", "listo")

    # No debe lanzar — responder_callback traga la excepción (ACK best-effort, ver docstring)
    asyncio.run(_run())


def test_responder_callback_envia_show_alert():
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["body"] = request.read()
        return httpx.Response(200, json={"ok": True})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await telegram_client.responder_callback(client, "cbq-2", "Alerta!", show_alert=True)

    asyncio.run(_run())
    assert b'"show_alert":true' in capturado["body"]
