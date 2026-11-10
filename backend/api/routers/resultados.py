"""routers/resultados.py — reemplaza el núcleo de WF-E (verificación de resultados).

Todavía sin scheduler (APScheduler queda para la Parte 2, junto con Telegram) — por ahora es
un endpoint invocable a mano o desde un cron externo simple."""
from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import requerir_admin
from backend.api.db.session import get_db
from backend.api.services import resultados as resultados_svc

# Solo admin (2026-10-07): el endpoint gasta cuota de las APIs deportivas externas y estaba
# abierto a cualquiera con la URL (hallazgo de la auditoría del agente). Mismo criterio que
# `routers/scheduler.py`; el agente reenvía el Bearer del admin (`sports.results`).
router = APIRouter(prefix="/api/v1/resultados", tags=["resultados"], dependencies=[Depends(requerir_admin)])


class VerificarResultadosInput(BaseModel):
    fixture_ids: list[str] = Field(default_factory=list)
    fecha: str = ""  # YYYY-MM-DD; default hoy si no se pasa


@router.post("/verificar")
async def verificar_resultados(payload: VerificarResultadosInput, db: Session = Depends(get_db)) -> dict:
    fecha = payload.fecha or datetime.now().strftime("%Y-%m-%d")

    fixture_ids = payload.fixture_ids
    if not fixture_ids:
        # Sin fixture_ids explícitos: usar los pendientes reales del día (mismo fallback
        # que el modo manual del script original).
        fixture_ids = [p["fixture_id"] for p in resultados_svc.leer_pendientes_del_dia(db, fecha)]

    if not fixture_ids:
        return {"ok": True, "data": {"total": 0, "actualizados": 0, "mensaje": "Sin pendientes"}}

    async with httpx.AsyncClient() as client:
        resultado = await resultados_svc.actualizar_resultados(db, client, fixture_ids, fecha)

    return {"ok": True, "data": resultado}
