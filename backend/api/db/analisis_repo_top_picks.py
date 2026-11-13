"""
db/analisis_repo_top_picks.py — Carousel de Top Picks de la app (canal, usuario, compartido). Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from backend.api.db.analisis_repo_comun import _now_str, log
from backend.api.models.predicciones import AnalisisComparativo, CacheConsenso


def leer_top_picks_app(db: Session, device_id: str, fecha_yyyymmdd: str) -> dict:
    """Carousel de 3 fuentes: canal (WF-D), usuario (jobs propios), compartido (cache_consenso
    con 2+ análisis)."""
    from backend.api.models.jobs import Job
    from backend.api.models.partidos import RecomendacionDia

    fecha_iso = (
        f"{fecha_yyyymmdd[:4]}-{fecha_yyyymmdd[4:6]}-{fecha_yyyymmdd[6:]}"
        if len(fecha_yyyymmdd) == 8 else datetime.now().strftime("%Y-%m-%d")
    )

    recs = (
        db.query(RecomendacionDia)
        .filter(RecomendacionDia.fecha == fecha_yyyymmdd)
        .order_by(RecomendacionDia.hora_chile.asc())
        .limit(5)
        .all()
    )
    picks_canal = []
    for r in recs:
        ac = (
            db.query(AnalisisComparativo)
            .filter(AnalisisComparativo.partido_id == r.fixture_id, AnalisisComparativo.fecha == fecha_iso)
            .first()
        )
        picks_canal.append({
            "match_id": r.fixture_id, "local": r.local, "visitante": r.visitante, "liga": r.liga,
            "hora": r.hora_chile, "pick": (ac.pick_final if ac else None) or "Por definir",
            "confianza": (ac.confianza if ac else None) or "MEDIA",
            "score": ac.score_final if ac else None,
            "consenso": (f"{ac.fuentes_disp}/3" if ac and ac.fuentes_disp else "2/3"),
            "fuente": "canal", "partido": f"{r.local} vs {r.visitante}",
        })
    picks_canal.sort(key=lambda p: (p["score"] is None, -(p["score"] or 0)))

    picks_usuario = []
    if device_id:
        jobs = (
            db.query(Job)
            .filter(Job.device_id_app == device_id, Job.origen == "app", Job.status == "listo",
                    Job.fecha_partido == fecha_iso)
            .order_by(Job.completado_en.desc())
            .limit(3)
            .all()
        )
        for j in jobs:
            ac = db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == j.match_id,
                                                        AnalisisComparativo.fecha == fecha_iso).first()
            local = j.local_app or (ac.local if ac else "") or ""
            visitante = j.visitante_app or (ac.visitante if ac else "") or ""
            pick_val = (ac.pick_final if ac else None) or ""
            confianza_val = (ac.confianza if ac else None) or ""
            score_val = ac.score_final if ac else None
            fuente_val = "python"
            if j.resultado_app:
                try:
                    rd = json.loads(j.resultado_app)
                    if isinstance(rd, dict):
                        fuente_val = rd.get("fuente") or rd.get("source") or "python"
                        pick_val = pick_val or rd.get("pick") or ""
                        confianza_val = confianza_val or rd.get("confianza") or "MEDIA"
                        score_val = score_val or rd.get("score")
                except Exception:
                    log.debug("analisis_repo: resultado_app no interpretable (pick)", exc_info=True)
            if not pick_val:
                continue
            picks_usuario.append({
                "match_id": j.match_id, "local": local, "visitante": visitante,
                "liga": j.liga_app or (ac.liga if ac else "") or "", "hora": None,
                "pick": pick_val, "confianza": confianza_val or "MEDIA", "score": score_val,
                "consenso": "1/3", "fuente": fuente_val, "partido": f"{local} vs {visitante}",
            })

    ahora = _now_str()
    ccs = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.expira_en > ahora, CacheConsenso.total_analisis >= 2)
        .order_by(CacheConsenso.total_analisis.desc(), CacheConsenso.creado_en.desc())
        .limit(3)
        .all()
    )
    picks_compartido = []
    for cc in ccs:
        ac = (
            db.query(AnalisisComparativo)
            .filter(AnalisisComparativo.partido_id == cc.partido_id, AnalisisComparativo.fecha == fecha_iso)
            .first()
        )
        if not ac or not ac.local:
            continue
        picks_compartido.append({
            "match_id": cc.partido_id, "local": ac.local or "", "visitante": ac.visitante or "",
            "liga": ac.liga or "", "hora": None, "pick": cc.pick_consenso or "Por definir",
            "confianza": ac.confianza or "MEDIA", "score": ac.score_final,
            "consenso": f"{cc.total_analisis}/3", "fuente": f"compartido_{cc.tipo_consenso}",
            "partido": f"{ac.local or ''} vs {ac.visitante or ''}",
        })

    return {"canal": picks_canal, "usuario": picks_usuario, "compartido": picks_compartido,
            "fecha": fecha_iso, "tiene_contenido": bool(picks_canal or picks_usuario or picks_compartido)}
