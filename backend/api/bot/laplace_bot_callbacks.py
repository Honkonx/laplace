"""bot/laplace_bot_callbacks.py — botones inline (fecha, liga, partido, voto, confirmación de picks)."""
from __future__ import annotations

import asyncio
import logging

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.api.bot import ligas as ligas_bot
from backend.api.db.session import SessionLocal
from backend.api.db import (
    analisis_repo,
    jobs_repo,
    predicciones_usuario_repo,
    usuarios_repo,
)
from backend.api.db import bot_memoria_repo as memoria
from backend.api.services import analisis_completo, gateway, telegram_client, top_picks
from backend.api.services.fechas_bd import FechaBdInvalida

from backend.api.bot.laplace_bot_comun import _client, _usuario_desde_update
from backend.api.services import ligas_ident


def _favoritos_del_usuario(update: Update) -> tuple[list[str], list[str]]:
    """(ligas, equipos) favoritos; vacío si no hay consentimiento. Solo se usan para ORDENAR: ninguna cifra depende de ellos."""
    try:
        uid = str(update.effective_user.id)
        with SessionLocal() as db:
            if not memoria.tiene_consentimiento(db, uid):
                return [], []
            return usuarios_repo.listar_favoritos_ligas(db, uid), memoria.equipos_favoritos(db, uid)
    except Exception:  # noqa: BLE001 — personalizar es accesorio: ante cualquier falla se muestra la lista normal
        return [], []


def _ordenar_ligas_favoritas(update: Update, ligas: list[dict]) -> list[dict]:
    ligas_f, _equipos = _favoritos_del_usuario(update)
    return memoria.ordenar_por_favoritos(ligas, nombre_liga=lambda l: l.get("nombre", ""), ligas_favoritas=ligas_f)


def _ordenar_partidos_favoritos(update: Update, partidos: list[dict]) -> list[dict]:
    _ligas, equipos = _favoritos_del_usuario(update)
    return memoria.ordenar_por_favoritos(partidos, nombres_equipo=lambda p: (p["local"], p["visitante"]), equipos=equipos)

log = logging.getLogger("laplace.bot")


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
    ligas = _ordenar_ligas_favoritas(update, ligas)
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
    try:
        with SessionLocal() as db:
            stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, fecha)
    except FechaBdInvalida:  # un botón viejo o adulterado: en Telegram una excepción sin manejar deja a la persona sin respuesta
        await query.message.reply_html("⚠️ Ese botón ya no es válido.\n\nVuelve al menú con /juegos.")
        return

    partidos = []
    liga_nombre = liga_slug
    for stage in stages:
        if ligas_bot.slug_de_stage(stage) != liga_slug:  # nombre Y país: «Premier League» de Inglaterra no trae los partidos de la de Egipto
            continue
        nombre = (stage.get("Snm") or stage.get("CompN") or "Liga").strip()
        for ev in stage.get("Events", []):
            if ev.get("Eps") != "NS":
                continue
            liga_nombre = ligas_ident.nombre_visible(nombre, stage.get("Cnm"))
            local = (ev.get("T1") or [{}])[0].get("Nm", "Local")
            visitante = (ev.get("T2") or [{}])[0].get("Nm", "Visitante")
            partidos.append({"id": ev.get("Eid"), "local": local, "visitante": visitante, "cb": f"PREDICT_{fecha}_{ev.get('Eid')}",
                             "cubierto": ligas_bot._evento_cubierto({"Snm": nombre, "Cnm": stage.get("Cnm")}, ev)})
    partidos.sort(key=lambda p: not p["cubierto"])  # los que el bot sabe pronosticar, primero
    partidos = _ordenar_partidos_favoritos(update, partidos)

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
        limite = usuarios_repo.verificar_limite(db, u["user_id"], u["plan"])
        if not limite["puede"]:
            await query.message.reply_html(
                f"⚠️ <b>Límite IA diario alcanzado</b>\n\nHoy ya usaste {limite['usados']}/{limite['limite']} análisis IA.\n\n🔄 El límite se reinicia a medianoche."
            )
            return

        if cache.get("job_en_vuelo"):
            # otra persona ya pidió este partido: se anota la espera y el resultado se le envía cuando esté listo (H-011)
            espera = jobs_repo.registrar_espera(db, match_id, fecha, chat_id, u["user_id"], u["plan"])
            if espera is None:
                await query.message.reply_html("⏳ <b>Análisis en progreso</b>\n\nMucha gente espera este partido. Vuelve a tocar el botón en un minuto.")
            elif espera["ya_esperando"]:
                await query.message.reply_html("⏳ <b>Análisis en progreso</b>\n\nYa lo estás esperando: te lo envío aquí apenas esté listo.")
            else:
                await query.message.reply_html("⏳ <b>Análisis en progreso</b>\n\nYa hay un análisis de este partido en curso. Te lo envío aquí apenas esté listo.")
            return
        try:  # la memoria es accesorio: si falla (p. ej. tabla sin migrar) el análisis sigue
            memoria.registrar_consulta(db, u["user_id"], match_id, fecha)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.warning("no se pudo registrar la consulta en la memoria del bot", exc_info=True)
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
