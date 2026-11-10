"""services/nivel_evidencia.py — En qué se apoya un pronóstico, en una escala ordenada y honesta.

El usuario ve una etiqueta de confianza (ALTA/MEDIA/BAJA) que sale de la probabilidad; esta escala dice de DÓNDE sale esa
probabilidad, que es lo que de verdad la respalda. Medido el 2026-10-19 sobre el periodo de prueba, cada ancla acierta con
su probabilidad (cuotas p>=0,60 → 71 %, Dixon-Coles → 69 %); sin ancla solo hay señales débiles, y sin nada se da la
frecuencia histórica como referencia (nunca un pick).

  N4  histórico + cuotas       las dos anclas coinciden en el partido
  N3  solo cuotas              mercado sin margen
  N2  solo histórico           Dixon-Coles con ambos equipos conocidos
  N1  histórico, equipo nuevo  un equipo sin historial: el rating del otro es un promedio (confianza máx. BAJA)
  N0  sin pronóstico propio    solo frecuencia de la liga como referencia
  --  señales débiles          solo tabla/forma (pesan 3 % y 2 %): confianza máx. BAJA
"""
from __future__ import annotations

NIVELES = {
    "N4": "Histórico y cuotas",
    "N3": "Solo cuotas del mercado",
    "N2": "Solo histórico de la liga",
    "N1": "Histórico con un equipo sin historial",
    "N0": "Sin pronóstico propio: frecuencia de la liga como referencia",
    "DEBIL": "Señales débiles (tabla y forma)",
}


def calcular_nivel_evidencia(resultado_motor: dict) -> dict:
    """`resultado_motor` es la salida de `motor.analizar_partido` (o el dict equivalente de "sin pronóstico")."""
    consenso = resultado_motor.get("consenso") or {}
    modulos = resultado_motor.get("modulos") or {}
    en_consenso = set(consenso.get("modulos_en_consenso") or []) | set(consenso.get("modulos_disidentes") or [])
    votan = {m for m in modulos if (modulos.get(m) or {}).get("ok") and (consenso.get("peso_efectivo") or {}).get(m, 0) > 0} | en_consenso
    pick = str(consenso.get("pick_final") or "")
    if not votan or pick.startswith("Sin pronóstico"):
        codigo = "N0"
    else:
        historico = modulos.get("historico") or {}
        con_historico = "historico" in votan
        nuevo = bool(historico.get("equipo_sin_historial"))
        con_cuotas = "odds" in votan
        if con_cuotas and con_historico and not nuevo:
            codigo = "N4"
        elif con_cuotas:
            codigo = "N3"
        elif con_historico and not nuevo:
            codigo = "N2"
        elif con_historico:
            codigo = "N1"
        else:
            codigo = "DEBIL"
    return {"codigo": codigo, "etiqueta": NIVELES[codigo]}
