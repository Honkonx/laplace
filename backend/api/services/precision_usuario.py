"""services/precision_usuario.py — "Mis picks": cuánto acertaron los pronósticos que consultó UN usuario.

Une el historial web del usuario con los marcadores finales de `partidos_dia` (los guarda el colector de resultados). Solo
cuentan los pronósticos con pick (un "Sin pronóstico" no es una predicción) y los partidos ya terminados con marcador.
Es un reporte honesto, no una promesa: con pocos partidos verificados lo dice (`concluyente=False`).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import HistorialPrediccionWeb
from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd

MUESTRA_MINIMA = 30  # igual que el mínimo que exige `calibracion.py` antes de llamar "confiable" a un winrate
PICKS_VALIDOS = ("Local", "Empate", "Visitante")


def _resultado(goles_local: int, goles_visitante: int) -> str:
    return "Local" if goles_local > goles_visitante else "Visitante" if goles_visitante > goles_local else "Empate"


def calcular_precision_usuario(db: Session, user_id: str) -> dict:
    filas = db.query(HistorialPrediccionWeb).filter(HistorialPrediccionWeb.user_id == user_id).all()
    sin_pronostico = sum(1 for f in filas if (f.pick or "") not in PICKS_VALIDOS)
    # Un mismo partido consultado varias veces cuenta una sola vez (el último análisis).
    ultimos: dict[tuple[str, str], HistorialPrediccionWeb] = {}
    for fila in sorted(filas, key=lambda f: f.creado_en or ""):
        if (fila.pick or "") in PICKS_VALIDOS:
            ultimos[(str(fila.partido_id), str(fila.fecha))] = fila

    verificados = aciertos = pendientes = 0
    por_confianza: dict[str, dict[str, int]] = {}
    for (partido_id, fecha), fila in ultimos.items():
        try:
            fecha_bd = normalizar_fecha_bd(fecha)
        except FechaBdInvalida:
            pendientes += 1
            continue
        partido = db.query(PartidoDia).filter(PartidoDia.fecha == fecha_bd, PartidoDia.match_id == partido_id).first()
        if partido is None or partido.status != "finished" or partido.goles_local is None or partido.goles_visitante is None:
            pendientes += 1
            continue
        acierto = _resultado(partido.goles_local, partido.goles_visitante) == fila.pick
        verificados += 1
        aciertos += acierto
        grupo = por_confianza.setdefault(str(fila.confianza or "n/d"), {"verificados": 0, "aciertos": 0})
        grupo["verificados"] += 1
        grupo["aciertos"] += acierto

    return {
        "picks_consultados": len(ultimos), "sin_pronostico": sin_pronostico, "verificados": verificados, "aciertos": aciertos,
        "pendientes": pendientes, "acierto_pct": round(100 * aciertos / verificados, 1) if verificados else None,
        "por_confianza": por_confianza, "muestra_minima": MUESTRA_MINIMA, "concluyente": verificados >= MUESTRA_MINIMA,
        "nota": ("Muestra suficiente para una lectura inicial." if verificados >= MUESTRA_MINIMA else
                 f"Solo {verificados} partidos verificados (mínimo {MUESTRA_MINIMA}): el porcentaje es real pero no concluyente."),
    }
