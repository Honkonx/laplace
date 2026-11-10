"""services/calidad_datos.py — Puerta de calidad de datos compartida por el análisis individual
(`analisis_completo`) y Top Picks.

Antes cada flujo tenía su propia lista de fuentes (`analisis_completo` contaba tabla/odds/h2h/
estadísticas/xg/bsd; `top_picks` solo estadísticas/tabla/h2h/odds), contaba odds y BSD como dos
fuentes independientes (BSD consume cuotas, así que no lo son) y no reconocía el módulo
`historico`, que no necesita fuentes externas. Esta es la única definición.

Canales independientes (cada uno cuenta una vez):
  - `estadisticas_equipo`: goles a favor/en contra reales de ambos equipos.
  - `tabla`: posición real de ambos equipos.
  - `h2h`: historial directo de al menos 3 partidos.
  - `mercado`: cuotas reales O predicción de BSD (BSD se alimenta de cuotas: un solo canal).
  - `xg`: xG real de ambos equipos.
  - `historico`: Dixon-Coles entrenado con histórico, solo si valida la liga y ambos equipos.
"""
from __future__ import annotations

import logging
from backend.api.services import modelo_historico as modelo_historico_svc

log = logging.getLogger("laplace.calidad_datos")

MIN_FUENTES_PUBLICAR = 2

# Cuántas señales crudas alimentan el canal único de mercado (se informan en `detalle_mercado`).
_SENALES_MERCADO = ("odds", "bsd")


def _estado_historico(d: dict) -> str | None:
    """`"ok"` (liga y ambos equipos), `"equipo_sin_historial"` (uno solo, con prior medido) o None."""
    try:
        valido, razon = modelo_historico_svc.validar_historico(d)
    except Exception:  # noqa: BLE001 — artefactos ausentes no deben tumbar el análisis
        log.debug("calidad_datos: validación histórica falló", exc_info=True)
        return None
    return razon if valido else None


def calcular_calidad_datos(fuentes_crudas: dict[str, bool], datos_motor: dict | None = None) -> dict:
    """`fuentes_crudas` usa las claves `estadisticas_equipo`, `tabla`, `h2h`, `odds`, `bsd`, `xg`
    (las que no aplican al flujo se omiten). `datos_motor` es el dict que recibe el motor: se usa
    para decidir si `historico` participa, así la puerta se evalúa DESPUÉS de saberlo."""
    estado_historico = _estado_historico(datos_motor) if datos_motor else None
    canales = {
        "estadisticas_equipo": bool(fuentes_crudas.get("estadisticas_equipo")),
        "tabla": bool(fuentes_crudas.get("tabla")),
        "h2h": bool(fuentes_crudas.get("h2h")),
        "mercado": any(bool(fuentes_crudas.get(s)) for s in _SENALES_MERCADO),
        "xg": bool(fuentes_crudas.get("xg")),
        "historico": estado_historico is not None,
    }
    activas = [nombre for nombre, disponible in canales.items() if disponible]
    cantidad = len(activas)
    # Un ancla basta para publicar: cuotas reales (no la predicción de BSD, que no vota) o el histórico con ambos equipos
    # conocidos. Medido el 2026-10-19 (ver `consenso.py`), cada uno SOLO acierta 69-71 % con p>=0,60 y 55-56 % con
    # 0,50-0,60: están calibrados. Sin ancla hacen falta dos fuentes, como antes.
    ancla = bool(fuentes_crudas.get("odds")) or estado_historico == "ok"
    publicable = cantidad >= MIN_FUENTES_PUBLICAR or ancla
    return {
        # Una fuente débil solo permite una lectura exploratoria. Un ancla, o dos fuentes, habilitan la publicación
        # y las métricas, sin convertir valores de respaldo en evidencia.
        "eligible": publicable,
        "ancla": ancla,
        "tier": "completa" if publicable else "exploratoria" if cantidad else "sin_datos",
        "sources": activas,
        "source_count": cantidad,
        "detalle_mercado": [s for s in _SENALES_MERCADO if fuentes_crudas.get(s)],
        "reason": (
            "Datos insuficientes para analizar el partido." if cantidad == 0
            else "Análisis exploratorio: hay una fuente real, pero sin cuotas ni histórico completo; falta una segunda fuente para publicar o medir rendimiento."
            if not publicable else None
        ),
    }
