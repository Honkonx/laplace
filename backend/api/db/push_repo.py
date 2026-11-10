"""db/push_repo.py — Tokens de push (Expo) y suscriptores por partido.

Port de `db_query.py::leer_match_subscriptores/guardar_push_token/
leer_push_tokens` (v8) — mismas tablas (`push_tokens`, `jobs`), mismo criterio de
suscripción (jobs de origen 'app' con status 'listo' para ese match_id).
"""
from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.jobs import Job
from backend.api.models.push import PushToken


def _now() -> str:
    """`creado_en`/`actualizado_en` — normalizado a UTC 2026-09-09 (ver docstring de
    `jobs_repo._now_str`). Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def guardar_push_token(db: Session, device_id: str, expo_push_token: str, platform: str = "android") -> None:
    existente = db.get(PushToken, device_id)
    ts = _now()
    if existente is None:
        db.add(PushToken(device_id=device_id, expo_push_token=expo_push_token, platform=platform,
                          creado_en=ts, actualizado_en=ts))
    else:
        existente.expo_push_token = expo_push_token
        existente.platform = platform
        existente.actualizado_en = ts
    db.commit()


def leer_push_tokens(db: Session, device_id: str | None = None) -> list[dict]:
    """Sin `device_id` devuelve todos los tokens registrados (para broadcast)."""
    stmt = select(PushToken)
    if device_id:
        stmt = stmt.where(PushToken.device_id == device_id)
    filas = db.execute(stmt).scalars().all()
    return [{"device_id": f.device_id, "expo_push_token": f.expo_push_token, "platform": f.platform} for f in filas]


def leer_match_subscriptores(db: Session, match_id: str) -> list[dict]:
    """device_ids que pidieron (y ya recibieron) un análisis de app para `match_id`."""
    filas = (
        db.query(Job.device_id_app, PushToken.expo_push_token, PushToken.platform)
        .outerjoin(PushToken, Job.device_id_app == PushToken.device_id)
        .filter(Job.match_id == match_id, Job.origen == "app", Job.status == "listo")
        .distinct()
        .all()
    )
    return [
        {"device_id": device_id, "expo_push_token": token, "platform": platform}
        for device_id, token, platform in filas
    ]
