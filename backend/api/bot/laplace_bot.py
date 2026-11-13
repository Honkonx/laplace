"""bot/laplace_bot.py — Bot de Telegram (reemplaza WF-A completo).

Port de WF-A (`Router Comandos` + las 8 ramas) usando `python-telegram-bot` v21 (async) en vez
del `n8n-nodes-base.telegramTrigger` + `httpRequest` a `sendMessage`. Bugs reales de WF-A que
este port NO reproduce (encontrados leyendo el JSON, documentados en `docs/humano/`):
  - `/stats` y `/top` en n8n nunca asignaban el resultado de `httpRequest` (variable fantasma
    `r`/`r1`/`r2`) — siempre mostraban datos vacíos. Acá `analisis_repo.leer_stats(...)` se
    llama y se usa de verdad.
  - El límite del plan `pro` (`Verificar Límite Plan`, wfa-045) tenía el mismo bug y caía
    siempre al `catch` → `puede=true` (fail-open). `usuarios_repo.puede_usar_ia(...)` no repite
    ese comportamiento salvo que así se documente explícitamente ahí.
"""
from __future__ import annotations

import asyncio  # noqa: F401  (reexportado: las pruebas y otros módulos lo alcanzan vía este módulo)
import html  # noqa: F401
import logging
from datetime import datetime  # noqa: F401
from zoneinfo import ZoneInfo  # noqa: F401

import httpx  # noqa: F401
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: F401
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,  # noqa: F401
    MessageHandler,
    filters,
)

from backend.api.bot import ligas as ligas_bot  # noqa: F401
from backend.api.bot.laplace_bot_admin import cmd_generarcodigos, cmd_gestionarusuario, cmd_listarcodigos
from backend.api.bot.laplace_bot_callbacks import (
    _procesar_job_en_fondo,  # noqa: F401
    callback_confirmar_picks,
    callback_dia,
    callback_liga,
    callback_predict,
    callback_voto,
)
from backend.api.bot.laplace_bot_comun import (  # noqa: F401
    MAX_PARTIDOS_HOY,
    TEXTO_AYUDA,
    TEXTO_BIENVENIDA,
    TZ_CHILE,
    _client,
    _es_admin,
    _eventos_no_iniciados,
    _primer_partido_del_dia,
    _texto_hoy,
    _usuario_desde_update,
)
from backend.api.bot.laplace_bot_usuario import (
    cmd_avisos,
    cmd_ayuda,
    cmd_desconocido,
    cmd_encuesta,
    cmd_equipos,
    cmd_favoritos,
    cmd_hoy,
    cmd_juegos,
    cmd_ligas,
    cmd_mi_id,
    cmd_misplanes,
    cmd_olvidame,
    cmd_privacidad,
    cmd_start,
    cmd_simular,
    cmd_stats,
    cmd_top,
    cmd_vincular,
)
from backend.api.core.config import settings
from backend.api.db import (  # noqa: F401
    admin_repo,
    analisis_repo,
    auditoria_repo,
    codigos_repo,
    jobs_repo,
    predicciones_usuario_repo,
    usuarios_repo,
)
from backend.api.db.session import SessionLocal  # noqa: F401
from backend.api.services import analisis_completo, gateway, telegram_client, top_picks  # noqa: F401
from backend.api.services.ligas import LIGAS  # noqa: F401
from backend.api.services.mensajes_analisis import pie_comunidad  # noqa: F401

log = logging.getLogger("laplace.bot")

# Menú que ve la persona al tocar «/» (H-012, 2026-11-11): antes lo definía BotFather a mano y tenía «recomendaciones», un comando que ningún manejador atendía (caía en «comando desconocido»).
# Ahora el menú sale del código y se registra al arrancar, así nunca se desincroniza. Los comandos de administración no van en el menú público.
COMANDOS_PUBLICOS = [
    ("start", "Bienvenida y tu plan"), ("juegos", "Elegir un partido y analizarlo"), ("hoy", "Partidos de hoy con pronóstico propio"), ("top", "Top Picks de hoy"),
    ("ligas", "Ligas con cobertura"), ("stats", "Rendimiento del bot"), ("encuesta", "Votar un partido"), ("favoritos", "Tus ligas favoritas"), ("equipos", "Tus equipos favoritos"),
    ("avisos", "Aviso diario de tus favoritos"), ("simular", "Simular una liga (planes pro y max)"), ("privacidad", "Consentimiento de tus datos"), ("olvidame", "Borrar todo lo tuyo"), ("misplanes", "Tu plan y su vigencia"),
    ("vincular", "Unir tu cuenta web o app"), ("mi_id", "Tu ID de Telegram"), ("ayuda", "Lista de comandos"),
]


async def registrar_menu(app: Application) -> None:
    """Publica el menú en Telegram; un fallo (sin red) solo se registra: el bot sigue funcionando."""
    try:
        from telegram import BotCommand

        await app.bot.set_my_commands([BotCommand(n, d) for n, d in COMANDOS_PUBLICOS])
    except Exception:  # noqa: BLE001
        log.warning("no se pudo registrar el menú de comandos en Telegram", exc_info=True)


def construir_app() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CommandHandler("mi_id", cmd_mi_id))
    app.add_handler(CommandHandler("juegos", cmd_juegos))
    app.add_handler(CommandHandler("ligas", cmd_ligas))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("encuesta", cmd_encuesta))
    app.add_handler(CallbackQueryHandler(callback_dia, pattern=r"^DAY_"))
    app.add_handler(CallbackQueryHandler(callback_liga, pattern=r"^LEAGUE_"))
    app.add_handler(CallbackQueryHandler(callback_predict, pattern=r"^(PREDICT|REFRESH)_"))
    app.add_handler(CallbackQueryHandler(callback_voto, pattern=r"^VOTE_"))
    app.add_handler(CallbackQueryHandler(callback_confirmar_picks, pattern=r"^(pub|nopub)_"))
    app.add_handler(CommandHandler("generarcodigos", cmd_generarcodigos))
    app.add_handler(CommandHandler("listarcodigos", cmd_listarcodigos))
    app.add_handler(CommandHandler("gestionarusuario", cmd_gestionarusuario))
    app.add_handler(CommandHandler("misplanes", cmd_misplanes))
    app.add_handler(CommandHandler("favoritos", cmd_favoritos))
    app.add_handler(CommandHandler("equipos", cmd_equipos))
    app.add_handler(CommandHandler("avisos", cmd_avisos))
    app.add_handler(CommandHandler("simular", cmd_simular))
    app.add_handler(CommandHandler("privacidad", cmd_privacidad))
    app.add_handler(CommandHandler("olvidame", cmd_olvidame))
    app.add_handler(CommandHandler("vincular", cmd_vincular))
    # Fallback de comando desconocido — debe ir AL FINAL: un MessageHandler(filters.COMMAND)
    # matchea cualquier `/algo`, así que si se registrara antes interceptaría los comandos
    # válidos de arriba.
    app.add_handler(MessageHandler(filters.COMMAND, cmd_desconocido))
    return app
