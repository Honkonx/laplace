"""db/auditoria_repo.py — Escritura/lectura de `historial_plan` e `intento_login_fallido`.

Ver `models/auditoria.py` para el porqué de cada tabla.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.auditoria import AccionAdminAuditoria, HistorialPlan, IntentoLoginFallido

MEDIOS_VALIDOS = ("codigo", "admin")


def _now_str() -> str:
    """`creado_en` — normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`).
    Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def registrar_cambio_plan(db: Session, device_id: str, plan_anterior: str | None, plan_nuevo: str,
                           medio: str, detalle: str | None = None) -> dict:
    if medio not in MEDIOS_VALIDOS:
        raise ValueError(f"medio inválido: {medio}. Válidos: {MEDIOS_VALIDOS}")
    db.add(HistorialPlan(device_id=device_id, plan_anterior=plan_anterior, plan_nuevo=plan_nuevo,
                          medio=medio, detalle=detalle, creado_en=_now_str()))
    db.commit()
    return {"registrado": True, "device_id": device_id, "plan_nuevo": plan_nuevo, "medio": medio}


def leer_historial_plan(db: Session, device_id: str) -> list[dict]:
    """Más reciente primero. Ordena por `id` (no solo `creado_en`, que tiene resolución de
    segundo — dos cambios de plan en el mismo segundo quedarían en orden indefinido con un
    ORDER BY de un solo campo con empate)."""
    filas = (
        db.query(HistorialPlan)
        .filter(HistorialPlan.device_id == device_id)
        .order_by(HistorialPlan.id.desc())
        .all()
    )
    return [
        {"plan_anterior": f.plan_anterior, "plan_nuevo": f.plan_nuevo, "medio": f.medio,
         "detalle": f.detalle, "creado_en": f.creado_en}
        for f in filas
    ]


def listar_historial_plan(db: Session, limit: int = 50, offset: int = 0) -> dict:
    """Lista paginada de TODOS los cambios de plan (todos los device_id) para el dashboard de
    admin — distinto de `leer_historial_plan`, que filtra por un `device_id` puntual."""
    query = db.query(HistorialPlan).order_by(HistorialPlan.id.desc())
    total = query.count()
    filas = query.offset(offset).limit(limit).all()
    historial = [
        {"id": f.id, "device_id": f.device_id, "plan_anterior": f.plan_anterior,
         "plan_nuevo": f.plan_nuevo, "medio": f.medio, "detalle": f.detalle, "creado_en": f.creado_en}
        for f in filas
    ]
    return {"total": total, "limit": limit, "offset": offset, "historial": historial}


def registrar_intento_login_fallido(db: Session, username_intentado: str) -> dict:
    db.add(IntentoLoginFallido(username_intentado=username_intentado, creado_en=_now_str()))
    db.commit()
    return {"registrado": True}


def listar_intentos_login_fallidos(db: Session, limit: int = 50, offset: int = 0) -> dict:
    """Lista paginada de TODOS los intentos fallidos (todos los username) para el dashboard de
    admin — útil para detectar patrones de fuerza bruta a simple vista (ver
    `models/auditoria.py::IntentoLoginFallido`)."""
    query = db.query(IntentoLoginFallido).order_by(IntentoLoginFallido.id.desc())
    total = query.count()
    filas = query.offset(offset).limit(limit).all()
    intentos = [
        {"id": f.id, "username_intentado": f.username_intentado, "creado_en": f.creado_en}
        for f in filas
    ]
    return {"total": total, "limit": limit, "offset": offset, "intentos": intentos}


def registrar_accion_admin(db: Session, actor_admin_id: str, accion: str, detalle: str | None = None) -> dict:
    """Auditoría de una acción admin sensible sin `device_id` asociado (ej. generar códigos de
    acceso en lote) — ver `models/auditoria.py::AccionAdminAuditoria` para por qué no reusa
    `historial_plan`."""
    db.add(AccionAdminAuditoria(actor_admin_id=actor_admin_id, accion=accion, detalle=detalle, creado_en=_now_str()))
    db.commit()
    return {"registrado": True, "actor_admin_id": actor_admin_id, "accion": accion}


def listar_acciones_admin(db: Session, limit: int = 50, offset: int = 0) -> dict:
    """Lista paginada de TODAS las acciones admin auditadas (todos los actores) para el
    dashboard de admin — mismo patrón que `listar_historial_plan`/`listar_intentos_login_fallidos`."""
    query = db.query(AccionAdminAuditoria).order_by(AccionAdminAuditoria.id.desc())
    total = query.count()
    filas = query.offset(offset).limit(limit).all()
    acciones = [
        {"id": f.id, "actor_admin_id": f.actor_admin_id, "accion": f.accion,
         "detalle": f.detalle, "creado_en": f.creado_en}
        for f in filas
    ]
    return {"total": total, "limit": limit, "offset": offset, "acciones": acciones}


def contar_intentos_fallidos_recientes(db: Session, username: str, minutos: int = 15) -> int:
    """Informativo por ahora (no bloquea ningún login) — queda listo para un futuro rate-limit
    por username sin tener que rediseñar el esquema."""
    limite = (utc_ahora() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    return (
        db.query(IntentoLoginFallido)
        .filter(IntentoLoginFallido.username_intentado == username, IntentoLoginFallido.creado_en >= limite)
        .count()
    )
