"""
services/analisis_completo_textos.py — Resumen estadístico para el prompt de IA y mensaje honesto de «sin pronóstico». Dividido de `analisis_completo.py` sin cambiar
comportamiento; `analisis_completo.py` reexporta estos nombres.
"""
from __future__ import annotations

import logging

from backend.api.core.config import settings
from backend.api.services import consenso as consenso_svc
from backend.api.services import mensajes_analisis, modelo_historico, nivel_evidencia

log = logging.getLogger("laplace.analisis")


def _resumen_estadistico(resultado_motor: dict) -> str:
    """Referencia que se inyecta al prompt de IA. Usa la probabilidad ponderada del consenso (la
    que decide el pick público) con su procedencia; el Poisson, si existe, va solo como detalle."""
    consenso = resultado_motor.get("consenso", {})
    texto = consenso_svc.texto_probabilidad_consenso(consenso)
    if not texto:
        return "Motor estadístico no disponible."
    partes = [
        f"Probabilidad ponderada del consenso: {texto}",
        f"Pick: {consenso.get('pick_final', '?')} (score {consenso.get('score_consenso', 0)}/100, "
        f"nivel {consenso.get('nivel', '?')})",
    ]
    procedencia = consenso.get("procedencia") or {}
    if procedencia.get("modulos"):  # MB-20: de dónde sale cada cifra (módulos que respondieron, peso y versión del modelo propio)
        origen = ", ".join(f"{m['modulo']} {round((m.get('peso') or 0) * 100)}%" + (f" (modelo propio {m['version_modelo_propio']})" if m.get("version_modelo_propio") else "") for m in procedencia["modulos"])
        partes.append(f"Procedencia: {origen}")
    partes.append("Estas cifras son del sistema: no las cambies ni las recalcules")
    poisson = resultado_motor.get("modulos", {}).get("poisson", {})
    if poisson.get("ok"):
        pl = round((poisson.get("prob_local") or 0) * 100, 1)
        pe = round((poisson.get("prob_empate") or 0) * 100, 1)
        pv = round((poisson.get("prob_visitante") or 0) * 100, 1)
        partes.append(f"Detalle Poisson (un módulo más): {pl}% | Empate {pe}% | {pv}%")
    return " | ".join(partes)


def _motivos_sin_pronostico(d: dict, calidad_datos: dict) -> list[str]:
    """Razones concretas (verificables en `d`) por las que no hay pronóstico propio, en lenguaje llano."""
    motivos = []
    if not d.get("odds_disponibles"):
        motivos.append("no hay cuotas reales de este partido")
    motivos += modelo_historico.motivos_sin_historico(d)
    if set(calidad_datos.get("sources", [])) & {"estadisticas_equipo", "h2h", "xg"}:
        motivos.append("hay estadísticas de los equipos, pero medidas contra el histórico rinden peor que la frecuencia de la liga")
    return motivos or ["ninguna fuente medida alcanzó para estimar el resultado"]


def _marcar_sin_pronostico(d: dict, resultado_motor: dict, calidad_datos: dict) -> str:
    """Adjunta la referencia histórica (liga o general) y devuelve el mensaje honesto para el usuario."""
    resultado_motor["referencia_tasa_base"] = modelo_historico.referencia_sin_pronostico(d)
    resultado_motor["motivos_sin_pronostico"] = _motivos_sin_pronostico(d, calidad_datos)
    resultado_motor["nivel_evidencia"] = nivel_evidencia.calcular_nivel_evidencia(resultado_motor)
    log.info(
        "sin_pronostico partido_id=%s liga=%r fuentes=%s motivos=%s", resultado_motor.get("partido_id"),
        resultado_motor.get("liga"), calidad_datos.get("sources"), resultado_motor["motivos_sin_pronostico"],
    )
    return mensajes_analisis.formatear_mensaje_sin_pronostico(
        resultado_motor, resultado_motor["motivos_sin_pronostico"], settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL
    )
