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

import functools
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from backend.api.core.config import settings
from backend.api.db.session import SessionLocal
from backend.api.models.agent_runtime import AgentApproval, AgentMemory, AgentTask
from backend.api.services.agent_approvals import AprobacionError, decidir_aprobacion, expirar_vencidas
from backend.api.services.agent_guard import (
    LimiteExcedido,
    autorizacion_sports,
    consumir_ia,
    consumir_mensaje_chat,
    lista_env,
)
from backend.api.services.agent_runtime import procesar_mensaje, sincronizar_conocimiento_json
from backend.api.services.agent_tools import ejecutar_herramienta_deportiva

log = logging.getLogger("laplace.agent_telegram")

TZ_CHILE = ZoneInfo("America/Santiago")
MAX_MENSAJE = 3800
LIMITE_PARTIDOS = 20
MULTIPLICADOR_ADMIN_MENSAJES = 6

MSG_NO_AUTORIZADO = "No tienes acceso a este agente."
MSG_LIMITE = "Estás escribiendo demasiado rápido; espera un minuto e inténtalo de nuevo."
MSG_ERROR = "Ocurrió un error procesando tu mensaje. Inténtalo de nuevo en un momento."
MSG_SOLO_ADMIN = "Este comando es solo para el administrador."
AVISO_ESTIMACION = "Es una estimación estadística, no una certeza."

COMANDOS_PUBLICOS = [
    ("partidos", "Partidos de hoy o mañana (opcional: liga o equipo)"),
    ("predecir", "Predicción de un partido: /predecir River vs Boca"),
    ("top", "Top Picks publicados de hoy"),
    ("ligas", "Ligas cubiertas por el bot"),
    ("ia", "Pregunta al agente con IA"),
    ("estado", "Tus tareas y memorias"),
    ("ayuda", "Qué puedo hacer"),
]
COMANDOS_ADMIN = [
    ("panel", "Estado del sistema (admin)"),
    ("fuentes", "Salud de las fuentes de datos (admin)"),
    ("resultados", "Verificar resultados pendientes (admin)"),
    ("toppicks", "Generar Top Picks sin publicar (admin)"),
    ("publicar", "Publicar Top Picks: /publicar confirmo (admin)"),
    ("aprobaciones", "Aprobaciones pendientes (admin)"),
    ("decidir", "Decidir una aprobación (admin)"),
]


# --- Acceso -------------------------------------------------------------------------------------

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


# --- Utilidades de formato ----------------------------------------------------------------------

async def _enviar(update: Update, texto: str) -> None:
    """Envía respetando el límite de Telegram, cortando por saltos de línea."""
    texto = (texto or "").strip() or "Sin contenido."
    while texto:
        if len(texto) <= MAX_MENSAJE:
            await update.effective_message.reply_text(texto)
            return
        corte = texto.rfind("\n", 0, MAX_MENSAJE)
        corte = corte if corte > MAX_MENSAJE // 2 else MAX_MENSAJE
        await update.effective_message.reply_text(texto[:corte])
        texto = texto[corte:].lstrip("\n")


def _fecha_desde(texto: str | None) -> str:
    """'hoy' (defecto), 'mañana' o YYYY-MM-DD, en hora de Chile."""
    hoy = datetime.now(TZ_CHILE).date()
    valor = (texto or "hoy").strip().lower()
    if valor in {"mañana", "manana", "tomorrow"}:
        return (hoy + timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return valor
    return hoy.isoformat()


def _es_token_fecha(token: str) -> bool:
    return token.lower() in {"hoy", "mañana", "manana", "today", "tomorrow"} or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", token))


def _hora_corta(valor: object) -> str:
    """HH:MM desde el formato compacto de la cascada (`yyyymmddHHMM[SS]`) o desde un ISO (`...THH:MM...`)."""
    texto = str(valor or "")
    compacto = re.fullmatch(r"\d{8}(\d{2})(\d{2})(?:\d{2})?", texto)
    if compacto:
        return f"{compacto.group(1)}:{compacto.group(2)}"
    iso = re.search(r"[T ](\d{2}):(\d{2})", texto)
    return f"{iso.group(1)}:{iso.group(2)}" if iso else ""


def formatear_partidos(partidos: list[dict], fecha: str) -> str:
    if not partidos:
        return f"No encontré partidos para {fecha}."
    por_liga: dict[str, list[dict]] = {}
    for partido in partidos[:LIMITE_PARTIDOS]:
        por_liga.setdefault(str(partido.get("liga") or "Otras competiciones"), []).append(partido)
    lineas = [f"⚽ Partidos {fecha} ({len(partidos)} encontrados)"]
    for liga, items in por_liga.items():
        lineas.append(f"\n{liga}")
        for p in items:
            hora = _hora_corta(p.get("fecha"))
            lineas.append(f"• {hora + ' ' if hora else ''}{p.get('local', '?')} vs {p.get('visitante', '?')}")
    if len(partidos) > LIMITE_PARTIDOS:
        lineas.append(f"\n…y {len(partidos) - LIMITE_PARTIDOS} más. Filtra con /partidos <liga o equipo>.")
    lineas.append("\nPara una predicción: /predecir Local vs Visitante")
    return "\n".join(lineas)


def formatear_prediccion(partido: dict, resumen: dict) -> str:
    cabecera = f"⚽ {partido.get('local', '?')} vs {partido.get('visitante', '?')}"
    if partido.get("liga"):
        cabecera += f"\n{partido['liga']}"
    if not resumen or not resumen.get("pick"):
        texto = f"{cabecera}\n\nSin pronóstico propio para este partido (es un resultado válido, no un error)."
        for motivo in (resumen or {}).get("motivos_sin_pronostico") or []:
            texto += f"\n• {motivo}"
        ref = (resumen or {}).get("referencia_tasa_base") or {}
        if ref.get("pct_local") is not None:
            donde = "esta liga" if ref.get("nivel") == "liga" else "promedio general"
            texto += (f"\n\nReferencia, no pronóstico ({donde}): local {ref.get('pct_local')}% · empate {ref.get('pct_empate')}% · "
                      f"visitante {ref.get('pct_visitante')}%. No distingue a estos dos equipos.")
        return texto
    prob = resumen.get("prob_ponderada_pct") or {}
    lineas = [cabecera, ""]
    if prob:
        lineas.append(
            f"Probabilidad estimada: {partido.get('local', 'Local')} {prob.get('local', '?')}% · "
            f"Empate {prob.get('empate', '?')}% · {partido.get('visitante', 'Visitante')} {prob.get('visitante', '?')}%"
        )
    lineas.append(f"Resultado más probable: {resumen['pick']} · confianza {resumen.get('confianza', 'n/d')}")
    modulos = ", ".join(resumen.get("modulos_usados") or []) or "n/d"
    lineas.append(f"Modelos usados: {modulos}")
    base = resumen.get("tasa_base_liga")
    if base:
        lineas.append(
            f"Tasa base de la liga ({base.get('partidos')} partidos): local {base.get('pct_local')}% · "
            f"empate {base.get('pct_empate')}% · visitante {base.get('pct_visitante')}%"
        )
    lineas += ["", AVISO_ESTIMACION]
    return "\n".join(lineas)


# --- Núcleo de consulta al agente ---------------------------------------------------------------

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
        resultado = await procesar_mensaje(db, user_id=usuario, mensaje=texto, session_id=None, channel="telegram_agent", usar_ia=usar_ia, es_admin=admin)
    await _enviar(update, resultado["respuesta"])


async def _herramienta(update: Update, nombre: str, argumentos: dict, *, aprobado: bool = False) -> dict:
    usuario = f"telegram:{update.effective_user.id}"
    admin = _es_admin(update)
    return await ejecutar_herramienta_deportiva(
        nombre, argumentos, es_admin=admin, authorization=autorizacion_sports(usuario, None, admin=admin), aprobado=aprobado,
        usuario=usuario,  # el tope de predicciones se aplica dentro de la herramienta, igual para todos los caminos
    )


# --- Comandos para todos ------------------------------------------------------------------------

@protegido
async def _responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (update.effective_message.text or "").strip()
    if not texto:
        await update.effective_message.reply_text("Escribe una consulta para el agente. Usa /ayuda para ver qué puedo hacer.")
        return
    await _consultar_agente(update, texto[:4000], False)


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
    await _consultar_agente(update, texto[:4000], True)


@protegido
async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = f"telegram:{update.effective_user.id}"
    with SessionLocal() as db:
        tareas = db.query(AgentTask).filter(AgentTask.user_id == user_id).order_by(AgentTask.creado_en.desc()).limit(5).all()
        memorias = db.query(AgentMemory).filter(AgentMemory.owner_id == user_id, AgentMemory.activo == 1).count()
    resumen = ", ".join(f"{item.kind}:{item.status}" for item in tareas) or "sin tareas"
    await update.effective_message.reply_text(f"Estado Laplace\nMemorias privadas: {memorias}\nÚltimas tareas: {resumen}")


@protegido
async def cmd_partidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = list(context.args)
    fecha_token = args.pop(0) if args and _es_token_fecha(args[0]) else "hoy"
    fecha = _fecha_desde(fecha_token)
    filtro = " ".join(args).strip()
    try:
        resultado = await _herramienta(update, "sports.list_fixtures", {"date": fecha, **({"team": filtro} if filtro else {}), "limit": 200})
        partidos = resultado.get("fixtures", [])
        if filtro and not partidos:  # quizá era una liga y no un equipo
            resultado = await _herramienta(update, "sports.list_fixtures", {"date": fecha, "league": filtro, "limit": 200})
            partidos = resultado.get("fixtures", [])
    except Exception:
        log.exception("Fallo al listar partidos")
        await update.effective_message.reply_text("No pude consultar los partidos ahora mismo. Inténtalo en un momento.")
        return
    await _enviar(update, formatear_partidos(partidos, fecha))


def _separar_equipos(texto: str) -> tuple[str, str] | None:
    partes = re.split(r"\s+(?:vs\.?|v|contra|-)\s+", texto.strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(partes) != 2 or not partes[0].strip() or not partes[1].strip():
        return None
    return partes[0].strip(), partes[1].strip()


def _coincide(nombre_pedido: str, nombre_partido: str) -> bool:
    pedido, real = nombre_pedido.casefold(), (nombre_partido or "").casefold()
    return bool(pedido) and (pedido in real or real in pedido)


async def _buscar_partido(update: Update, local: str, visitante: str) -> tuple[dict, str] | None:
    for token in ("hoy", "mañana"):
        fecha = _fecha_desde(token)
        resultado = await _herramienta(update, "sports.list_fixtures", {"date": fecha, "team": local, "limit": 200})
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
        resultado = await _herramienta(update, "sports.predict", {
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
        resultado = await _herramienta(update, "sports.list_top_picks", {"date": fecha})
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
        resultado = await _herramienta(update, "sports.list_leagues", {})
    except Exception:
        log.exception("Fallo al listar ligas")
        await update.effective_message.reply_text("No pude consultar las ligas ahora mismo.")
        return
    ligas = [item.get("slug", "") for item in resultado.get("leagues", []) if item.get("slug")]
    await _enviar(update, f"Ligas con datos configurados ({len(ligas)}):\n" + ", ".join(ligas[:60]) +
                  ("\n…" if len(ligas) > 60 else "") + "\n\nPara cobertura detallada pregúntame por una liga.")


# --- Comandos de administrador ------------------------------------------------------------------

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


@protegido
@solo_admin
async def cmd_resultados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    fecha = context.args[0] if context.args and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context.args[0]) else ""
    resultado = await _herramienta(update, "sports.results", {"date": fecha}, aprobado=True)  # el comando del admin verificado es la aprobación
    datos = (resultado.get("result") or {}).get("data") or {}
    await update.effective_message.reply_text(
        f"Verificación de resultados: {datos.get('actualizados', 0)} actualizados de {datos.get('total', 0)} revisados."
        if datos else "Verificación ejecutada.")


@protegido
@solo_admin
async def cmd_toppicks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    resultado = await _herramienta(update, "sports.top_picks", {}, aprobado=True)
    datos = resultado.get("result") or {}
    picks = (datos.get("resultado") or datos).get("picks") or []
    await update.effective_message.reply_text(
        f"Vista previa de Top Picks (sin publicar): {len(picks)} pick(s) válidos. Para publicar: /publicar confirmo")


@protegido
@solo_admin
async def cmd_publicar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0].lower() != "confirmo":
        await update.effective_message.reply_text("Esto publica los Top Picks en el canal. Para confirmar escribe: /publicar confirmo")
        return
    resultado = await _herramienta(update, "sports.publish", {"publish": True}, aprobado=True)
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
    ):
        app.add_handler(CommandHandler(nombre, funcion))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _responder))
    app.add_error_handler(_error_global)
    return app
