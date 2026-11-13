"""services/planes_seguimiento.py — cuánto puede seguir y que le avisen cada persona según su plan (MS-11 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Los límites se aplican en el backend (repositorios y avisos), nunca en el prompt: lo mismo en Telegram, en el agente, en la web y en la PWA. Una persona sin fila de usuario (nunca se registró) conserva los
límites que el bot ya tenía (`SIN_PLAN`); los administradores tienen los del plan `max`. Los números son una propuesta y se cambian en un solo sitio: `LIMITES`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.models.usuarios import Usuario

LIMITES: dict[str, dict[str, int]] = {
    "free": {"equipos": 3, "ligas": 1, "partidos_24h": 3},
    "pro": {"equipos": 5, "ligas": 3, "partidos_24h": 6},
    "max": {"equipos": 10, "ligas": 6, "partidos_24h": 12},
}
SIN_PLAN = {"equipos": 5, "ligas": 3, "partidos_24h": 6}   # los topes que el bot tenía antes de los planes


def _id_comun(user_id: str) -> str:
    return user_id.removeprefix("telegram:")


def plan_de(db: Session, user_id: str) -> str | None:
    """El plan de la persona (`free`, `pro`, `max`) o None si no tiene fila de usuario o la base falla."""
    try:
        fila = db.query(Usuario).filter(Usuario.device_id == _id_comun(user_id)).first()
        return fila.plan if fila is not None else None
    except Exception:  # noqa: BLE001 — accesorio: ante un fallo rige el límite de siempre
        db.rollback()
        return None


def es_administrador(user_id: str) -> bool:
    return _id_comun(user_id) in settings.admin_ids or _id_comun(user_id) == (settings.SPORTS_ADMIN_ID or "-")


def limites(db: Session, user_id: str, es_admin: bool = False) -> dict[str, int]:
    """`{equipos, ligas, partidos_24h}` de esta persona."""
    if es_admin or es_administrador(user_id):
        return dict(LIMITES["max"])
    plan = plan_de(db, user_id)
    return dict(LIMITES.get(plan or "", SIN_PLAN))
