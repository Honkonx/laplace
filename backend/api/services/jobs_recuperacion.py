"""services/jobs_recuperacion.py — avisar a quien pidió un análisis que el servicio reinició a mitad (H-010, 2026-11-11).

Antes, un análisis interrumpido por un reinicio quedaba «procesando» hasta 15–30 minutos y luego pasaba a `error` EN SILENCIO: la persona esperaba un mensaje que nunca llegaba (el mismo
síntoma que el incidente del botón). Ahora, al arrancar, todo trabajo pendiente de un proceso anterior se marca `error` y a quien lo pidió por Telegram se le avisa para que lo repita.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.db import jobs_repo
from backend.api.services import telegram_client

log = logging.getLogger("laplace.jobs")
MAX_AVISOS = 200
TEXTO = "⚠️ Se interrumpió tu análisis porque el servicio se reinició. No quedó guardado: vuelve a pedirlo con /juegos."


async def notificar_interrumpidos(client: httpx.AsyncClient, detalle: list[dict], enviar=telegram_client.enviar_mensaje) -> int:
    """Avisa a cada chat de Telegram afectado (una vez por chat); devuelve cuántos avisos salieron."""
    chats = list(dict.fromkeys(d["chat_id"] for d in detalle if d.get("origen") == "telegram" and d.get("chat_id")))[:MAX_AVISOS]
    enviados = 0
    for chat in chats:
        try:
            enviados += bool(await enviar(client, chat, TEXTO))
        except Exception:  # noqa: BLE001 — un aviso fallido no debe impedir los demás
            log.warning("no se pudo avisar al chat %s del análisis interrumpido", chat)
    return enviados


async def recuperar_al_arrancar(db: Session, client: httpx.AsyncClient, enviar=telegram_client.enviar_mensaje) -> dict:
    """Marca como error todo trabajo que quedó en vuelo de un proceso anterior y avisa a sus dueños."""
    r = jobs_repo.reset_jobs_colgados(db, todos=True)
    avisos = await notificar_interrumpidos(client, r["detalle"], enviar) if r["reseteados"] else 0
    if r["reseteados"]:
        log.warning("recuperación al arrancar: %d trabajo(s) interrumpido(s), %d aviso(s)", r["reseteados"], avisos)
    return {"reseteados": r["reseteados"], "avisos": avisos}
