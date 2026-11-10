"""services/resultados_scheduler.py — Orquestador de WF-E (Actualizar Resultados).

Ciclo completo: calcular fecha objetivo (zona Chile) → sweep de caché de partidos_dia →
leer pendientes (ventana horaria, con fallback a "todos los del día") → actualizar resultados
reales (`services/resultados.py`, ya construido en la Parte 1 — NO se reescribe acá) → push a
suscriptores por partido actualizado → resumen a Telegram admin.

Diferencia real vs. WF-E: el push y la notificación admin funcionaban con `cmd: ''` (string
vacío) en el n8n original — nunca se ejecutaban. Acá el envío es real.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.config import settings
from backend.api.db import partidos_repo
from backend.api.services import laboratorio_pronosticos, push_service, resultados as resultados_svc
from backend.api.services.telegram_client import enviar_mensaje

log = logging.getLogger("laplace.resultados_scheduler")

TZ_CHILE = ZoneInfo("America/Santiago")


def _calcular_fecha_objetivo(ahora: datetime | None = None) -> tuple[str, str]:
    """Replica la lógica de WF-E `Calcular Fecha Hoy`: la corrida de la madrugada (04h-10h
    Chile) procesa los partidos de AYER (que terminaron de noche); el resto del día procesa
    los de HOY. Devuelve (fecha 'YYYY-MM-DD', 'mañana'|'noche')."""
    ahora_cl = (ahora or datetime.now(TZ_CHILE)).astimezone(TZ_CHILE)
    es_manana = 4 <= ahora_cl.hour < 10
    objetivo = ahora_cl - timedelta(days=1) if es_manana else ahora_cl
    return objetivo.strftime("%Y-%m-%d"), ("manana" if es_manana else "noche")


def _formatear_resumen(fecha: str, corrida: str, resumen: dict, aciertos_hoy: dict | None = None) -> str:
    emoji_corrida = "🌅 Mañana" if corrida == "manana" else "🌙 Noche"
    linea_sep = "━" * 20
    texto = (
        f"📊 Resultados ({emoji_corrida}) — {fecha}\n{linea_sep}\n"
        f"✅ Actualizados: {resumen['actualizados']}/{resumen['total']}\n"
    )
    if resumen.get("pendientes"):
        texto += f"⏳ Aún en juego: {resumen['pendientes']}\n"
    if resumen.get("cancelados"):
        texto += f"🚫 Cancelados: {resumen['cancelados']}\n"
    if resumen.get("sin_datos"):
        texto += f"❌ Sin datos: {resumen['sin_datos']}\n"
    texto += linea_sep
    if aciertos_hoy:
        wr = f"{aciertos_hoy['winrate']}%" if aciertos_hoy.get("winrate") is not None else "N/D"
        texto += f"\n🎯 Aciertos hoy: {aciertos_hoy.get('aciertos', 0)}/{aciertos_hoy.get('evaluados', 0)} ({wr})"
    return texto


async def ejecutar_ciclo_resultados(db: Session, client: httpx.AsyncClient,
                                     ahora: datetime | None = None) -> dict:
    """Punto de entrada único — equivalente al cron de 2h + el de 07:00 de WF-E en una sola
    función (el caller decide la cadencia: endpoint manual, APScheduler, o ambos)."""
    fecha, corrida = _calcular_fecha_objetivo(ahora)
    ahora_utc_str = utc_ahora().strftime("%Y-%m-%dT%H:%M:%S")
    reconciliacion = laboratorio_pronosticos.reconciliar_resultados_experimentales(db)

    # 1. Sweep de caché — corre siempre, con o sin pendientes de análisis.
    invalidados_hora = partidos_repo.invalidar_partidos_terminados(db, ahora_utc_str)
    invalidados_ayer = 0
    if corrida == "noche":
        ayer = (datetime.strptime(fecha, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        invalidados_ayer = partidos_repo.invalidar_cache_dia_anterior(db, ayer)

    # 2. Pendientes — ventana horaria primero (ahorra cuota), fallback a "todos los del día".
    pendientes = partidos_repo.leer_pendientes_ventana(db, fecha)
    usando_ventana = len(pendientes) > 0
    if not usando_ventana:
        pendientes = resultados_svc.leer_pendientes_del_dia(db, fecha)

    if not pendientes:
        return {
            "fecha": fecha, "corrida": corrida, "sin_pendientes": True,
            "sweep": {"invalidados_hora": invalidados_hora, "invalidados_ayer": invalidados_ayer},
            "laboratorio": reconciliacion,
        }

    fixture_ids = [p["fixture_id"] for p in pendientes]
    pend_por_id = {p["fixture_id"]: p for p in pendientes}

    # 3. Actualizar resultados reales (BSD primero, api-football fallback) — ya construido.
    resultado = await resultados_svc.actualizar_resultados(db, client, fixture_ids, fecha)

    # 4. Push por partido actualizado (roto en n8n original — acá es real).
    push_enviados = 0
    for item in resultado["detalle"]:
        if item.get("estado") != "actualizado":
            continue
        p = pend_por_id.get(item["fixture_id"], {})
        marcador = item.get("resultado", {}).get("resultado", "")
        r = await push_service.enviar_push_a_subscriptores_match(
            client, db, item["fixture_id"],
            titulo="Resultado disponible",
            body=f"{p.get('local', 'Local')} {marcador} {p.get('visitante', 'Visitante')}",
            data={"screen": "Prediction", "params": {"match_id": item["fixture_id"]}},
        )
        push_enviados += r["enviados"]

    # 5. Resumen a Telegram admin.
    texto = _formatear_resumen(fecha, corrida, resultado["resumen"])
    admin_ok = False
    if settings.SPORTS_ADMIN_ID:
        admin_ok = await enviar_mensaje(client, settings.SPORTS_ADMIN_ID, texto)

    return {
        "fecha": fecha, "corrida": corrida, "sin_pendientes": False,
        "usando_ventana": usando_ventana,
        "sweep": {"invalidados_hora": invalidados_hora, "invalidados_ayer": invalidados_ayer},
        "resumen": resultado["resumen"], "detalle": resultado["detalle"],
        "push_enviados": push_enviados, "admin_notificado": admin_ok,
        "laboratorio": reconciliacion,
    }
