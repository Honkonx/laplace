"""services/top_picks_publicacion.py — Publicación de los Top Picks en el canal de Telegram: formato del mensaje, marca de «ya publicado»,
envío idempotente por fecha y confirmación del administrador cuando la confianza es baja.

Se separó de `top_picks.py` (que calcula los candidatos y los pronósticos) para que cada archivo haga una sola cosa. `top_picks` reexporta estos nombres: quien ya
importaba `top_picks.publicar_top_picks` (el planificador, el router, el bot de Telegram y las pruebas) no cambia.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import recomendaciones_repo
from backend.api.models.partidos import StatsCache
from backend.api.services import consenso as consenso_svc
from backend.api.services.telegram_client import enviar_mensaje

log = logging.getLogger("laplace.top_picks")

# API-Football free tiene un presupuesto diario finito. Los caps priorizan ligas premium y
# dejan margen para análisis individuales durante el resto del día.
# Umbral de publicación por PROBABILIDAD ponderada del pick (2026-10-07). Evaluación walk-forward del
# consenso real (EVALUACION_CONSENSO_HISTORICO_2026-10-06.md): los picks con probabilidad
# ponderada >= 0,50 aciertan 58–64% y cubren ~40% de los partidos; por debajo el acierto cae a 46% o
# menos, cerca de "siempre Local" (43%). El score de consenso (acuerdo entre módulos) no estaba
# calibrado y premiaba módulos correlacionados, así que ya no decide la elegibilidad.
UMBRAL_PROB_PUBLICAR = consenso_svc.PROB_CONFIANZA_MEDIA

# `nivel_ia` viene de `services/consenso_ia.py::combinar_con_claude()` (COINCIDEN/DIVERGEN/
# SOLO_ESTADISTICO) — mismos 3 valores que arma el consenso a 2 vías del bot/app.
NIVEL_IA_EMOJI = {"COINCIDEN": "✅", "SOLO_ESTADISTICO": "⚠️", "DIVERGEN": "❌"}

NIVEL_IA_TEXTO = {"COINCIDEN": "IA coincide", "SOLO_ESTADISTICO": "sin IA", "DIVERGEN": "IA difiere"}

# TTL propio de la marca de "ya publicado" en `stats_cache` — no usa `guardar_stats_cache` de
# `db/cache.py` porque ese TTL es por `tipo` (team_stats/h2h/standings/predictions/odds) y no
# tiene una entrada para este caso; el default de esa tabla (6h) no alcanza a cubrir la ventana
# real entre el cron de las 9AM y una posible aprobación tardía del admin en el flujo de baja
# confianza (`confirmar_publicacion`), que puede llegar horas después.
MARCA_PUBLICADO_TTL_HORAS = 48

# ── Estado intermedio para el flujo de confirmación admin ────────────────────────────────────
# Un solo proceso, un solo admin decidiendo — un dict en memoria alcanza (si el proceso se
# reinicia entre el aviso y la respuesta del admin, se pierde y el admin simplemente no puede
# confirmar ese día; se vuelve a generar mañana). Ver `backend/api/bot/laplace_bot.py`.
_PENDIENTES_CONFIRMACION: dict[str, dict] = {}


def _formatear_mensaje_canal(resultado: dict) -> str:
    if resultado.get("sin_candidatos"):
        return (
            f"⚠️ Top Picks — {resultado['fecha_display']}\n{'━' * 20}\n\n"
            "Hoy no hay partidos de ligas prioritarias disponibles para analizar.\n\nVuelve mañana."
        )
    if resultado.get("sin_picks_validos"):
        return (
            f"⚠️ Top Picks — {resultado['fecha_display']}\n{'━' * 20}\n\n"
            f"Hoy los partidos disponibles no alcanzan el umbral mínimo de confianza "
            f"({round(UMBRAL_PROB_PUBLICAR * 100)}% de probabilidad estimada) para publicar picks.\n\nVuelve mañana para el análisis diario.\n\n"
            f"{'━' * 20}" + (f"\n🤖 Análisis personalizado: {settings.TELEGRAM_CANAL_ID}" if settings.TELEGRAM_CANAL_ID else "")
        )
    medals = ["🥇", "🥈", "🥉"]
    picks = resultado["picks"]
    mensaje = f"🗓 Top {len(picks)} Pick{'s' if len(picks) != 1 else ''} — {resultado['fecha_display']}\n{'━' * 20}\n\n"
    for idx, p in enumerate(picks):
        conf_emoji = "🟢" if p["score_consolidado"] >= 65 else "🟡" if p["score_consolidado"] >= 45 else "🔴"
        consenso_emoji = NIVEL_IA_EMOJI.get(p["nivel_ia"], "⚠️")
        mensaje += f"{medals[idx]} PICK {idx + 1}\n🏆 {p['local']} vs {p['visitante']}\n"
        mensaje += f"📍 {p['liga']} · {p['hora_chile']} (Chile)\n💰 {p['odds_texto']}\n"
        # Se muestra la probabilidad que decide el pick (consenso ponderado, con su procedencia);
        # el Poisson es un módulo más y solo aparece como detalle secundario si existe.
        prob_consenso = p.get("prob_consenso")
        if prob_consenso:
            mensaje += (
                f"📐 Probabilidad (consenso): {p['local']} {round(prob_consenso['local'] * 100, 1)}% | "
                f"Emp {round(prob_consenso['empate'] * 100, 1)}% | "
                f"{p['visitante']} {round(prob_consenso['visitante'] * 100, 1)}%"
            )
            if prob_consenso.get("procedencia"):
                mensaje += " (" + ", ".join(f"{m} {w}%" for m, w in prob_consenso["procedencia"]) + ")"
            mensaje += "\n"
        if p.get("prob_local_py") is not None:
            mensaje += (
                f"   Detalle Poisson: {round(p['prob_local_py'] * 100, 1)}% | "
                f"{round(p['prob_empate_py'] * 100, 1)}% | {round(p['prob_visit_py'] * 100, 1)}%\n"
            )
        mensaje += f"🤖 IA: {p['razon_ia'] or 'Sin análisis'}\n"
        if p.get("pick_externo"):
            mensaje += f"🌐 Externo: {p['pick_externo']}\n"
        # `modulos_consenso` ("N/M modelos coinciden en <pick>") ya incluye h2h/odds/tabla
        # cuando corrieron — a diferencia del texto viejo ("Consenso (N fuentes)"), que solo
        # contaba acuerdo entre poisson/forma/IA aunque el pick real ahora pesa los 5 módulos.
        mensaje += f"{consenso_emoji} {p['modulos_consenso']} ({NIVEL_IA_TEXTO.get(p['nivel_ia'], p['nivel_ia'])}) | Pick: <b>{p['pick_final']}</b>\n"
        mensaje += f"{conf_emoji} Score: {p['score_consolidado']}/100 [P:{p['score_py']} F:{p['score_form']} IA:{p['score_ia']}]\n\n"
    mensaje += f"{'━' * 20}" + (f"\n🤖 Análisis personalizado: {settings.TELEGRAM_CANAL_ID}" if settings.TELEGRAM_CANAL_ID else "") + (f"\n💬 <a href=\"{settings.TELEGRAM_GRUPO_URL}\">{html.escape(settings.TELEGRAM_GRUPO_NOMBRE)}</a>" if settings.TELEGRAM_GRUPO_URL else "")
    return mensaje


def _clave_publicado(fecha_clave: str) -> str:
    return f"top_picks_publicado:{fecha_clave}"


def _ya_publicado_hoy(db: Session, fecha_clave: str) -> bool:
    """Guarda de idempotencia real antes de enviar el mensaje al canal (bug real encontrado
    en la auditoría: `RecomendacionDia` es delete+reinsert idempotente, pero el ENVÍO real a
    Telegram no tenía ninguna protección — un re-disparo del cron 9AM, o una llamada manual a
    `POST /api/v1/scheduler/top-picks` el mismo día, mandaba el mensaje dos veces al canal
    real). Se ignora `expira_en` a propósito acá (a diferencia de `leer_stats_cache`): lo que
    importa es si la fila EXISTE para esta fecha, no si ya "venció" su TTL informativo."""
    return db.get(StatsCache, _clave_publicado(fecha_clave)) is not None


def _marcar_publicado(db: Session, fecha_clave: str) -> None:
    ahora = datetime.now()
    fila = StatsCache(
        cache_key=_clave_publicado(fecha_clave),
        tipo="top_picks_publicado",
        datos_json=json.dumps({"publicado_en": ahora.isoformat()}),
        creado_en=ahora.strftime("%Y-%m-%d %H:%M:%S"),
        expira_en=(ahora + timedelta(hours=MARCA_PUBLICADO_TTL_HORAS)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.merge(fila)  # merge, no add — evita choque de PK si dos requests pasan la guarda a la vez
    db.commit()


async def publicar_top_picks(db: Session, client: httpx.AsyncClient, resultado: dict) -> bool:
    """Envía al canal + guarda predicciones/recomendaciones. Se llama directo si la
    confianza no es baja, o desde `confirmar_publicacion()` si el admin aprueba.

    Idempotente por fecha: si ya se publicó hoy (`fecha_db`, o `fecha_display` como respaldo
    para el caso defensivo de un resultado sin candidatos/picks válidos), no vuelve a enviar
    el mensaje real al canal — devuelve `False` igual que un envío fallido, mismo contrato que
    ya esperaban los callers (`if not enviado: ...`)."""
    fecha_clave = resultado.get("fecha_db") or resultado.get("fecha_display", "")
    if fecha_clave and _ya_publicado_hoy(db, fecha_clave):
        log.warning("Top Picks ya publicado para %s — se evita el envío duplicado al canal", fecha_clave)
        return False

    if not settings.TELEGRAM_CANAL_ID:
        log.warning("TELEGRAM_CANAL_ID no configurado: Top Picks no se publica en ningún canal")
        return False

    mensaje = _formatear_mensaje_canal(resultado)
    enviado = await enviar_mensaje(client, settings.TELEGRAM_CANAL_ID, mensaje, disable_web_page_preview=True)

    if enviado and fecha_clave:
        _marcar_publicado(db, fecha_clave)
        if resultado.get("picks") and resultado.get("fecha_db"):
            recomendaciones_repo.guardar_picks_publicados(db, resultado["fecha_db"], resultado["picks"])

    if enviado and resultado.get("picks") and resultado.get("fecha_db"):
        # La app lee `recomendaciones_dia` como carrusel del canal. Antes se guardaban los
        # sobrantes y el usuario veía partidos distintos a los publicados en Telegram.
        recomendaciones_repo.guardar_recomendaciones(db, resultado["fecha_db"], resultado["picks"])

    return enviado


async def confirmar_publicacion(db: Session, client: httpx.AsyncClient, resultado: dict, aprobado: bool) -> str:
    """Función pura para que el bot de Telegram la conecte a los botones inline
    `pub_{fecha}`/`nopub_{fecha}` del flujo de baja confianza (wfd-012/013). El bot es quien
    guarda `resultado` (el dict de `generar_top_picks_dia`) en memoria/caché entre el mensaje
    al admin y el callback — este módulo no persiste ese estado intermedio."""
    if not aprobado:
        return "No publicado (rechazado por el admin)."
    ok = await publicar_top_picks(db, client, resultado)
    return "Publicado en el canal." if ok else "Error al publicar en el canal."


# ── Estado intermedio para el flujo de confirmación admin ────────────────────────────────────
# Un solo proceso, un solo admin decidiendo — un dict en memoria alcanza (si el proceso se
# reinicia entre el aviso y la respuesta del admin, se pierde y el admin simplemente no puede
# confirmar ese día; se vuelve a generar mañana). Ver `backend/api/bot/laplace_bot.py`.
_PENDIENTES_CONFIRMACION: dict[str, dict] = {}


def guardar_pendiente_confirmacion(fecha_db: str, resultado: dict) -> None:
    _PENDIENTES_CONFIRMACION[fecha_db] = resultado


def sacar_pendiente_confirmacion(fecha_db: str) -> dict | None:
    return _PENDIENTES_CONFIRMACION.pop(fecha_db, None)
