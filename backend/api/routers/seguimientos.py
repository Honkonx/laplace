"""routers/seguimientos.py — «Mis seguimientos» de la web y la PWA (MS-13): equipos y ligas que sigue la persona, avisos y perfil.

Misma lógica, mismo almacén y mismos topes por plan que el chat de Telegram (`services/agent_panel.py`). Requiere sesión (JWT). Las respuestas llevan `ok`, el `mensaje` que diría el agente y el resumen al día.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.core.rate_limit import limitar
from backend.api.db.session import get_db
from backend.api.services import agent_panel

router = APIRouter(prefix="/api/v1/agent", tags=["seguimientos"])


class SeguirIn(BaseModel):
    tipo: str = Field(pattern="^(equipo|liga)$", description="equipo o liga")
    nombre: str = Field(min_length=3, max_length=60)


class AvisosIn(BaseModel):
    activar: bool


class PerfilIn(BaseModel):
    zona_horaria: str | None = Field(default=None, max_length=40)
    estilo: str | None = Field(default=None, max_length=12)
    mercados: list[str] | None = Field(default=None, max_length=4)


def _admin(usuario: dict) -> bool:
    return usuario.get("rol") == "admin"


@router.get("/seguimientos")
def ver(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.resumen(db, usuario["sub"], _admin(usuario))


@router.post("/seguimientos")
@limitar("60/minute")
def seguir(request: Request, body: SeguirIn, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.seguir(db, usuario["sub"], body.tipo, body.nombre, _admin(usuario))


@router.delete("/seguimientos")
@limitar("60/minute")
def dejar(request: Request, nombre: str = Query(min_length=3, max_length=60), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.dejar(db, usuario["sub"], nombre, _admin(usuario))


@router.post("/seguimientos/consentimiento")
@limitar("30/minute")
def aceptar(request: Request, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.aceptar(db, usuario["sub"], _admin(usuario))


@router.put("/seguimientos/avisos")
@limitar("30/minute")
def avisos(request: Request, body: AvisosIn, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.avisos(db, usuario["sub"], body.activar, _admin(usuario))


@router.put("/perfil")
@limitar("30/minute")
def guardar_perfil(request: Request, body: PerfilIn, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.guardar_perfil(db, usuario["sub"], body.zona_horaria, body.estilo, body.mercados, _admin(usuario))


@router.delete("/perfil")
@limitar("30/minute")
def borrar_perfil(request: Request, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return agent_panel.borrar_perfil(db, usuario["sub"], _admin(usuario))
