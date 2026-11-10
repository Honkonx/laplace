"""db/tokens_repo.py — Revocación de sesión JWT (`token_revocado`).

Ver docstring de `models/tokens.py` para el porqué. `revocar_token` es idempotente: revocar
dos veces el mismo `jti` no falla ni duplica fila (logout llamado dos veces con el mismo token,
por ejemplo por un doble tap en la UI, debe comportarse igual que una vez).
"""
from __future__ import annotations


from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.tokens import TokenRevocado


def _now_str() -> str:
    """`revocado_en` — normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`).
    Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def revocar_token(db: Session, jti: str, device_id: str) -> dict:
    existente = db.query(TokenRevocado).filter(TokenRevocado.jti == jti).first()
    if existente is not None:
        return {"revocado": True, "jti": jti, "ya_estaba": True}
    db.add(TokenRevocado(jti=jti, device_id=device_id, revocado_en=_now_str()))
    db.commit()
    return {"revocado": True, "jti": jti, "ya_estaba": False}


def esta_revocado(db: Session, jti: str) -> bool:
    return db.query(TokenRevocado).filter(TokenRevocado.jti == jti).first() is not None
