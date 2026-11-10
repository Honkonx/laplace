"""routers/partidos.py — reemplaza la acción `juegos` de WF-A2 (cascada de fixtures)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.db.session import get_db
from backend.api.services import gateway
from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd

router = APIRouter(prefix="/api/v1", tags=["partidos"])


@router.get("/partidos")
async def listar_partidos(fecha: str, db: Session = Depends(get_db)) -> dict:
    """`fecha` en formato yyyyMMdd (mismo formato que ya usa gateway_unificado.py/la app).
    Cascada BD → LiveScore6 → BSD → api-football — la primera fuente con datos gana, y si
    no vino de 'bd' se guarda en caché para la próxima consulta del mismo día."""
    try:
        # Acepta YYYYMMDD o YYYY-MM-DD, pero la cascada trabaja con YYYYMMDD (formato de sus URLs).
        fecha = normalizar_fecha_bd(fecha).replace("-", "")
    except FechaBdInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with httpx.AsyncClient() as client:
        stages, fuente = await gateway.obtener_fixtures_cascada(db, client, fecha)
        if fuente != "bd" and stages:
            gateway.guardar_stages_en_cache(db, fecha, stages, fuente)

    total = sum(len(s.get("Events", [])) for s in stages)
    return {"ok": True, "fuente": fuente, "total": total, "Stages": stages}


@router.get("/partidos/pronosticables")
def partidos_pronosticables(fecha: str, db: Session = Depends(get_db)) -> dict:
    """Partidos programados del día que el bot SABE pronosticar (modelo histórico con la liga y los equipos), para que la
    web y la app ofrezcan primero lo que tendrá respuesta. Solo lee la caché `partidos_dia`: no gasta cuota de ninguna API.
    Los partidos con cuotas reales también se pronostican aunque no figuren aquí (las cuotas se piden al analizar)."""
    from backend.api.services.pronosticables import listar_pronosticables

    try:
        fecha_bd = normalizar_fecha_bd(fecha)
    except FechaBdInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return listar_pronosticables(db, fecha_bd)
