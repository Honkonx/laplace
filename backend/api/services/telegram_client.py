"""services/telegram_client.py — Cliente HTTP delgado para la API de Telegram.

Reemplaza los `httpRequest` a `api.telegram.org` repetidos en cada nodo de WF-A/WF-B/WF-D/WF-E.
Una sola implementación real (con manejo de error explícito, no un `catch(e) {}` silencioso como
en n8n) en vez de duplicarla en cada lugar que envía un mensaje.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from backend.api.core.config import settings

log = logging.getLogger("laplace.telegram")

API_BASE = "https://api.telegram.org"

# Reintentos de `enviar_mensaje` — 2026-09-09, hallazgo de auditoría: antes un único fallo de
# red (timeout, 5xx transitorio de Telegram) perdía el mensaje sin ningún reintento. Backoff
# corto y fijo (no exponencial — no vale la pena la complejidad para solo 2 reintentos):
# intento 1 inmediato, espera 1s, intento 2, espera 2s, intento 3 (último) — si sigue fallando
# ahí sí se devuelve False y se loguea, igual que antes.
_REINTENTO_DELAYS: tuple[float, ...] = (1.0, 2.0)


def _url(metodo: str) -> str:
    return f"{API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{metodo}"


async def enviar_mensaje(
    client: httpx.AsyncClient,
    chat_id: str,
    texto: str,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    """Envía un mensaje, con hasta `len(_REINTENTO_DELAYS)` reintentos (backoff corto) si falla.
    Devuelve True/False — el caller decide qué hacer con un fallo final, nunca se traga el
    error en silencio (a diferencia de los `catch(e) {}` de n8n)."""
    body: dict = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup is not None:
        body["reply_markup"] = reply_markup

    intentos_totales = len(_REINTENTO_DELAYS) + 1
    for intento in range(1, intentos_totales + 1):
        try:
            r = await client.post(_url("sendMessage"), json=body, timeout=15)
            r.raise_for_status()
            return True
        except Exception:
            if intento == intentos_totales:
                log.warning(
                    "Fallo enviando mensaje Telegram a chat_id=%s tras %d intento(s)",
                    chat_id, intentos_totales, exc_info=True,
                )
                return False
            log.info(
                "Fallo enviando mensaje Telegram a chat_id=%s (intento %d/%d) — reintentando en %ss",
                chat_id, intento, intentos_totales, _REINTENTO_DELAYS[intento - 1],
            )
            await asyncio.sleep(_REINTENTO_DELAYS[intento - 1])
    return False  # inalcanzable — el loop siempre retorna o agota reintentos arriba


async def responder_callback(
    client: httpx.AsyncClient,
    callback_query_id: str,
    texto: str = "",
    show_alert: bool = False,
) -> None:
    """ACK de un callback_query (botón inline) — no bloquear el flujo si falla."""
    try:
        await client.post(
            _url("answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": texto, "show_alert": show_alert},
            timeout=5,
        )
    except Exception:
        log.debug("Fallo respondiendo callback_query %s", callback_query_id, exc_info=True)
