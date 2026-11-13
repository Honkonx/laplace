"""bot/laplace_bot_usuario.py — comandos que puede usar cualquier usuario del bot deportivo."""
from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.api.core.config import settings
from backend.api.db.session import SessionLocal
from backend.api.db import (
    analisis_repo,
    auditoria_repo,
    usuarios_repo,
)
from backend.api.services import gateway
from backend.api.services.ligas import LIGAS
from backend.api.services.mensajes_analisis import pie_comunidad

from backend.api.bot.laplace_bot_comun import (
    TEXTO_AYUDA,
    TEXTO_BIENVENIDA,
    TZ_CHILE,
    _client,
    _primer_partido_del_dia,
    _texto_hoy,
    _usuario_desde_update,
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
    ia_label = {"free": "Solo estadístico (Python)", "pro": "6 análisis IA/día", "max": "Ilimitado"}.get(u["plan"], "Solo estadístico (Python)")
    texto = TEXTO_BIENVENIDA.format(nombre=update.effective_user.first_name or "Usuario", plan=u["plan"].upper(), ia_label=ia_label, pie=pie_comunidad(settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL))
    await update.message.reply_html(texto)


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(TEXTO_AYUDA.format(pie=pie_comunidad(settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL)), disable_web_page_preview=True)


async def cmd_mi_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra sólo al solicitante su identificador para habilitar administración de forma verificable."""
    await update.message.reply_html(f"Tu ID de Telegram es <code>{update.effective_user.id}</code>.")


async def cmd_juegos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Partidos de Hoy", callback_data="DAY_TODAY"),
        InlineKeyboardButton("📅 Partidos de Mañana", callback_data="DAY_TOMORROW"),
    ]])
    await update.message.reply_html("⚽ <b>¿Qué partidos quieres ver?</b>\n\nSelecciona una fecha:", reply_markup=teclado)


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista los partidos de hoy (Chile) con cobertura propia; solo lee la caché, no gasta cuota."""
    from backend.api.services.pronosticables import listar_pronosticables

    fecha_bd = datetime.now(TZ_CHILE).strftime("%Y-%m-%d")
    with SessionLocal() as db:
        pronosticables = listar_pronosticables(db, fecha_bd)
    await update.message.reply_html(_texto_hoy(pronosticables))


async def cmd_ligas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el catálogo local de ligas con cobertura."""
    ligas = sorted({key.title() for key in LIGAS})
    texto = "⚽ <b>Ligas con cobertura en Laplace</b>\n\n" + "\n".join(f"• {liga}" for liga in ligas[:60])
    texto += f"\n\nTotal de entradas: <b>{len(ligas)}</b>\nUsa /juegos para elegir fecha y partido."
    await update.message.reply_html(texto)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        stats = analisis_repo.leer_stats(db)
        aciertos = analisis_repo.leer_stats_aciertos(db, dias=30)
    pick_final = aciertos.get("pick_final", {})
    predicciones = stats.get("predicciones", {})
    wr = pick_final.get("winrate")
    wr_txt = f"{wr}% ({pick_final.get('aciertos', 0)}/{pick_final.get('evaluados', 0)})" if wr is not None else "Sin datos"
    texto = (
        "📊 <b>Rendimiento del Bot — últimos 30 días</b>\n\n"
        f"🎯 Winrate: <b>{wr_txt}</b>\n\n"
        f"📈 Por confianza:\n  🟢 Alta: {predicciones.get('alta', 0)}\n  🟡 Media: {predicciones.get('media', 0)}\n  🔴 Baja: {predicciones.get('baja', 0)}\n\n"
        f"💡 Tu plan: <b>{u['plan'].upper()}</b>\n{pie_comunidad(settings.TELEGRAM_CANAL_ID, '')}"
    )
    await update.message.reply_html(texto)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime
    fecha = datetime.now().strftime("%Y%m%d")
    with SessionLocal() as db:
        picks = analisis_repo.leer_top_picks_app(db, "", fecha).get("canal", [])[:3]
    if not picks:
        await update.message.reply_html(
            "📅 No hay Top Picks disponibles para hoy.\n\nEl canal publica automáticamente a las 9AM Chile.\nUsa /juegos para analizar partidos ahora."
        )
        return
    medallas = ["🥇", "🥈", "🥉"]
    texto = "🏆 <b>Top Picks — Hoy</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, p in enumerate(picks):
        conf = f" | {p['confianza']}" if p.get("confianza") else ""
        score = f" ({p['score']}/100)" if p.get("score") is not None else ""
        texto += (
            f"{medallas[i]} <b>PICK {i+1}</b>\n⚽ {p['local']} vs {p['visitante']}\n"
            f"🏆 {p['liga']}{' · ' + p['hora'] + ' (Chile)' if p.get('hora') else ''}\n"
            f"✅ Pick: <b>{p['pick']}</b>{conf}{score}\n\n"
        )
    texto += f"━━━━━━━━━━━━━━━━━━━━━━\n{pie_comunidad(settings.TELEGRAM_CANAL_ID, '')}"
    await update.message.reply_html(texto, disable_web_page_preview=True)


async def cmd_encuesta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/encuesta` — primer paso real de la visión "Laplace-Agents le pregunta a los usuarios,
    tipo encuestas, y se puede auto-alimentar de eso" (pedido original del usuario). Esta ronda
    SOLO captura el voto — "aprender" de los votos (conectarlo al motor/`laplace-agents/`) queda
    fuera de alcance, ver `predicciones_usuario_repo`.

    Reusa la misma cascada de fixtures de `/juegos` (`gateway.obtener_fixtures_cascada`) en vez
    de reimplementar la obtención de partidos del día — solo cambia qué se hace con el primer
    partido `NS` encontrado (mostrar 3 botones de voto en vez de un menú de ligas)."""
    from datetime import datetime

    client = _client(context)
    fecha = datetime.now().strftime("%Y%m%d")
    with SessionLocal() as db:
        await _usuario_desde_update(db, update)
        stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, fecha)

    partido = _primer_partido_del_dia(stages)
    if partido is None:
        await update.message.reply_html(
            "⚠️ No hay partidos disponibles hoy para la encuesta.\n\nProbá más tarde o usá /juegos para ver otra fecha."
        )
        return

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Local", callback_data=f"VOTE_{partido['id']}_L"),
        InlineKeyboardButton("🤝 Empate", callback_data=f"VOTE_{partido['id']}_E"),
        InlineKeyboardButton("✈️ Visitante", callback_data=f"VOTE_{partido['id']}_V"),
    ]])
    await update.message.reply_html(
        f"🗳️ <b>¿Quién gana este partido?</b>\n\n⚽ {partido['local']} vs {partido['visitante']}\n🏆 {partido['liga']}\n\nVotá tu pronóstico:",
        reply_markup=teclado,
    )


async def cmd_misplanes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/misplanes` — plan actual + vencimiento, separado del mensaje de bienvenida de
    `/start`. Usa `usuarios_repo.obtener_usuario_app` (ya existente, misma función que usa el
    perfil de la app) — funciona igual para Telegram porque `device_id` guarda el `user_id`
    numérico en la misma columna."""
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        perfil = usuarios_repo.obtener_usuario_app(db, u["user_id"])

    if u["es_admin"]:
        texto = "💎 <b>Tu plan</b>\n\n👑 <b>ADMIN</b> — acceso ilimitado, sin vencimiento."
        await update.message.reply_html(texto)
        return

    vencimiento = (
        f"\n📅 Vence: <b>{perfil['activo_hasta']}</b>" if perfil.get("activo_hasta")
        else "\n📅 Sin vencimiento (plan free)"
    )
    texto = (
        "💎 <b>Tu plan</b>\n\n"
        f"📦 Plan actual: <b>{perfil['plan'].upper()}</b>{vencimiento}\n\n"
        f"🤖 IA disponible/día: {perfil['limite_ia_diario']}\n\n"
        "💡 ¿Quieres más días? Consigue un código en el canal y actívalo desde la app."
    )
    await update.message.reply_html(texto)


async def cmd_favoritos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/favoritos [agregar|quitar] <liga>` — hasta 3 ligas favoritas guardadas por usuario,
    para no tener que navegar Hoy→Liga→Partido desde cero cada vez. Sin argumentos, lista lo
    guardado."""
    args = context.args or []
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)

        if not args:
            favoritos = usuarios_repo.listar_favoritos_ligas(db, u["user_id"])
            if not favoritos:
                await update.message.reply_html(
                    "⭐ <b>Ligas favoritas</b>\n\nNo tienes ninguna guardada todavía.\n\n"
                    "Usa <code>/favoritos agregar &lt;liga&gt;</code> (hasta 3)."
                )
                return
            lista = "\n".join(f"• {l}" for l in favoritos)
            await update.message.reply_html(
                f"⭐ <b>Ligas favoritas</b>\n\n{lista}\n\n"
                "Quita una con <code>/favoritos quitar &lt;liga&gt;</code>."
            )
            return

        accion = args[0].lower()
        liga = " ".join(args[1:]).strip()
        if accion in ("agregar", "add") and liga:
            resultado = usuarios_repo.agregar_favorito_liga(db, u["user_id"], liga)
        elif accion in ("quitar", "eliminar", "remove") and liga:
            resultado = usuarios_repo.quitar_favorito_liga(db, u["user_id"], liga)
        else:
            await update.message.reply_html(
                "Uso:\n<code>/favoritos</code> — ver tus favoritos\n"
                "<code>/favoritos agregar &lt;liga&gt;</code>\n"
                "<code>/favoritos quitar &lt;liga&gt;</code>"
            )
            return

    prefijo = "✅" if resultado.get("agregado") or resultado.get("quitado") else "⚠️"
    await update.message.reply_html(f"{prefijo} {resultado['mensaje']}")


async def cmd_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback para cualquier mensaje que empiece con `/` y no matchee ningún comando
    registrado (typo de comando) — antes quedaba en silencio total, sin ningún handler que
    respondiera. Debe registrarse DESPUÉS de todos los `CommandHandler` en `construir_app` para
    no interceptar comandos válidos."""
    await update.message.reply_html("🤔 No reconozco ese comando.\n\nProbá /ayuda para ver la lista completa.")


async def cmd_vincular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/vincular <usuario> <contraseña>` — vincula la cuenta creada en la Web o en la App
    Android con el usuario de Telegram, sincronizando el plan activo (`PRO`/`MAX`) y su
    fecha de vencimiento entre ambas superficies."""
    from backend.api.services.auth_password import verificar_password

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_html(
            "🔗 <b>Vincular cuenta Web / App</b>\n\n"
            "Comparte tu plan activo entre la Web/App y Telegram usando:\n"
            "<code>/vincular &lt;usuario&gt; &lt;contraseña&gt;</code>"
        )
        return

    username = args[0].strip()
    password = " ".join(args[1:])
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        cuenta = usuarios_repo.obtener_usuario_por_username(db, username)
        if cuenta is None or not cuenta.password_hash or not verificar_password(password, cuenta.password_hash):
            auditoria_repo.registrar_intento_login_fallido(db, username)
            await update.message.reply_html("⚠️ Usuario o contraseña incorrectos.")
            return
        resultado = usuarios_repo.vincular_cuenta_telegram(db, u["user_id"], cuenta)

    await update.message.reply_html(f"✅ {resultado['mensaje']}")


async def cmd_privacidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/privacidad [aceptar|revocar]` — consentimiento para guardar equipos favoritos e historial (MB-33). Sin argumento muestra el estado."""
    from backend.api.db import bot_memoria_repo as memoria

    arg = (context.args[0].lower() if context.args else "")
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        if arg == "aceptar":
            memoria.aceptar(db, u["user_id"])
            texto = "✅ Listo. Ya puedes guardar equipos con /equipos agregar <equipo>."
        elif arg == "revocar":
            memoria.revocar(db, u["user_id"])
            texto = "Consentimiento retirado; borré tu historial y tus equipos favoritos."
        else:
            estado = "aceptado" if memoria.tiene_consentimiento(db, u["user_id"]) else "no aceptado"
            texto = f"{memoria.TEXTO_CONSENTIMIENTO}\n\nEstado: <b>{estado}</b>"
    await update.message.reply_html(texto)


async def cmd_equipos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/equipos [agregar|quitar] <equipo>` — hasta 5 equipos favoritos (solo ordenan tus listas; requiere /privacidad aceptar)."""
    from backend.api.db import bot_memoria_repo as memoria

    args = context.args or []
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        if len(args) >= 2 and args[0].lower() in ("agregar", "quitar"):
            nombre = " ".join(args[1:])
            r = (memoria.agregar_equipo if args[0].lower() == "agregar" else memoria.quitar_equipo)(db, u["user_id"], nombre)
            texto = r["mensaje"]
        else:
            favoritos = memoria.equipos_favoritos(db, u["user_id"])
            texto = ("⭐ <b>Equipos favoritos</b>\n" + "\n".join(f"• {e}" for e in favoritos)) if favoritos else "No tienes equipos guardados. /equipos agregar <equipo>"
    await update.message.reply_html(texto)


async def cmd_olvidame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/olvidame confirmo` — borra todo lo tuyo en el bot (favoritos, historial, consentimiento, votos)."""
    from backend.api.db import bot_memoria_repo as memoria

    if not context.args or context.args[0].lower() != "confirmo":
        await update.message.reply_html("Esto borra tus favoritos, historial, consentimiento y votos del bot. Para confirmar: <code>/olvidame confirmo</code>")
        return
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        borrado = memoria.olvidar(db, u["user_id"])
    await update.message.reply_html(f"🗑️ Listo: borré {sum(borrado.values())} registro(s) tuyos del bot.")


async def cmd_avisos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/avisos [on|off]` — aviso diario cuando juega alguno de tus favoritos (requiere /privacidad aceptar y un favorito)."""
    from backend.api.db import bot_memoria_repo as memoria

    arg = (context.args[0].lower() if context.args else "")
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        if arg in ("on", "off"):
            texto = memoria.configurar_avisos(db, u["user_id"], arg == "on")["mensaje"]
        else:
            fila = db.get(memoria.BotPreferencias, str(u["user_id"]))
            texto = "Avisos: <b>" + ("activos" if fila is not None and fila.avisos else "apagados") + "</b>. /avisos on · /avisos off"
    await update.message.reply_html(texto)


async def cmd_simular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/simular [liga]` — simulador de liga (campeón, copa, descenso): solo planes pro/max y administradores. Sin liga lista las disponibles."""
    import asyncio

    from backend.api.services import simulador_propio

    arg = " ".join(context.args or []).strip().lower()
    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        acceso = usuarios_repo.acceso_simulador(db, u["user_id"])
    if not acceso["permitido"]:
        await update.message.reply_html(f"🔒 {usuarios_repo.MENSAJE_SIMULADOR}\nTu plan: <b>{(acceso['plan'] or 'free').upper()}</b>. /misplanes")
        return
    if not arg:
        ligas = await asyncio.to_thread(simulador_propio.ligas_disponibles)
        await update.message.reply_html("🏆 <b>Simulador de liga</b>\nUsa <code>/simular premier</code>. Ligas: " + ", ".join(x["slug"] for x in ligas if x["disponible"]))
        return
    slug = arg if arg in simulador_propio.SLUGS else simulador_propio.liga_de_texto(simulador_propio._normalizar(arg))
    if slug is None:
        await update.message.reply_html("No conozco esa liga. Usa /simular para ver las disponibles.")
        return
    r = await asyncio.to_thread(simulador_propio.simular, slug)
    await update.message.reply_html("🏆 " + simulador_propio.texto_resumen(r).replace("&", "&amp;").replace("<", "&lt;"))
