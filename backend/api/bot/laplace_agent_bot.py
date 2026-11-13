"""Bot Telegram del agente superior Laplace.

Usa un token distinto al bot deportivo y conversa con el runtime del agente.

ACCESO (decisión del usuario, 2026-10-07): el agente funciona para TODOS los usuarios de Telegram.
Los privilegios, en cambio, son solo del administrador (`settings.admin_ids`):

- Cualquier usuario: conversar con el agente, consultar partidos, ligas y Top Picks publicados,
  pedir una predicción (`/predecir A vs B`) y usar IA con un presupuesto diario acotado.
- Administrador: sin topes de IA ni de mensajes, acciones con efectos (`/resultados`, `/toppicks`,
  `/publicar confirmo`), panel del sistema (`/panel`), salud de fuentes (`/fuentes`) y decisión de
  aprobaciones (`/aprobaciones`, `/decidir`). Las herramientas de administración siguen marcadas
  `admin_only` en `agent_tools`: un usuario normal nunca las ejecuta aunque lo pida por chat.

Variables de entorno (opcionales): `AGENT_TELEGRAM_ALLOWED_IDS` (si tiene valores, vuelve el modo
restringido: solo esos ids y los administradores), `AGENT_TELEGRAM_BLOCKED_IDS` (ids vetados, tiene
prioridad), `AGENT_TELEGRAM_RATE_PER_MIN` (def. 10 por chat), `AGENT_IA_MAX_POR_MINUTO`/`_POR_DIA`,
`AGENT_PREDICCIONES_MAX_POR_DIA` (def. 15; cada predicción consulta APIs externas con cuota).
"""
from __future__ import annotations

import functools  # noqa: F401
import logging
import re  # noqa: F401
from datetime import datetime, timedelta  # noqa: F401
from zoneinfo import ZoneInfo  # noqa: F401

import httpx  # noqa: F401
from sqlalchemy import text  # noqa: F401
from telegram import BotCommand, BotCommandScopeChat, Update  # noqa: F401
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from backend.api.bot.laplace_agent_bot_acceso import (  # noqa: F401
    MSG_ERROR,
    MSG_LIMITE,
    MSG_NO_AUTORIZADO,
    MSG_SOLO_ADMIN,
    MULTIPLICADOR_ADMIN_MENSAJES,
    _es_admin,
    _esta_autorizado,
    _id_usuario,
    protegido,
    solo_admin,
)
from backend.api.bot.laplace_agent_bot_admin import (  # noqa: F401
    PALABRAS_APROBAR,
    PALABRAS_RECHAZAR,
    cmd_aprobaciones,
    cmd_decidir_aprobacion,
    cmd_fuentes,
    cmd_marcador,
    cmd_panel,
    cmd_publicar,
    cmd_resultados,
    cmd_toppicks,
)
from backend.api.bot.laplace_agent_bot_comandos import (  # noqa: F401
    _buscar_partido,
    _responder,
    cmd_ayuda,
    cmd_estado,
    cmd_nuevo,
    cmd_incognito,
    cmd_olvidar,
    cmd_retomar,
    cmd_simular,
    cmd_sesiones,
    cmd_ia,
    cmd_ligas,
    cmd_partidos,
    cmd_predecir,
    cmd_start,
    cmd_top,
)
from backend.api.bot.laplace_agent_bot_formato import (  # noqa: F401
    AVISO_ESTIMACION,
    COMANDOS_ADMIN,
    COMANDOS_PUBLICOS,
    LIMITE_PARTIDOS,
    MAX_MENSAJE,
    TZ_CHILE,
    _coincide,
    _enviar,
    _es_token_fecha,
    _fecha_desde,
    _hora_corta,
    _separar_equipos,
    formatear_partidos,
    formatear_prediccion,
)
from backend.api.bot.laplace_agent_bot_nucleo import _consultar_agente, _herramienta  # noqa: F401
from backend.api.core.config import settings
from backend.api.db.session import SessionLocal  # noqa: F401
from backend.api.models.agent_runtime import AgentApproval, AgentMemory, AgentTask  # noqa: F401
from backend.api.services.agent_approvals import AprobacionError, decidir_aprobacion, expirar_vencidas  # noqa: F401
from backend.api.services.agent_guard import (  # noqa: F401
    LimiteExcedido,
    autorizacion_sports,
    consumir_ia,
    consumir_mensaje_chat,
    lista_env,
)
from backend.api.services.agent_runtime import procesar_mensaje, sincronizar_conocimiento_json  # noqa: F401
from backend.api.services.agent_tools import ejecutar_herramienta_deportiva  # noqa: F401

log = logging.getLogger("laplace.agent_telegram")


async def _error_global(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error no controlado en el bot del agente", exc_info=context.error)


async def _publicar_menu_de_comandos(app: Application) -> None:
    """Menú de comandos de Telegram: público para todos y ampliado en el chat de cada admin."""
    try:
        await app.bot.set_my_commands([BotCommand(n, d) for n, d in COMANDOS_PUBLICOS])
        for admin_id in settings.admin_ids:
            try:
                await app.bot.set_my_commands(
                    [BotCommand(n, d) for n, d in COMANDOS_PUBLICOS + COMANDOS_ADMIN], scope=BotCommandScopeChat(chat_id=int(admin_id)))
            except Exception:  # el admin aún no abrió el chat con el bot: no es un error del arranque
                log.info("No se pudo fijar el menú de admin para %s", admin_id)
    except Exception:
        log.warning("No se pudo publicar el menú de comandos del bot del agente", exc_info=True)


def construir_app() -> Application:
    if not settings.AGENT_TELEGRAM_BOT_TOKEN:
        raise RuntimeError("AGENT_TELEGRAM_BOT_TOKEN no está configurado")
    app = Application.builder().token(settings.AGENT_TELEGRAM_BOT_TOKEN).post_init(_publicar_menu_de_comandos).build()
    for nombre, funcion in (
        ("start", cmd_start), ("ayuda", cmd_ayuda), ("ia", cmd_ia), ("estado", cmd_estado), ("partidos", cmd_partidos),
        ("predecir", cmd_predecir), ("top", cmd_top), ("ligas", cmd_ligas), ("panel", cmd_panel), ("fuentes", cmd_fuentes),
        ("resultados", cmd_resultados), ("toppicks", cmd_toppicks), ("publicar", cmd_publicar),
        ("aprobaciones", cmd_aprobaciones), ("decidir", cmd_decidir_aprobacion),
        ("nuevo", cmd_nuevo), ("incognito", cmd_incognito), ("olvidar", cmd_olvidar), ("sesiones", cmd_sesiones), ("retomar", cmd_retomar), ("marcador", cmd_marcador), ("simular", cmd_simular),
    ):
        app.add_handler(CommandHandler(nombre, funcion))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _responder))
    app.add_error_handler(_error_global)
    return app
