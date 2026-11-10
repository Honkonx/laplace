"""core/auth_deps.py — dependency FastAPI para validar el JWT de sesión (login app/web).

Usada por `POST /api/v1/auth/logout` (`routers/auth.py`) — primer endpoint que la conecta.
Queda lista para que futuros endpoints protegidos (perfil propio, historial propio, etc.) la
usen igual vía `Depends(obtener_usuario_actual)`.

2026-09-08 — agregado el chequeo de revocación (`db/tokens_repo.py`): un token cuyo `jti` fue
cerrado con `/auth/logout` deja de ser válido aunque su firma/expiración sigan siendo correctas.
El parámetro `db` tiene un default `Depends(get_db)` para no romper el contrato con quien ya
llamaba a esta función directo (sin FastAPI DI, ver `tests/test_auth.py`) — esos tokens de
prueba no incluyen `jti`, así que el chequeo de revocación nunca llega a tocar `db` en ese caso.
"""
from __future__ import annotations

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db.session import get_db
from backend.api.db.tokens_repo import esta_revocado

ALGORITMO_JWT = "HS256"


def obtener_usuario_actual(authorization: str = Header(...), db: Session = Depends(get_db)) -> dict:
    """Extrae y valida el JWT del header `Authorization: Bearer <token>`. Lanza 401 si
    falta el header, el formato es inválido, el token es inválido/expiró, o fue revocado
    (`POST /api/v1/auth/logout`)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization inválido — se espera 'Bearer <token>'")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.WEB_JWT_SECRET, algorithms=[ALGORITMO_JWT])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesión expirada — inicia sesión de nuevo")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

    jti = payload.get("jti")
    if jti and esta_revocado(db, jti):
        raise HTTPException(status_code=401, detail="Sesión cerrada — inicia sesión de nuevo")
    return payload


def requerir_admin(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    """Dependency para `routers/admin.py` (dashboard de administración, v1 solo-lectura, ver
    `PROPUESTA_DASHBOARD_ADMIN.md`). Reusa `obtener_usuario_actual` (JWT ya
    validado) y exige además `rol == 'admin'` — 403 si no. Nunca reutilizar `x-kairos-key`
    para esto (regla dura de AGENTS.md §3.9): ese secreto autentica al gateway de la app, no
    identifica a una persona ni tiene rol — solo un JWT de sesión real puede probar quién es
    el usuario logueado.

    2026-09-10 — antes chequeaba `plan == 'admin'` (pseudo-valor mezclado con el tier de
    suscripción, ver `models/usuarios.py`). Separado: `rol` es ahora la única fuente de verdad
    de permiso, `plan` volvió a ser 100% tier free/pro/max. Un JWT emitido antes de este cambio
    no trae el claim `rol` (`.get()` devuelve `None`, sigue dando 403 — fail-closed, correcto)."""
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Requiere permisos de administrador")
    return usuario
