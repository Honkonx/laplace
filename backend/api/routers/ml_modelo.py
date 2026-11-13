"""routers/ml_modelo.py — contrato HTTP del modelo Laplace (`/api/v1/ml/*`). El modelo PRONOSTICA; publicar o no es política del agente.

- `POST /api/v1/ml/predict`: pronóstico de un partido (1X2, goles esperados, marcadores, ambos marcan, más/menos, confianza). Cálculo local, sin costo
  externo; limitado por IP. Si no hay modelo activo responde con el respaldo Dixon-Coles y `degradado: true`, o `ok: false` con el motivo.
- `GET /api/v1/ml/models`: modelos registrados con su estado y métricas (administrador).
- `GET /api/v1/ml/health`: versión del contrato y si hay un modelo activo (público, sin datos sensibles).
"""
from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import requerir_admin
from backend.api.core.config import settings
from backend.api.core.rate_limit import limitar
from backend.api.db.session import get_db
from backend.api.ml.laplace import auditoria, registro, servicio
from backend.api.ml.laplace import deriva as deriva_mod
from backend.api.models.ml_modelo import MlModelo

router = APIRouter(prefix="/api/v1/ml", tags=["modelo-laplace"])
VERSION_CONTRATO = "ml-1"


class EntradaPronostico(BaseModel):
    local: str = Field(min_length=1, max_length=120)
    visitante: str = Field(min_length=1, max_length=120)
    liga: str = Field(default="", max_length=120)
    pais: str = Field(default="", max_length=60, description="País de la competición (opcional): desambigua ligas homónimas, como la Serie B de Brasil o de Italia")
    liga_id: int | None = Field(default=None, ge=1, le=10_000_000, description="Id de la competición en API-Football (opcional)")
    partido_id: str | None = Field(default=None, max_length=64)
    cuotas: list[float] | None = Field(default=None, min_length=3, max_length=3, description="Cuotas decimales local, empate, visitante (opcional): activa `p1x2_con_mercado`")


@router.post("/predict")
@limitar("120/minute")
def pronosticar(request: Request, entrada: EntradaPronostico, db: Session = Depends(get_db)) -> dict:
    # `partido_id` NO se acepta por HTTP: ese endpoint es público y con un id elegido por quien llama se podrían sembrar pronósticos
    # "en sombra" sobre partidos ya jugados y sesgar la evaluación que habilita promover el modelo. Solo los llamadores internos lo fijan.
    datos = entrada.model_dump()
    datos["partido_id"] = None
    return {"contrato": VERSION_CONTRATO, **servicio.publico(servicio.pronosticar_partido(db, datos, canal="http"))}


@router.post("/predict/interno")
@limitar("300/minute")
def pronosticar_interno(request: Request, entrada: EntradaPronostico, x_laplace_ml_key: str = Header(default=""), db: Session = Depends(get_db)) -> dict:
    """Igual que `/predict` pero para llamadores de confianza (laboratorio, scripts, IAs externas autorizadas): exige `x-laplace-ml-key`, acepta `partido_id` y deja rastro
    (predicciones y sombra), que alimenta la evaluación. Sin `ML_API_KEY` configurada el endpoint no existe (404). La clave nunca se devuelve ni se registra."""
    clave = settings.ML_API_KEY
    if not clave:
        raise HTTPException(status_code=404, detail="Endpoint interno deshabilitado")
    if not hmac.compare_digest(x_laplace_ml_key.encode(), clave.encode()):
        raise HTTPException(status_code=401, detail="Clave inválida")
    return {"contrato": VERSION_CONTRATO, **servicio.publico(servicio.pronosticar_partido(db, entrada.model_dump(), canal="interno"))}


DEFINICION_HERRAMIENTA = {
    "name": "laplace_pronosticar",
    "description": "Pronóstico estadístico de un partido de fútbol con el modelo propio de Laplace: probabilidades 1X2, goles esperados, marcadores probables, "
                   "ambos marcan y más/menos goles. Solo pronostica; no recomienda apostar ni publicar. Es una estimación, no una certeza.",
    "input_schema": {"type": "object", "properties": {"local": {"type": "string", "maxLength": 120}, "visitante": {"type": "string", "maxLength": 120},
                                                       "liga": {"type": "string", "maxLength": 120}}, "required": ["local", "visitante"]},
}


@router.get("/tools")
def herramientas() -> dict:
    """Definición de la herramienta en formato Anthropic (`input_schema`) y OpenAI (`function`): cualquier IA con llamadas a herramientas puede pedirle el pronóstico al modelo por API."""
    d = DEFINICION_HERRAMIENTA
    return {"contrato": VERSION_CONTRATO, "endpoint": "POST /api/v1/ml/predict", "anthropic": d,
            "openai": {"type": "function", "function": {"name": d["name"], "description": d["description"], "parameters": d["input_schema"]}}}


@router.get("/modelo")
def ficha(db: Session = Depends(get_db)) -> dict:
    """Ficha del modelo activo (model card en datos): versión, variables, ligas, mercados validados y huellas de reproducibilidad. Pública y sin datos sensibles."""
    return {"contrato": VERSION_CONTRATO, **servicio.ficha_modelo(db)}


@router.get("/health")
def salud(db: Session = Depends(get_db)) -> dict:
    activo = registro.modelo_vigente(db)
    return {"contrato": VERSION_CONTRATO, "modelo_activo": bool(activo), "version": activo.version if activo else None}


@router.get("/equipo/{liga}/{equipo}")
@limitar("60/minute")
def memoria_de_equipo(request: Request, liga: str, equipo: str, db: Session = Depends(get_db)) -> dict:
    """Memoria compartida (MP-4): lo que el modelo activo sabe de un equipo (rating, goles, forma, partidos, fiabilidad, fecha y origen). `liga` es el código del modelo (p. ej. `E0`)."""
    activo = registro.modelo_vigente(db)
    if activo is None:
        raise HTTPException(status_code=404, detail="no hay un modelo Laplace activo: no hay memoria que consultar")
    memoria = auditoria.memoria_equipo(db, activo, liga.strip()[:40], equipo.strip()[:120], registro.cargar_artefacto(activo))
    if memoria is None:
        raise HTTPException(status_code=404, detail="el modelo no conoce esa liga o ese equipo")
    return {"contrato": VERSION_CONTRATO, **memoria}


@router.get("/errores")
def errores(_admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    """Memoria de errores (MP-1): dónde falla el modelo activo, con n por segmento (solo administradores)."""
    activo = registro.modelo_vigente(db)
    return {"contrato": VERSION_CONTRATO, "modelo_id": activo.id if activo else None, **auditoria.informe_errores(db, activo.id if activo else None)}


@router.get("/deriva")
def deriva(_admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    """Alerta de deriva de lo que produce el modelo activo (MP-12): PSI de las probabilidades de los últimos 30 días frente a los 120 anteriores (solo administradores)."""
    activo = registro.modelo_vigente(db)
    if activo is None:
        return {"contrato": VERSION_CONTRATO, "modelo_id": None, "alarma": False, "motivo": "no hay un modelo activo"}
    return {"contrato": VERSION_CONTRATO, **deriva_mod.deriva_de_salidas(db, activo.id)}


@router.get("/cadena")
def cadena(_admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    """Verifica la cadena de sellos de los pronósticos guardados (MP-5): `ok` o la primera ruptura (solo administradores)."""
    return {"contrato": VERSION_CONTRATO, **auditoria.verificar_cadena(db)}


@router.get("/models")
def listar_modelos(_admin: dict = Depends(requerir_admin), db: Session = Depends(get_db)) -> dict:
    filas = db.scalars(select(MlModelo).order_by(MlModelo.id.desc()).limit(100)).all()
    return {"contrato": VERSION_CONTRATO, "modelos": [
        {"id": m.id, "nombre": m.nombre, "version": m.version, "familia": m.familia, "estado": m.estado, "creado_en": m.creado_en,
         "promovido_por": m.promovido_por, "metricas": json.loads(m.metricas_json) if m.metricas_json else None} for m in filas]}
