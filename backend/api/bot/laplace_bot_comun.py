"""bot/laplace_bot_comun.py — textos, formato y utilidades compartidas del bot deportivo."""
from __future__ import annotations

import html
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from backend.api.core.config import settings
from backend.api.db import (
    usuarios_repo,
)


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
    "/equipos · /privacidad · /olvidame — Tus equipos, consentimiento y borrado de datos\n"
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


def _es_admin(update: Update) -> bool:
    return str(update.effective_user.id) in settings.admin_ids
