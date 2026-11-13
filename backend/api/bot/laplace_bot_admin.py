"""bot/laplace_bot_admin.py — comandos de administración del bot deportivo (solo `SPORTS_ADMIN_IDS`)."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.api.db.session import SessionLocal
from backend.api.db import (
    admin_repo,
    auditoria_repo,
    codigos_repo,
    usuarios_repo,
)

from backend.api.bot.laplace_bot_comun import _es_admin


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
