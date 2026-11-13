"""bot/laplace_agent_bot_acceso.py — autorización, rate limit y decoradores del bot del agente."""
from __future__ import annotations

import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from backend.api.core.config import settings
from backend.api.services.agent_guard import (
    consumir_mensaje_chat,
    lista_env,
)

log = logging.getLogger("laplace.agent_telegram")


MULTIPLICADOR_ADMIN_MENSAJES = 6

MSG_NO_AUTORIZADO = "No tienes acceso a este agente."
MSG_LIMITE = "Estás escribiendo demasiado rápido; espera un minuto e inténtalo de nuevo."
MSG_ERROR = "Ocurrió un error procesando tu mensaje. Inténtalo de nuevo en un momento."
MSG_SOLO_ADMIN = "Este comando es solo para el administrador."


def _id_usuario(update: Update) -> str:
    return str(update.effective_user.id) if update.effective_user else ""


def _es_admin(update: Update) -> bool:
    return bool(update.effective_user) and _id_usuario(update) in settings.admin_ids


def _esta_autorizado(update: Update) -> bool:
    """Abierto a todos salvo vetados; si `AGENT_TELEGRAM_ALLOWED_IDS` tiene valores, modo restringido."""
    if not update.effective_user:
        return False
    if _id_usuario(update) in lista_env("AGENT_TELEGRAM_BLOCKED_IDS") and not _es_admin(update):
        return False
    if _es_admin(update):
        return True
    permitidos = lista_env("AGENT_TELEGRAM_ALLOWED_IDS")
    return not permitidos or _id_usuario(update) in permitidos


def protegido(handler):
    """Veto/allowlist opcional + rate limit por chat (relajado para el admin) + errores contenidos."""

    @functools.wraps(handler)
    async def envoltorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        mensaje = update.effective_message
        if not update.effective_user or not mensaje:
            return
        if not _esta_autorizado(update):
            log.warning("Telegram del agente: usuario no autorizado %s", update.effective_user.id)
            await mensaje.reply_text(MSG_NO_AUTORIZADO)
            return
        chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
        tope = None
        if _es_admin(update):
            from backend.api.services.agent_guard import entero_env

            tope = entero_env("AGENT_TELEGRAM_RATE_PER_MIN", 10) * MULTIPLICADOR_ADMIN_MENSAJES
        if not consumir_mensaje_chat(f"chat:{chat_id}", tope):
            await mensaje.reply_text(MSG_LIMITE)
            return
        try:
            await handler(update, context)
        except Exception:
            log.exception("Fallo en el handler %s del bot del agente", handler.__name__)
            try:
                await mensaje.reply_text(MSG_ERROR)
            except Exception:
                log.exception("No se pudo avisar del error al usuario")

    return envoltorio


def solo_admin(handler):
    """Doble barrera: el comando solo corre para administradores verificados por id de Telegram."""

    @functools.wraps(handler)
    async def envoltorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _es_admin(update):
            await update.effective_message.reply_text(MSG_SOLO_ADMIN)
            return
        await handler(update, context)

    return envoltorio
