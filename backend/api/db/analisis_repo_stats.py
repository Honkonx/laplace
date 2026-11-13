"""
db/analisis_repo_stats.py — Estadísticas, winrate e historial de la app. Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.api.db.analisis_repo_comun import log
from backend.api.models.predicciones import CORTE_MOTOR_CON_PUERTA_CALIDAD, AnalisisComparativo, Prediccion


def leer_stats(db: Session) -> dict:
    from backend.api.models.jobs import Job

    total = db.query(Prediccion).count()
    alta = db.query(Prediccion).filter(Prediccion.confianza == "ALTA").count()
    media = db.query(Prediccion).filter(Prediccion.confianza == "MEDIA").count()
    baja = db.query(Prediccion).filter(Prediccion.confianza == "BAJA").count()
    completados = db.query(Job).filter(Job.status == "listo").count()
    errores = db.query(Job).filter(Job.status == "error").count()
    pendientes = db.query(Job).filter(Job.status == "pendiente").count()
    return {"predicciones": {"total": total, "alta": alta, "media": media, "baja": baja},
            "jobs": {"completados": completados, "errores": errores, "pendientes": pendientes}}


def leer_stats_aciertos(db: Session, dias: int = 30) -> dict:
    # `desde` se usa contra DOS campos de naturaleza distinta más abajo: `Prediccion.creado_en`
    # (timestamp, ahora UTC) y `AnalisisComparativo.fecha` (día calendario de negocio, local —
    # sin cambios). No hay un único valor que sea exacto para ambos; se deja en hora local
    # (correcto para `fecha`) — el único efecto práctico sobre `creado_en` es un corrimiento de
    # unas pocas horas en el borde de la ventana de reporte de N días (cosmético, no bloquea
    # ninguna decisión de negocio real). Ver docs/humano/ de esta ronda para el detalle.
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    def wr(a, t):
        return round((a or 0) / t * 100, 1) if t else None

    fuentes_out = []
    for fuente, total, aciertos, evaluados in (
        db.query(
            Prediccion.fuente,
            func.count(),
            func.sum(case((Prediccion.pick_correcto == 1, 1), else_=0)),
            func.sum(case((Prediccion.pick_correcto.isnot(None), 1), else_=0)),
        )
        .filter(Prediccion.creado_en >= desde)
        .group_by(Prediccion.fuente)
        .order_by(Prediccion.fuente)
        .all()
    ):
        fuentes_out.append({"fuente": fuente, "total": total or 0, "evaluados": evaluados or 0,
                             "aciertos": aciertos or 0, "winrate": wr(aciertos, evaluados)})

    filas = (
        db.query(AnalisisComparativo)
        .filter(
            AnalisisComparativo.fecha >= desde,
            AnalisisComparativo.creado_en >= CORTE_MOTOR_CON_PUERTA_CALIDAD,
            AnalisisComparativo.pick_correcto.isnot(None),
        )
        .all()
    )
    total = len(filas)
    aciertos = sum(1 for f in filas if f.pick_correcto == 1)
    alta = [f for f in filas if f.confianza == "ALTA"]
    media = [f for f in filas if f.confianza == "MEDIA"]
    consenso = [f for f in filas if f.consenso == "COINCIDEN"]

    return {
        "periodo_dias": dias, "desde": desde, "por_fuente": fuentes_out,
        "pick_final": {
            "total": total, "evaluados": total, "aciertos": aciertos, "winrate": wr(aciertos, total),
            "alta_winrate": wr(sum(1 for f in alta if f.pick_correcto == 1), len(alta)),
            "media_winrate": wr(sum(1 for f in media if f.pick_correcto == 1), len(media)),
            "consenso_winrate": wr(sum(1 for f in consenso if f.pick_correcto == 1), len(consenso)),
        },
    }


def leer_historial_app(db: Session, device_id: str, limit: int = 50) -> dict:
    from backend.api.models.jobs import Job

    jobs = (
        db.query(Job)
        .filter(Job.device_id_app == device_id, Job.origen == "app", Job.status == "listo")
        .order_by(Job.completado_en.desc())
        .limit(limit)
        .all()
    )
    historial = []
    for j in jobs:
        ac = db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == j.match_id).first()
        pick = (ac.pick_final if ac else None) or ""
        confianza = (ac.confianza if ac else None) or ""
        fuente = None
        if j.resultado_app:
            try:
                rd = json.loads(j.resultado_app)
                if isinstance(rd, dict):
                    fuente = rd.get("fuente") or rd.get("source")
                    pick = pick or rd.get("pick") or ""
                    confianza = confianza or rd.get("confianza") or ""
            except Exception:
                log.debug("analisis_repo: resultado_app no interpretable (resumen)", exc_info=True)

        if ac and ac.pick_correcto == 1:
            resultado_str = "acertado"
        elif ac and ac.pick_correcto == 0:
            resultado_str = "fallado"
        else:
            resultado_str = (ac.resultado_real if ac else None) or "pendiente"

        historial.append({
            "job_id": j.job_id, "match_id": j.match_id,
            "local": j.local_app or (ac.local if ac else "") or "",
            "visitante": j.visitante_app or (ac.visitante if ac else "") or "",
            "liga": j.liga_app or (ac.liga if ac else "") or "",
            "pick": pick, "confianza": confianza, "fuente": fuente,
            "resultado": resultado_str, "pick_correcto": ac.pick_correcto if ac else None,
            "fecha": (ac.fecha if ac else None) or j.fecha_partido, "completado_en": j.completado_en,
        })
    return {"historial": historial, "total": len(historial), "device_id": device_id}
