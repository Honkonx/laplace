"""services/pronosticables.py — partidos programados del día que el bot SABE pronosticar.

Lo comparten el endpoint `/partidos/pronosticables` y el comando `/hoy` del bot. Solo lee la caché
`partidos_dia`: no gasta cuota de ninguna API.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.partidos import PartidoDia
from backend.api.services import modelo_historico


def listar_pronosticables(db: Session, fecha_bd: str) -> dict:
    """`fecha_bd` ya normalizada (YYYY-MM-DD). Los partidos con cuotas reales también se pronostican aunque
    no figuren aquí (las cuotas se piden al analizar)."""
    filas = db.query(PartidoDia).filter(PartidoDia.fecha == fecha_bd, PartidoDia.status == "scheduled").all()
    partidos = []
    for fila in filas:
        valido, razon = modelo_historico.validar_historico(
            {"liga": fila.liga_nombre or "", "local": fila.local or "", "visitante": fila.visitante or ""})
        if valido:
            partidos.append({
                "match_id": fila.match_id, "liga": fila.liga_nombre, "local": fila.local, "visitante": fila.visitante,
                "hora_chile": fila.hora_chile, "cobertura": "equipo_sin_historial" if razon == "equipo_sin_historial" else "completa",
            })
    partidos.sort(key=lambda p: (p["cobertura"] != "completa", p["hora_chile"] or "", p["liga"] or ""))
    return {"ok": True, "fecha": fecha_bd, "total_programados": len(filas), "total_pronosticables": len(partidos), "partidos": partidos}
