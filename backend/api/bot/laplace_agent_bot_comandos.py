"""bot/laplace_agent_bot_comandos.py — comandos del bot del agente para todos los usuarios."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from backend.api.core.config import settings
from backend.api.db.session import SessionLocal
from backend.api.models.agent_runtime import AgentMemory, AgentTask
from backend.api.services import agent_privacidad, agent_sesiones
from backend.api.services.agent_guard import (
    LimiteExcedido,
)

log = logging.getLogger("laplace.agent_telegram")

from backend.api.bot import laplace_agent_bot_nucleo as nucleo
from backend.api.bot.laplace_agent_bot_acceso import _es_admin, protegido
from backend.api.bot.laplace_agent_bot_formato import (
    AVISO_ESTIMACION,
    COMANDOS_ADMIN,
    COMANDOS_PUBLICOS,
    _enviar,
    _es_token_fecha,
    _fecha_desde,
    _coincide,
    _separar_equipos,
    formatear_partidos,
    formatear_prediccion,
)


@protegido
async def _responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (update.effective_message.text or "").strip()
    if not texto:
        await update.effective_message.reply_text("Escribe una consulta para el agente. Usa /ayuda para ver qué puedo hacer.")
        return
    politica = (settings.AGENT_TEXTO_LIBRE_IA or "admin").strip().lower()
    usar_ia = bool(settings.AGENT_IA_ACTIVA) and (politica == "todos" or (politica == "admin" and _es_admin(update)))
    await nucleo._consultar_agente(update, texto[:4000], usar_ia)


@protegido
async def cmd_simular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/simular [liga]` — simulador de liga (solo planes pro/max y administradores): pasa por el mismo agente y el mismo control de acceso que escribir «simula la premier»."""
    liga = " ".join(context.args or []).strip()
    await nucleo._consultar_agente(update, f"simula la {liga}" if liga else "simula la liga", False)


@protegido
async def cmd_nuevo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usuario = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        agent_sesiones.nueva_sesion(db, usuario, "telegram_agent")
    await update.effective_message.reply_text("Listo: empezamos una conversación nueva. La anterior queda guardada; con /sesiones la ves y con /retomar la sigues.")


@protegido
async def cmd_incognito(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/incognito [on|off]` — mientras esté activo no guardo tus mensajes ni memoria (al reiniciar el bot vuelve a lo normal)."""
    usuario = f"telegram:{update.effective_user.id}"
    arg = (context.args[0].lower() if context.args else "")
    if arg in ("off", "no", "apagar"):
        agent_privacidad.desactivar_incognito(usuario)
        await update.effective_message.reply_text("Modo incógnito apagado: vuelvo a guardar tus conversaciones.")
    elif arg in ("on", "si", "sí", "activar", ""):
        agent_privacidad.activar_incognito(usuario)
        await update.effective_message.reply_text("Modo incógnito activo: no guardo mensajes ni memoria. /incognito off para salir.")
    else:  # H-024: un argumento que no se entiende antes recibía silencio
        await update.effective_message.reply_text("Usa /incognito on para no guardar esta conversación o /incognito off para volver a guardarla.")


@protegido
async def cmd_olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/olvidar confirmo` — borra todas tus conversaciones y memorias del agente."""
    if not context.args or context.args[0].lower() != "confirmo":
        await update.effective_message.reply_text("Esto borra tus conversaciones y memorias del agente. Para confirmar: /olvidar confirmo")
        return
    usuario = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        hecho = agent_privacidad.olvidar_usuario(db, usuario)
    await update.effective_message.reply_text(f"Listo: borré {sum(hecho.values())} registro(s) tuyos del agente.")


@protegido
async def cmd_sesiones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usuario = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        sesiones = agent_sesiones.listar_sesiones(db, usuario, "telegram_agent")
    if not sesiones:
        await update.effective_message.reply_text("Todavía no tienes conversaciones guardadas.")
        return
    lineas = [f"{i}. {s['titulo'][:50]} ({s['mensajes']} mensajes, {s['actualizado_en'][:10]})" for i, s in enumerate(sesiones, 1)]
    await update.effective_message.reply_text("Tus conversaciones:\n" + "\n".join(lineas) + "\nPara seguir una: /retomar <número>")


@protegido
async def cmd_retomar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usuario = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        sesiones = agent_sesiones.listar_sesiones(db, usuario, "telegram_agent")
        elegida = None
        if context.args and context.args[0].isdigit() and 1 <= int(context.args[0]) <= len(sesiones):
            elegida = sesiones[int(context.args[0]) - 1]["id"]
            agent_sesiones.activar_sesion(db, usuario, elegida)
        sesion_ref = elegida or agent_sesiones.ultima_sesion(db, usuario, "telegram_agent") or ""
        texto = agent_sesiones.resumen_para_retomar(db, usuario, sesion_ref)
    await update.effective_message.reply_text(texto)


@protegido
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Hola, soy Laplace, un agente de pronósticos de fútbol. Puedo mostrarte partidos, estimar probabilidades "
        "con modelos estadísticos medidos y explicarte cómo leerlas.\n\n"
        "Prueba: /partidos · /predecir River vs Boca · /top · /ayuda\n\n"
        "No soy una casa de apuestas ni acepto dinero: solo informo estimaciones."
    )


@protegido
async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lineas = ["Qué puedo hacer:"] + [f"/{nombre} — {descripcion}" for nombre, descripcion in COMANDOS_PUBLICOS]
    lineas.append("\nTambién puedes escribirme en lenguaje natural dentro del alcance de Laplace.")
    if _es_admin(update):
        lineas.append("\nAdministración:")
        lineas += [f"/{nombre} — {descripcion}" for nombre, descripcion in COMANDOS_ADMIN]
    await _enviar(update, "\n".join(lineas))


@protegido
async def cmd_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = " ".join(context.args).strip()
    if not texto:
        await update.effective_message.reply_text("Uso: /ia <consulta dentro del alcance de Laplace>")
        return
    await nucleo._consultar_agente(update, texto[:4000], True)


@protegido
async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        tareas = db.query(AgentTask).filter(AgentTask.user_id == user_id).order_by(AgentTask.creado_en.desc()).limit(5).all()
        memorias = db.query(AgentMemory).filter(AgentMemory.owner_id == user_id, AgentMemory.activo == 1).count()
    resumen = ", ".join(f"{item.kind}:{item.status}" for item in tareas) or "sin tareas"
    try:  # estado de las piezas (bot, modelo, IA): la comprobación nunca rompe el comando
        from backend.api.services.agent_tools import estado_de_piezas

        piezas = await estado_de_piezas()
        texto_piezas = "; ".join(f"{p['nombre']} {p['estado']}" + (f" ({p['motivo']})" if p.get("motivo") else "") for p in piezas)
    except Exception:  # noqa: BLE001
        texto_piezas = "no disponible"
    await update.effective_message.reply_text(f"Estado Laplace\nPiezas: {texto_piezas}\nMemorias privadas: {memorias}\nÚltimas tareas: {resumen}")


@protegido
async def cmd_partidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = list(context.args)
    fecha_token = args.pop(0) if args and _es_token_fecha(args[0]) else "hoy"
    fecha = _fecha_desde(fecha_token)
    filtro = " ".join(args).strip()
    try:
        resultado = await nucleo._herramienta(update, "sports.list_fixtures", {"date": fecha, **({"team": filtro} if filtro else {}), "limit": 200})
        partidos = resultado.get("fixtures", [])
        if filtro and not partidos:  # quizá era una liga y no un equipo
            resultado = await nucleo._herramienta(update, "sports.list_fixtures", {"date": fecha, "league": filtro, "limit": 200})
            partidos = resultado.get("fixtures", [])
    except Exception:
        log.exception("Fallo al listar partidos")
        await update.effective_message.reply_text("No pude consultar los partidos ahora mismo. Inténtalo en un momento.")
        return
    await _enviar(update, formatear_partidos(partidos, fecha))


async def _buscar_partido(update: Update, local: str, visitante: str) -> tuple[dict, str] | None:
    for token in ("hoy", "mañana"):
        fecha = _fecha_desde(token)
        resultado = await nucleo._herramienta(update, "sports.list_fixtures", {"date": fecha, "team": local, "limit": 200})
        for partido in resultado.get("fixtures", []):
            if _coincide(visitante, partido.get("visitante", "")) or _coincide(visitante, partido.get("local", "")):
                return partido, fecha
    return None


@protegido
async def cmd_predecir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    equipos = _separar_equipos(" ".join(context.args))
    if equipos is None:
        await update.effective_message.reply_text("Uso: /predecir Local vs Visitante\nEjemplo: /predecir River vs Boca")
        return
    try:
        encontrado = await _buscar_partido(update, *equipos)
        if encontrado is None:
            await update.effective_message.reply_text(
                "No encontré ese partido hoy ni mañana. Revisa los nombres con /partidos o prueba con otro equipo.")
            return
        partido, fecha = encontrado
        resultado = await nucleo._herramienta(update, "sports.predict", {
            "match_id": str(partido.get("match_id", "")), "local": partido.get("local", ""),
            "visitante": partido.get("visitante", ""), "league": partido.get("liga", "") or "Competición", "date": fecha,
        })
    except LimiteExcedido as exc:
        await update.effective_message.reply_text(f"{exc}. Inténtalo más tarde.")
        return
    except PermissionError:
        await update.effective_message.reply_text("No pude autenticar la consulta al bot deportivo. Avisa al administrador.")
        return
    except Exception:
        log.exception("Fallo al predecir")
        await update.effective_message.reply_text("No pude generar la predicción ahora mismo. Inténtalo en un momento.")
        return
    await _enviar(update, formatear_prediccion(partido, resultado.get("resumen") or {}))


@protegido
async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    fecha = _fecha_desde(context.args[0] if context.args else "hoy")
    try:
        resultado = await nucleo._herramienta(update, "sports.list_top_picks", {"date": fecha})
    except Exception:
        log.exception("Fallo al consultar Top Picks")
        await update.effective_message.reply_text("No pude consultar los Top Picks ahora mismo.")
        return
    picks = resultado.get("picks") or []
    if not picks:
        await update.effective_message.reply_text(
            f"No hay Top Picks publicados para {fecha}. El bot solo publica cuando la probabilidad estimada es suficiente.")
        return
    lineas = [f"🏆 Top Picks {fecha}"]
    for pick in picks[:5]:
        lineas.append(f"• {pick.get('local', '?')} vs {pick.get('visitante', '?')} → {pick.get('pick_final') or pick.get('pick') or 'n/d'}"
                      f" ({pick.get('confianza_final') or pick.get('confianza') or 'n/d'})")
    lineas += ["", AVISO_ESTIMACION]
    await _enviar(update, "\n".join(lineas))


@protegido
async def cmd_ligas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        resultado = await nucleo._herramienta(update, "sports.list_leagues", {})
    except Exception:
        log.exception("Fallo al listar ligas")
        await update.effective_message.reply_text("No pude consultar las ligas ahora mismo.")
        return
    ligas = [item.get("slug", "") for item in resultado.get("leagues", []) if item.get("slug")]
    await _enviar(update, f"Ligas con datos configurados ({len(ligas)}):\n" + ", ".join(ligas[:60]) +
                  ("\n…" if len(ligas) > 60 else "") + "\n\nPara cobertura detallada pregúntame por una liga.")
