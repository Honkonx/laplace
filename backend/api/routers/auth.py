"""routers/auth.py — Registro/login con usuario+clave (app y web, sin correo).

Nuevo 2026-09-07 — no existía nada equivalente en el sistema anterior (n8n identificaba app
por `device_id` automático, sin login real; Telegram se identifica por la plataforma misma).
Esto es una vía de identidad ADICIONAL sobre la misma tabla `usuarios` — no reemplaza el flujo
de `device_id` que ya usa `routers/app_gateway.py`.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import ALGORITMO_JWT, obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.core.rate_limit import limitar
from backend.api.db.auditoria_repo import registrar_intento_login_fallido
from backend.api.db.session import get_db
from backend.api.db.tokens_repo import revocar_token
from backend.api.db.usuarios_repo import crear_usuario_credenciales, obtener_usuario_por_username
from backend.api.services.auth_password import hashear_password, verificar_password

log = logging.getLogger("laplace.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
ORIGENES_VALIDOS = {"app", "web"}
TERMS_VERSION = "2026-09-25"


class RegistroInput(BaseModel):
    username: str
    password: str = Field(min_length=8)
    origen: str
    terms_accepted: bool = False
    terms_version: str = ""


class LoginInput(BaseModel):
    username: str
    password: str


def _emitir_token(usuario) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": usuario.device_id,
        "username": usuario.username,
        "plan": usuario.plan,
        # rol — 2026-09-10, separado de plan (ver models/usuarios.py). `requerir_admin`
        # (core/auth_deps.py) valida este claim, no `plan`.
        "rol": usuario.rol,
        # jti — 2026-09-08, permite revocar este token puntual antes de su expiración natural
        # vía POST /api/v1/auth/logout (ver core/auth_deps.py y db/tokens_repo.py).
        "jti": str(uuid.uuid4()),
        "iat": ahora,
        "exp": ahora + timedelta(hours=settings.WEB_JWT_EXPIRA_HORAS),
    }
    return jwt.encode(payload, settings.WEB_JWT_SECRET, algorithm=ALGORITMO_JWT)


@router.post("/registro")
@limitar("5/minute")
def registro(request: Request, body: RegistroInput, db: Session = Depends(get_db)) -> dict:
    if body.origen not in ORIGENES_VALIDOS:
        raise HTTPException(status_code=400, detail="origen debe ser 'app' o 'web'")
    if not body.terms_accepted or body.terms_version != TERMS_VERSION:
        raise HTTPException(status_code=400, detail="Debes aceptar los Términos y Condiciones vigentes para crear una cuenta")
    if not _USERNAME_RE.match(body.username):
        raise HTTPException(status_code=400, detail="username debe tener 3-20 caracteres alfanuméricos o guion bajo")

    if obtener_usuario_por_username(db, body.username) is not None:
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está en uso")

    # El chequeo de arriba da un mensaje claro en el caso normal, pero tiene una ventana
    # TOCTOU real entre el SELECT y el INSERT — dos registros concurrentes con el mismo
    # username podían colar ambos antes de la constraint UNIQUE real en BD (migración
    # 2026-09-09, ver models/usuarios.py). La constraint ya cierra la carrera; este
    # try/except es la red de seguridad para el caso concurrente, para no devolver un 500
    # genérico cuando la constraint es la que efectivamente frena el segundo INSERT.
    try:
        usuario = crear_usuario_credenciales(db, body.username, hashear_password(body.password), body.origen, TERMS_VERSION)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está en uso")
    return {"token": _emitir_token(usuario), "username": usuario.username, "plan": usuario.plan, "rol": usuario.rol, "device_id": usuario.device_id}


@router.post("/login")
@limitar("5/minute")
def login(request: Request, body: LoginInput, db: Session = Depends(get_db)) -> dict:
    usuario = obtener_usuario_por_username(db, body.username)
    if usuario is None or not usuario.password_hash or not verificar_password(body.password, usuario.password_hash):
        # Mensaje genérico a propósito — nunca revelar si falló el usuario o la contraseña.
        registrar_intento_login_fallido(db, body.username)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    return {"token": _emitir_token(usuario), "username": usuario.username, "plan": usuario.plan, "rol": usuario.rol, "device_id": usuario.device_id}


@router.post("/logout")
def logout(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Revoca el JWT actual (`jti` del token del header `Authorization`) — ver
    `db/tokens_repo.py`. Un token emitido antes de que existiera el claim `jti` no puede
    revocarse puntualmente (se deja pasar en `obtener_usuario_actual`, expira solo)."""
    jti = usuario.get("jti")
    if not jti:
        raise HTTPException(status_code=400, detail="Este token no admite revocación (emitido antes de esta función) — espera a que expire.")
    resultado = revocar_token(db, jti=jti, device_id=usuario.get("sub", ""))
    return {"cerrado": True, **resultado}


@router.get("/me")
def me(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Devuelve el estado real vigente del usuario autenticado por JWT (sincronizado con BD)."""
    from backend.api.models.usuarios import Usuario

    fila = db.query(Usuario).filter(Usuario.device_id == usuario.get("sub", "")).first()
    if fila is None:
        return {
            "username": usuario.get("username"),
            "plan": usuario.get("plan", "free"),
            "rol": usuario.get("rol", "usuario"),
            "device_id": usuario.get("sub", ""),
            "activo_hasta": None,
        }
    return {
        "username": fila.username or usuario.get("username"),
        "plan": fila.plan,
        "rol": fila.rol,
        "device_id": fila.device_id,
        "activo_hasta": fila.activo_hasta,
    }


class ActivarCodigoInput(BaseModel):
    codigo: str = Field(..., min_length=4, max_length=32)


@router.post("/activar-codigo")
def activar_codigo_jwt(
    body: ActivarCodigoInput,
    usuario: dict = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
) -> dict:
    """Canjea un código `KS-PRO-XXXXXXX` / `KS-MAX-XXXXXXX` para el usuario autenticado por JWT
    (Web/PWA o App) y emite un nuevo JWT firmado con el `plan` actualizado."""
    from backend.api.db import codigos_repo
    from backend.api.models.usuarios import Usuario

    sub = usuario.get("sub", "")
    resultado = codigos_repo.activar_codigo(db, body.codigo, sub)
    if not resultado.get("activado"):
        raise HTTPException(
            status_code=400,
            detail=resultado.get("mensaje", "No se pudo activar el código."),
        )

    fila = db.query(Usuario).filter(Usuario.device_id == sub).first()
    if fila is not None and not fila.username and usuario.get("username"):
        fila.username = usuario.get("username")
    nuevo_token = _emitir_token(fila) if fila is not None else ""
    return {
        "activado": True,
        "plan": fila.plan if fila is not None else resultado["plan"],
        "rol": fila.rol if fila is not None else usuario.get("rol", "usuario"),
        "dias": resultado["dias"],
        "activo_hasta": resultado["activo_hasta"],
        "mensaje": resultado["mensaje"],
        "token": nuevo_token,
    }
