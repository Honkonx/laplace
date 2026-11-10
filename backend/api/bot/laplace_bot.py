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

import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from backend.api.bot import ligas as ligas_bot
from backend.api.core.config import settings
from backend.api.db.session import SessionLocal
from backend.api.db import (
    admin_repo,
    analisis_repo,
    auditoria_repo,
    codigos_repo,
    jobs_repo,
    predicciones_usuario_repo,
    usuarios_repo,
)
from backend.api.services import analisis_completo, gateway, telegram_client, top_picks
from backend.api.services.ligas import LIGAS
from backend.api.services.mensajes_analisis import pie_comunidad

log = logging.getLogger("laplace.bot")

TEXTO_BIENVENIDA = (
    "👋 <b>¡Hola, {nombre}!</b>\n\n"
    "⚽ <b>Laplace FutBOT</b> — Predicciones deportivas con IA\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📋 <b>Comandos:</b>\n\n"
    "/juegos — Ver partidos de hoy o mañana\n"
    "/top — Los 3 mejores picks del día\n"
    "/encuesta — Votá quién gana un partido\n"
    "/stats — Rendimiento del bot\n"
    "/ayuda — Ayuda completa\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "💡 <b>Tu plan:</b> {plan}\n"
    "📊 <b>IA:</b> {ia_label}\n\n"
    "{pie}"
)

TEXTO_AYUDA = (
    "📋 <b>Comandos disponibles</b>\n\n"
    "/juegos — Ver partidos (Hoy / Mañana)\n"
    "/hoy — Partidos de hoy que sé pronosticar\n"
    "/top — Los 3 mejores picks del día\n"
    "/encuesta — Votá quién gana un partido de hoy\n"
    "/stats — Rendimiento del bot\n"
    "/misplanes — Tu plan actual y vencimiento\n"
    "/vincular — Vincular cuenta Web/App (plan compartido)\n"
    "/favoritos — Tus ligas favoritas (hasta 3)\n"
    "/ayuda — Este mensaje\n"
    "/start — Bienvenida\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚽ <b>Cómo pedir un análisis:</b>\n"
    "1. /juegos → elige 📅 Hoy o Mañana\n"
    "2. Selecciona una 🏆 Liga\n"
    "3. Elige un partido\n"
    "4. Recibe el análisis\n\n"
    "{pie}"
)


def _client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.application.bot_data["http_client"]


async def _usuario_desde_update(db, update: Update) -> dict:
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    usuarios_repo.registrar_usuario_telegram(db, user_id=str(user.id), chat_id=chat_id, first_name=user.first_name or "Usuario")
    acceso = usuarios_repo.verificar_acceso(db, user_id=str(user.id))
    return {"user_id": str(user.id), "chat_id": chat_id, "plan": acceso.get("plan") or "free", "es_admin": acceso.get("es_admin", False)}


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


MAX_PARTIDOS_HOY = 20
TZ_CHILE = ZoneInfo("America/Santiago")


def _texto_hoy(pronosticables: dict) -> str:
    partidos = pronosticables.get("partidos", [])
    if not partidos:
        return ("Hoy no hay partidos que pueda pronosticar con datos propios; igual puedes consultar cualquiera "
                "con /juegos: si hay cuotas se analiza.")
    por_liga: dict[str, list[dict]] = {}
    for p in partidos[:MAX_PARTIDOS_HOY]:
        por_liga.setdefault(p.get("liga") or "Otras ligas", []).append(p)
    lineas = ["📅 <b>Partidos de hoy que sé pronosticar</b>"]
    for liga, items in por_liga.items():
        lineas.append(f"\n🏆 <b>{html.escape(liga)}</b>")
        for p in sorted(items, key=lambda x: x.get("hora_chile") or ""):
            marca = "~" if p.get("cobertura") != "completa" else ""
            lineas.append(f"{marca}{html.escape(p.get('hora_chile') or '--:--')} {html.escape(p['local'] or '')} vs {html.escape(p['visitante'] or '')}")
    lineas.append("\n~ cobertura parcial (un equipo sin historial). Elige uno en /juegos para el análisis.")
    return "\n".join(lineas)


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


def _eventos_no_iniciados(stages: list[dict]):
    """Itera `(liga_nombre, evento)` de partidos `NS` (no iniciados) en `stages` — extraído del
    loop que ya usaba `callback_liga` para no reimplementarlo en `cmd_encuesta` (que también
    necesita recorrer los partidos del día, solo que sin filtrar por liga)."""
    for stage in stages:
        liga_nombre = (stage.get("Snm") or stage.get("CompN") or "Liga").strip()
        for ev in stage.get("Events", []):
            if ev.get("Eps") != "NS":
                continue
            yield liga_nombre, ev


def _primer_partido_del_dia(stages: list[dict]) -> dict | None:
    """Primer partido `NS` (no iniciado) encontrado en `stages`, para `/encuesta` — a diferencia
    de `callback_liga` no filtra por liga, solo toma el primero que aparezca (alcance acotado de
    esta ronda: un partido por encuesta, no una lista para elegir)."""
    for liga_nombre, ev in _eventos_no_iniciados(stages):
        local = (ev.get("T1") or [{}])[0].get("Nm", "Local")
        visitante = (ev.get("T2") or [{}])[0].get("Nm", "Visitante")
        return {"id": ev.get("Eid"), "local": local, "visitante": visitante, "liga": liga_nombre}
    return None


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


async def callback_voto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback de los botones Local/Empate/Visitante de `/encuesta` — guarda el voto real del
    usuario que tocó el botón (`update.effective_user.id`) en `predicciones_usuario`. El
    "¿por qué?" en texto libre queda documentado como próximo paso, no implementado en esta
    ronda (ver docstring de `predicciones_usuario_repo.guardar_razon`)."""
    query = update.callback_query
    client = _client(context)

    raw = query.data.removeprefix("VOTE_")
    match_id, _sep, codigo = raw.rpartition("_")
    pick = {"L": "local", "E": "empate", "V": "visitante"}.get(codigo)
    if not match_id or pick is None:
        await telegram_client.responder_callback(client, query.id, "⚠️ Voto inválido.", show_alert=True)
        return

    with SessionLocal() as db:
        resultado = predicciones_usuario_repo.registrar_voto(
            db, match_id=match_id, telegram_user_id=str(update.effective_user.id), pick=pick,
        )

    if not resultado.get("ok"):
        await telegram_client.responder_callback(client, query.id, "⚠️ No se pudo registrar el voto.", show_alert=True)
        return

    await telegram_client.responder_callback(client, query.id, "✅ ¡Voto registrado!")
    etiqueta = {"local": "🏠 Local", "empate": "🤝 Empate", "visitante": "✈️ Visitante"}[pick]
    verbo = "actualizado" if resultado.get("voto_actualizado") else "registrado"
    await query.message.reply_html(f"✅ Voto {verbo}: <b>{etiqueta}</b>\n\n¡Gracias por participar en la encuesta!")


async def callback_dia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from datetime import datetime, timedelta
    query = update.callback_query
    client = _client(context)
    await telegram_client.responder_callback(client, query.id, "📅 Cargando partidos...")

    ahora = datetime.now()
    fecha_dt = ahora if query.data == "DAY_TODAY" else ahora + timedelta(days=1)
    fecha = fecha_dt.strftime("%Y%m%d")
    etiqueta = "Hoy" if query.data == "DAY_TODAY" else "Mañana"

    with SessionLocal() as db:
        stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, fecha)
    ligas = ligas_bot.ligas_con_partidos(stages)
    if not ligas:
        await query.message.reply_html(f"⚠️ No hay ligas con partidos para {etiqueta.lower()}.\n\nPrueba con otra fecha o vuelve más tarde.")
        return
    botones = [[InlineKeyboardButton(f"🏆 {l['nombre']} ({l['partidos']})" + (" ✅" if l.get("cubiertos") else ""), callback_data=f"LEAGUE_{fecha}_{l['slug']}")] for l in ligas]
    await query.message.reply_html(f"⚽ <b>Ligas con partidos — {etiqueta}</b>\n\nSelecciona una liga:", reply_markup=InlineKeyboardMarkup(botones))


async def callback_liga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    client = _client(context)
    await telegram_client.responder_callback(client, query.id, "⚽ Cargando partidos...")

    raw = query.data.removeprefix("LEAGUE_")
    fecha, liga_slug = raw[:8], raw[9:]
    with SessionLocal() as db:
        stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, fecha)

    partidos = []
    liga_nombre = liga_slug
    for nombre, ev in _eventos_no_iniciados(stages):
        if ligas_bot.slug_liga(nombre) != liga_slug:
            continue
        liga_nombre = nombre
        local = (ev.get("T1") or [{}])[0].get("Nm", "Local")
        visitante = (ev.get("T2") or [{}])[0].get("Nm", "Visitante")
        partidos.append({"id": ev.get("Eid"), "local": local, "visitante": visitante, "cb": f"PREDICT_{fecha}_{ev.get('Eid')}",
                         "cubierto": ligas_bot._evento_cubierto({"Snm": nombre}, ev)})
    partidos.sort(key=lambda p: not p["cubierto"])  # los que el bot sabe pronosticar, primero

    if not partidos:
        await query.message.reply_html(f"⚠️ No se encontraron partidos para <b>{liga_nombre}</b>.\n\nVuelve al menú con /juegos.")
        return
    botones = [[InlineKeyboardButton(f"⚽ {p['local']} vs {p['visitante']}" + (" ✅" if p["cubierto"] else ""), callback_data=p["cb"])] for p in partidos[:12]]
    await query.message.reply_html(f"🏆 <b>{liga_nombre}</b>\n\nSelecciona un partido:", reply_markup=InlineKeyboardMarkup(botones))


async def callback_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    client = _client(context)
    forzar_recalculo = query.data.startswith("REFRESH_")
    raw = query.data.removeprefix("REFRESH_" if forzar_recalculo else "PREDICT_")
    fecha, match_id = raw[:8], raw[9:]
    chat_id = str(update.effective_chat.id)

    with SessionLocal() as db:
        u = await _usuario_desde_update(db, update)
        await telegram_client.responder_callback(client, query.id, "🔄 Verificando...")

        cache = analisis_repo.verificar_consenso_cache(db, match_id)
        if cache.get("cache_consenso_hit") and not forzar_recalculo:
            teclado = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Recalcular", callback_data=f"REFRESH_{fecha}_{match_id}"),
                InlineKeyboardButton("📅 Partidos de Hoy", callback_data="DAY_TODAY"),
            ]])
            await query.message.reply_html(cache.get("texto_consenso") or "⚡ Análisis en caché disponible.", reply_markup=teclado)
            return
        if cache.get("job_en_vuelo"):
            await query.message.reply_html("⏳ <b>Análisis en progreso</b>\n\nYa hay un análisis en curso para este partido.")
            return

        limite = usuarios_repo.verificar_limite(db, u["user_id"], u["plan"])
        if not limite["puede"]:
            await query.message.reply_html(
                f"⚠️ <b>Límite IA diario alcanzado</b>\n\nHoy ya usaste {limite['usados']}/{limite['limite']} análisis IA.\n\n🔄 El límite se reinicia a medianoche."
            )
            return

        job_id = jobs_repo.crear_job(db, match_id=match_id, fecha=fecha, chat_id=chat_id, user_id=u["user_id"], plan=u["plan"])["job_id"]

    await query.message.reply_html(
        "🧠 <b>Analizando partido...</b>\n\n⏳ Esto tomará unos segundos.\n"
        "📊 Motor: Poisson · Dixon-Coles · xG · H2H · Odds · Forma" + ("\n🤖 + Análisis IA (Claude)" if u["plan"] != "free" else "\n📈 Análisis estadístico Python")
    )
    asyncio.create_task(_procesar_job_en_fondo(client, job_id))


async def _procesar_job_en_fondo(client: httpx.AsyncClient, job_id: str) -> None:
    with SessionLocal() as db:
        await analisis_completo.procesar_job(db, client, job_id)


async def callback_confirmar_picks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botones `pub_{fecha}`/`nopub_{fecha}` del aviso de confianza baja de WF-D (ver
    `main.py::_job_top_picks`) — solo el admin recibe ese mensaje, no hace falta chequear
    permisos acá de nuevo."""
    query = update.callback_query
    client = _client(context)
    await telegram_client.responder_callback(client, query.id)

    aprobado = query.data.startswith("pub_")
    fecha_db = query.data.split("_", 1)[1]
    with SessionLocal() as db:
        resultado = top_picks.sacar_pendiente_confirmacion(fecha_db)
        if resultado is None:
            await query.message.reply_html("⚠️ Ya no hay picks pendientes de confirmación para esa fecha (expiraron o el proceso se reinició).")
            return
        mensaje = await top_picks.confirmar_publicacion(db, client, resultado, aprobado)
    await query.message.reply_html(mensaje)


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


def _es_admin(update: Update) -> bool:
    return str(update.effective_user.id) in settings.admin_ids


async def cmd_generarcodigos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/generarcodigos <cantidad> <plan> <dias>` — ej. `/generarcodigos 5 pro 30`. Solo admin
    (`SPORTS_ADMIN_IDS`) — herramienta de gestión del negocio (vender códigos de acceso), sin
    equivalente en ningún workflow n8n."""
    if not _es_admin(update):
        await update.message.reply_html("⛔ No autorizado.")
        return
    args = context.args or []
    if len(args) != 3:
        await update.message.reply_html("Uso: /generarcodigos &lt;cantidad&gt; &lt;pro|max&gt; &lt;dias&gt;")
        return
    cantidad_raw, plan, dias_raw = args
    try:
        cantidad, dias = int(cantidad_raw), int(dias_raw)
    except ValueError:
        await update.message.reply_html("cantidad y dias deben ser números.")
        return

    with SessionLocal() as db:
        resultado = codigos_repo.generar_codigos_lote(db, plan, dias, cantidad)
        if "error" not in resultado:
            # Auditoría: quién generó qué (hallazgo real de la auditoría 2026-09-09 — este
            # comando no dejaba ningún rastro más allá de logs de proceso).
            auditoria_repo.registrar_accion_admin(
                db, actor_admin_id=str(update.effective_user.id), accion="generar_codigos",
                detalle=f"{resultado['generados']} codigos {plan.lower()} x{dias}d",
            )
    if "error" in resultado:
        await update.message.reply_html(f"⚠️ {resultado['error']}")
        return
    lista = "\n".join(f"<code>{c}</code>" for c in resultado["codigos"])
    await update.message.reply_html(
        f"✅ {resultado['generados']} códigos {plan.upper()} ({dias} días) generados:\n\n{lista}"
    )


async def cmd_listarcodigos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/listarcodigos [disponibles|usados|todos]` (default: disponibles). Solo admin."""
    if not _es_admin(update):
        await update.message.reply_html("⛔ No autorizado.")
        return
    filtro = (context.args or ["disponibles"])[0]
    with SessionLocal() as db:
        resultado = codigos_repo.listar_codigos(db, filtro)
    if resultado["total"] == 0:
        await update.message.reply_html(f"No hay códigos ({filtro}).")
        return
    lineas = [f"<code>{c['codigo']}</code> — {c['plan'].upper()} {c['dias']}d" for c in resultado["codigos"][:30]]
    texto = f"📋 <b>Códigos {filtro}</b> ({resultado['total']} total, mostrando {len(lineas)}):\n\n" + "\n".join(lineas)
    await update.message.reply_html(texto)


async def cmd_gestionarusuario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/gestionarusuario <device_id> <activar|desactivar|plan:<nuevo_plan>|rol:<usuario|admin|agente>>`.
    Solo admin. `rol:` — agregado 2026-09-10, separado de `plan:` (ver models/usuarios.py §v7)
    — único punto de escritura real hoy para promover a alguien a `rol=admin`, dado que el
    dashboard FastAPI (`routers/admin.py`) es v1 solo-lectura por decisión ya tomada."""
    if not _es_admin(update):
        await update.message.reply_html("⛔ No autorizado.")
        return
    args = context.args or []
    if len(args) != 2:
        await update.message.reply_html(
            "Uso: /gestionarusuario &lt;device_id&gt; &lt;activar|desactivar|plan:NUEVO_PLAN|rol:usuario|admin|agente&gt;"
        )
        return
    device_id, accion_raw = args
    actor_admin_id = str(update.effective_user.id)

    if accion_raw.startswith("rol:"):
        rol = accion_raw.split(":", 1)[1]
        with SessionLocal() as db:
            resultado = usuarios_repo.asignar_rol(db, device_id, rol, actor_admin_id=actor_admin_id)
        if "error" in resultado:
            await update.message.reply_html(f"⚠️ {resultado['error']}")
            return
        await update.message.reply_html(f"✅ {resultado}")
        return

    if accion_raw.startswith("plan:"):
        accion, plan = "cambiar_plan", accion_raw.split(":", 1)[1]
    else:
        accion, plan = accion_raw, "free"

    with SessionLocal() as db:
        resultado = admin_repo.gestionar_usuario(db, accion, device_id, plan, actor_admin_id=actor_admin_id)
    if "error" in resultado:
        await update.message.reply_html(f"⚠️ {resultado['error']}")
        return
    await update.message.reply_html(f"✅ {resultado}")


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
    app.add_handler(CommandHandler("vincular", cmd_vincular))
    # Fallback de comando desconocido — debe ir AL FINAL: un MessageHandler(filters.COMMAND)
    # matchea cualquier `/algo`, así que si se registrara antes interceptaría los comandos
    # válidos de arriba.
    app.add_handler(MessageHandler(filters.COMMAND, cmd_desconocido))
    return app
