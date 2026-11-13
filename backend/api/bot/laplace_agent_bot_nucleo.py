"""bot/laplace_agent_bot_nucleo.py — consulta al agente y ejecución de herramientas deportivas."""
from __future__ import annotations

import logging

from telegram import Update

from backend.api.db.session import SessionLocal
from backend.api.services.agent_guard import (
    LimiteExcedido,
    autorizacion_sports,
    consumir_ia,
)
from backend.api.services.agent_runtime import procesar_mensaje, sincronizar_conocimiento_json
from backend.api.services.agent_sesiones import ultima_sesion
from backend.api.services.agent_tools import ejecutar_herramienta_deportiva

log = logging.getLogger("laplace.agent_telegram")

from backend.api.bot.laplace_agent_bot_formato import _enviar
from backend.api.bot.laplace_agent_bot_acceso import _es_admin


async def _consultar_agente(update: Update, texto: str, usar_ia: bool) -> None:
    usuario = f"telegram:{update.effective_user.id}"
    admin = _es_admin(update)
    if usar_ia and not admin:  # el administrador no tiene tope de IA
        try:
            consumir_ia(usuario, es_admin=False)
        except LimiteExcedido as exc:
            await update.effective_message.reply_text(f"{exc}. Inténtalo más tarde.")
            return
    with SessionLocal() as db:
        sincronizar_conocimiento_json(db)
        resultado = await procesar_mensaje(db, user_id=usuario, mensaje=texto, session_id=ultima_sesion(db, usuario, "telegram_agent"), channel="telegram_agent", usar_ia=usar_ia, es_admin=admin)
    await _enviar(update, resultado["respuesta"])


async def _herramienta(update: Update, nombre: str, argumentos: dict, *, aprobado: bool = False) -> dict:
    usuario = f"telegram:{update.effective_user.id}"
    admin = _es_admin(update)
    return await ejecutar_herramienta_deportiva(
        nombre, argumentos, es_admin=admin, authorization=autorizacion_sports(usuario, None, admin=admin), aprobado=aprobado,
        usuario=usuario,  # el tope de predicciones se aplica dentro de la herramienta, igual para todos los caminos
    )
