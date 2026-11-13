"""bot/laplace_agent_bot_admin.py — comandos de administración del bot del agente (solo `settings.admin_ids`)."""
from __future__ import annotations

import logging
import functools
import re

import httpx
from sqlalchemy import text
from telegram import Update
from telegram.ext import ContextTypes

from backend.api.core.config import settings
from backend.api.db.session import SessionLocal
from backend.api.models.agent_runtime import AgentApproval
from backend.api.services.agent_approvals import AprobacionError, decidir_aprobacion, expirar_vencidas
from backend.api.services.agent_guard import (
    autorizacion_sports,
)

log = logging.getLogger("laplace.agent_telegram")

from backend.api.bot import laplace_agent_bot_nucleo as nucleo
from backend.api.bot.laplace_agent_bot_acceso import protegido, solo_admin
from backend.api.bot.laplace_agent_bot_formato import (
    _enviar,
)


@protegido
@solo_admin
async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conteos: dict[str, int] = {}
    with SessionLocal() as db:
        for etiqueta, tabla in (("usuarios", "usuarios"), ("análisis", "analisis_comparativo"), ("resultados verificados", "resultados_partidos"),
                                ("pronósticos de laboratorio", "pronosticos_experimentales")):
            try:
                conteos[etiqueta] = int(db.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar() or 0)  # tabla fija, no input
            except Exception:
                conteos[etiqueta] = -1
        evaluados = db.execute(text("SELECT variante, COUNT(*), SUM(resultado_real IS NOT NULL) FROM pronosticos_experimentales GROUP BY 1")).fetchall()
    lineas = ["🛠 Panel Laplace", *(f"• {k}: {v if v >= 0 else 'n/d'}" for k, v in conteos.items()), "", "Laboratorio (evaluados / total):"]
    lineas += [f"• {v}: {int(e or 0)}/{n}" for v, n, e in evaluados] or ["• sin observaciones"]
    try:
        usuario = f"telegram:{update.effective_user.id}"
        cabecera = autorizacion_sports(usuario, None, admin=True)
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{settings.SPORTS_BACKEND_URL.rstrip('/')}/api/v1/scheduler/status", headers={"Authorization": cabecera} if cabecera else None)
            r.raise_for_status()
            estado = r.json()
        trabajos = estado.get("jobs") or estado.get("trabajos") or []
        lineas += ["", f"Scheduler: {'saludable' if estado.get('saludable') else 'con jobs atrasados o sin correr'}"]
        for job in trabajos[:12]:
            lineas.append(f"• {job.get('job') or job.get('nombre')}: {job.get('estado') or ('ok' if job.get('ok') else 'revisar')}")
    except Exception as exc:
        lineas += ["", f"Scheduler: no disponible ({type(exc).__name__})"]
    await _enviar(update, "\n".join(lineas))


@protegido
@solo_admin
async def cmd_fuentes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.api.services.source_health import verificar_fuentes

    with SessionLocal() as db:
        async with httpx.AsyncClient() as client:
            fuentes = await verificar_fuentes(db, client)
    lineas = ["📡 Fuentes de datos"]
    for f in fuentes:
        icono = "✅" if f.get("saludable") else ("⚪" if not f.get("configurada") else "❌")
        extra = f" · {f['latencia_ms']} ms" if f.get("latencia_ms") else ""
        cuota = f" · cuota {f['cuota_restante']}" if f.get("cuota_restante") else ""
        lineas.append(f"{icono} {f.get('fuente')}{extra}{cuota}")
    await _enviar(update, "\n".join(lineas))


def con_bot_deportivo(handler):
    """H-025: si el bot deportivo no responde, la persona lee qué pasó y no el aviso genérico; `publicar` nunca da por publicado lo que no se pudo pedir."""

    @functools.wraps(handler)
    async def envoltorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await handler(update, context)
        except RuntimeError as exc:
            if "bot deportivo" not in str(exc):
                raise
            log.warning("El bot deportivo no respondió a /%s: %s", handler.__name__.removeprefix("cmd_"), exc)
            await update.effective_message.reply_text("El bot deportivo no responde ahora. No se hizo nada; inténtalo en unos minutos.")

    return envoltorio


@protegido
@solo_admin
@con_bot_deportivo
async def cmd_resultados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    fecha = context.args[0] if context.args and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context.args[0]) else ""
    resultado = await nucleo._herramienta(update, "sports.results", {"date": fecha}, aprobado=True)  # el comando del admin verificado es la aprobación
    datos = (resultado.get("result") or {}).get("data") or {}
    await update.effective_message.reply_text(
        f"Verificación de resultados: {datos.get('actualizados', 0)} actualizados de {datos.get('total', 0)} revisados."
        if datos else "Verificación ejecutada.")


@protegido
@solo_admin
async def cmd_marcador(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rendimiento histórico del modelo y del bot por liga (previa de los pesos del agente). `/marcador E0` muestra una liga."""
    from backend.api.services import agent_marcador

    previa = agent_marcador.cargar_previa()
    if not previa:
        await update.effective_message.reply_text("Todavía no hay previa histórica: corre backend/scripts/previa_piezas_por_liga.py.")
        return
    if context.args:
        codigo = context.args[0].upper()
        r = agent_marcador.resumen_liga(codigo, previa=previa)
        await update.effective_message.reply_text(agent_marcador.linea_para_usuario(r) or f"No hay datos de las dos piezas para {codigo}.")
        return
    lineas = []
    for f in agent_marcador.tabla_admin(previa):
        lider = {"modelo": "modelo", "bot": "bot"}.get(f["lider"], "parecidos")
        lineas.append(f"{f['liga']}: {lider} (dif. {f['diferencia']:.4f}, n={f['n_previa']})")
    await update.effective_message.reply_text("Marcador histórico (log loss; menos es mejor):\n" + "\n".join(lineas) + "\nDetalle: /marcador <liga>")


@protegido
@solo_admin
@con_bot_deportivo
async def cmd_toppicks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    resultado = await nucleo._herramienta(update, "sports.top_picks", {}, aprobado=True)
    datos = resultado.get("result") or {}
    picks = (datos.get("resultado") or datos).get("picks") or []
    await update.effective_message.reply_text(
        f"Vista previa de Top Picks (sin publicar): {len(picks)} pick(s) válidos. Para publicar: /publicar confirmo")


@protegido
@solo_admin
@con_bot_deportivo
async def cmd_publicar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0].lower() != "confirmo":
        await update.effective_message.reply_text("Esto publica los Top Picks en el canal. Para confirmar escribe: /publicar confirmo")
        return
    resultado = await nucleo._herramienta(update, "sports.publish", {"publish": True}, aprobado=True)
    publicado = bool((resultado.get("result") or {}).get("publicado", True))
    await update.effective_message.reply_text("Top Picks publicados en el canal." if publicado else "No se publicó (ya publicado hoy o sin picks válidos).")


PALABRAS_APROBAR = {"approve", "aprobar", "approved", "aprobado"}
PALABRAS_RECHAZAR = {"reject", "rechazar", "rejected", "rechazado"}


@protegido
@solo_admin
async def cmd_aprobaciones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        expirar_vencidas(db)
        items = db.query(AgentApproval).filter(AgentApproval.status == "pending").order_by(AgentApproval.requested_en.desc()).limit(10).all()
        texto = "\n".join(f"{item.id} · {item.tool_name} · usuario {item.user_id}" for item in items) or "No hay aprobaciones pendientes."
    await update.effective_message.reply_text(texto)


@protegido
@solo_admin
async def cmd_decidir_aprobacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    approval_id = context.args[0] if context.args else ""
    palabra = context.args[1].lower() if len(context.args) > 1 else ""
    if not approval_id or palabra not in PALABRAS_APROBAR | PALABRAS_RECHAZAR:
        # Un error de tipeo antes rechazaba la aprobación en silencio: ahora no se decide nada.
        await update.effective_message.reply_text("Uso: /decidir <id> aprobar | rechazar")
        return
    decision = "approved" if palabra in PALABRAS_APROBAR else "rejected"
    decididor = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        try:
            resultado = await decidir_aprobacion(db, approval_id, decision, decididor, authorization=autorizacion_sports(decididor, None, admin=True))
            estado = resultado["status"]
        except AprobacionError as exc:
            estado = exc.detalle
    await update.effective_message.reply_text(f"Aprobación {approval_id}: {estado}.")
