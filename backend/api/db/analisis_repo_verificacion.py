"""
db/analisis_repo_verificacion.py — Verificación de partido para la app (consensos, análisis propio, plan y cuota). Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.api.db.analisis_repo_comun import _now_str
from backend.api.db.jobs_repo import rango_utc_dia_chile
from backend.api.models.predicciones import CacheConsenso


def verificar_partido_completo(db: Session, match_id: str, device_id: str, fecha: str) -> dict:
    """Todo lo que la app necesita para mostrar opciones de análisis de un partido, en una
    sola llamada."""
    from backend.api.models.jobs import Job
    from backend.api.models.usuarios import Usuario

    ahora = _now_str()
    ccs = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.partido_id == match_id, CacheConsenso.expira_en > ahora,
                CacheConsenso.usos < CacheConsenso.max_usos)
        .all()
    )
    consenso_python = {"existe": False, "texto": None, "total": 0, "pick": None}
    consenso_ia = {"existe": False, "texto": None, "total": 0, "pick": None}
    for cc in ccs:
        bloque = {"existe": True, "texto": cc.texto_consenso, "total": cc.total_analisis, "pick": cc.pick_consenso}
        if cc.tipo_consenso == "python":
            consenso_python = bloque
        elif cc.tipo_consenso in ("ia", "mixto"):
            consenso_ia = bloque

    # `Job.completado_en` se persiste en UTC (ver jobs_repo._now_str) — un LIKE 'YYYY-MM-DD%'
    # con `hoy` (día calendario de Chile pasado por el caller) ya no es válido acá; se usa el
    # rango UTC de ese día (ver jobs_repo.rango_utc_dia_chile). `hoy` vacío = sin filtro de
    # fecha (mismo comportamiento que el LIKE '%' original cuando `fecha` venía vacío).
    hoy = fecha[:10]
    job_query = db.query(Job).filter(
        Job.device_id_app == device_id, Job.match_id == match_id, Job.status == "listo"
    )
    if hoy:
        inicio_utc, fin_utc = rango_utc_dia_chile(hoy)
        job_query = job_query.filter(Job.completado_en >= inicio_utc, Job.completado_en < fin_utc)
    job = job_query.order_by(Job.completado_en.desc()).first()
    analisis_propio = {"existe": False, "content": None}
    if job is not None and job.resultado_app:
        try:
            contenido = json.loads(job.resultado_app)
        except Exception:
            contenido = job.resultado_app
        analisis_propio = {"existe": True, "content": contenido}

    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    plan = usuario.plan if usuario else "free"
    es_admin_rol = usuario is not None and usuario.rol == "admin"
    if usuario and plan != "free" and not es_admin_rol and usuario.activo_hasta and usuario.activo_hasta < hoy:
        plan = "free"
    from backend.api.core.config import settings
    # rol separado de plan desde 2026-09-10 (ver models/usuarios.py §v7) — `es_admin_rol` cubre
    # promociones vía `/gestionarusuario rol:admin`, `settings.admin_ids` sigue cubriendo la
    # lista fija histórica de `.env` — ambas fuentes activan el mismo pseudo-valor "admin" acá
    # (uso interno de este cálculo, nunca se guarda en la columna `plan`).
    if device_id in settings.admin_ids or es_admin_rol:
        plan = "admin"

    limite_ia = {"pro": 6, "max": 9999, "admin": 9999, "free": 0}.get(plan, 0)
    if plan == "pro":
        from backend.api.models.usuarios import UsoDiarioApp
        uso = db.get(UsoDiarioApp, (device_id, hoy))
        cuota_ia_restante = max(0, limite_ia - (uso.predicciones_usadas if uso else 0))
    else:
        cuota_ia_restante = limite_ia

    return {"consenso_python": consenso_python, "consenso_ia": consenso_ia,
            "analisis_propio": analisis_propio, "plan": plan, "cuota_ia_restante": cuota_ia_restante}
