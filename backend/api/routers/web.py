"""routers/web.py — Endpoints mínimos para que `frontend/` (Astro) deje de tener lógica de
auth propia y sea un frontend puro, sin re-implementar `jwt.verify` en Node.

Agregado 2026-09-08 durante la auditoría línea por línea de `frontend/` vs `backend/api/` —
ver `AUDITORIA_FRONTEND_VS_BACKEND.md` para el detalle completo de qué se
migró y qué quedó pendiente (la lógica de predicción de tabla/descenso de `frontend/` NO se
migró en esta ronda — es un problema distinto al de Laplace, ver el documento).

Archivo nuevo separado de `routers/auth.py` a propósito (otro proceso en paralelo lo estaba
tocando el mismo día) — mismo prefix `/api/v1/auth`, sin colisión de rutas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.core.auth_deps import obtener_usuario_actual

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me")
def whoami(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    """Verifica el JWT del header `Authorization: Bearer <token>` y devuelve el usuario que
    representa — 401 si el token falta/expiró/es inválido/fue revocado (ver
    `core/auth_deps.py`). Pensado para que un cliente (como `frontend/`) verifique una sesión
    sin tener que conocer `WEB_JWT_SECRET` ni reimplementar la verificación de JWT."""
    return {
        "username": usuario.get("username"),
        "plan": usuario.get("plan"),
        # rol — 2026-09-10, separado de plan (ver models/usuarios.py §v7). El frontend/PWA lo
        # necesita para decidir si mostrar la sección de administración.
        "rol": usuario.get("rol"),
        "device_id": usuario.get("sub"),
    }
