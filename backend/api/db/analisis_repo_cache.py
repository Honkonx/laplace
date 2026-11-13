"""
db/analisis_repo_cache.py — Caché de consenso y caché de predicción. Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.db.analisis_repo_comun import _now_str
from backend.api.models.predicciones import AnalisisIndividual, CacheConsenso, CachePrediccion


def verificar_consenso_cache(db: Session, partido_id: str) -> dict:
    """1. Caché consenso activo → servir. 2. Job en vuelo → dedup. 3. Nada → generar."""
    from backend.api.models.jobs import Job

    ahora = _now_str()
    cc = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.partido_id == partido_id, CacheConsenso.expira_en > ahora,
                CacheConsenso.usos < CacheConsenso.max_usos)
        .first()
    )
    if cc is not None:
        cc.usos += 1
        db.commit()
        return {
            "cache_consenso_hit": True, "debe_generar": False, "job_en_vuelo": False,
            "pick_consenso": cc.pick_consenso, "texto_consenso": cc.texto_consenso,
            "total_analisis": cc.total_analisis, "tipo_consenso": cc.tipo_consenso,
            "usos_restantes": cc.max_usos - cc.usos,
        }

    job_en_vuelo = (
        db.query(Job)
        .filter(Job.match_id == partido_id, Job.status.in_(["pendiente", "procesando"]))
        .order_by(Job.creado_en.desc())
        .first()
    )
    if job_en_vuelo is not None:
        return {"cache_consenso_hit": False, "debe_generar": False, "job_en_vuelo": True,
                "pick_consenso": None, "texto_consenso": None, "total_analisis": 0, "usos_restantes": 0}

    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()
    return {"cache_consenso_hit": False, "debe_generar": True, "job_en_vuelo": False,
            "pick_consenso": None, "texto_consenso": None, "total_analisis": total, "usos_restantes": 0}


def activar_cache_consenso(db: Session, partido_id: str, max_usos: int = 5, horas_ttl: int = 3) -> dict:
    """python: 2+ análisis coincidentes activan caché. ia/mixto: 3+. Mismo criterio que el
    original — no relajar el umbral sin que el usuario lo pida."""
    filas = (
        db.query(AnalisisIndividual)
        .filter(AnalisisIndividual.partido_id == partido_id)
        .order_by(AnalisisIndividual.creado_en.desc())
        .limit(3)
        .all()
    )
    if len(filas) < 2:
        return {"activado": False, "razon": f"Solo {len(filas)}/2 análisis disponibles",
                "total_analisis": len(filas)}

    fuentes = {(f.fuente or "python") for f in filas}
    if fuentes <= {"python"}:
        tipo_consenso, min_requerido = "python", 2
    elif fuentes & {"claude", "ia"} and fuentes & {"python"}:
        tipo_consenso, min_requerido = "mixto", 3
    else:
        tipo_consenso, min_requerido = "ia", 3

    if len(filas) < min_requerido:
        return {"activado": False, "razon": f"Solo {len(filas)}/{min_requerido} análisis ({tipo_consenso})",
                "total_analisis": len(filas)}

    picks = [f.pick_final for f in filas[:min_requerido]]
    if len(set(picks)) != 1:
        return {"activado": False, "razon": f"Picks divergen: {picks}", "total_analisis": len(filas)}

    mejor = max(filas[:min_requerido], key=lambda f: f.score_final or 0)
    pick_consenso = picks[0]
    expira = (utc_ahora() + timedelta(hours=horas_ttl)).strftime("%Y-%m-%d %H:%M:%S")
    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()

    existente = db.query(CacheConsenso).filter(CacheConsenso.partido_id == partido_id).first()
    if existente is None:
        db.add(CacheConsenso(partido_id=partido_id, pick_consenso=pick_consenso,
                              texto_consenso=mejor.texto_completo, total_analisis=total, usos=0,
                              max_usos=max_usos, tipo_consenso=tipo_consenso, expira_en=expira,
                              creado_en=_now_str()))
    else:
        existente.pick_consenso = pick_consenso
        existente.texto_consenso = mejor.texto_completo
        existente.total_analisis = total
        existente.usos = 0
        existente.max_usos = max_usos
        existente.tipo_consenso = tipo_consenso
        existente.expira_en = expira
    db.commit()
    return {"activado": True, "pick_consenso": pick_consenso, "total_analisis": total,
            "tipo_consenso": tipo_consenso, "min_requerido": min_requerido, "expira_en": expira,
            "max_usos": max_usos}


def guardar_cache(db: Session, input_hash: str, respuesta_json: str, partido_id: str, horas_ttl: int = 6) -> dict:
    expira = (utc_ahora() + timedelta(hours=horas_ttl)).strftime("%Y-%m-%d %H:%M:%S")
    existente = db.query(CachePrediccion).filter(CachePrediccion.input_hash == input_hash).first()
    if existente is None:
        db.add(CachePrediccion(input_hash=input_hash, respuesta_json=respuesta_json,
                                partido_id=partido_id, expira_en=expira, hits=0, creado_en=_now_str()))
    else:
        existente.respuesta_json = respuesta_json
        existente.partido_id = partido_id
        existente.expira_en = expira
    db.commit()
    return {"hash": input_hash, "expira_en": expira}


def verificar_cache(db: Session, match_id: str, fecha: str = "") -> dict:
    import hashlib

    if not match_id:
        return {"cache_hit": False, "respuesta_json": None, "hash": None,
                "error_debug": "match_id vacío — no se puede cachear"}

    h = hashlib.md5(f"{match_id}{fecha}".encode()).hexdigest()
    row = (
        db.query(CachePrediccion)
        .filter(CachePrediccion.input_hash == h, CachePrediccion.expira_en > _now_str())
        .first()
    )
    if row is None:
        return {"cache_hit": False, "respuesta_json": None, "hash": h}
    row.hits += 1
    db.commit()
    return {"cache_hit": True, "respuesta_json": row.respuesta_json, "hash": h}
