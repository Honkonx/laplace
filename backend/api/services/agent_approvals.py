"""Flujo de aprobaciones del agente, compartido por la API y el bot de Telegram.

La confirmación de una acción con efectos externos NO viaja como flag del cliente: solo existe
cuando un administrador decide una `AgentApproval` pendiente y vigente. La decisión es un UPDATE
condicional (`status='pending'`), de modo que dos decisiones simultáneas no ejecutan dos veces.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.api.models.agent_runtime import AgentApproval, AgentToolInvocation
from backend.api.services.agent_guard import entero_env
from backend.api.services.agent_tools import ejecutar_herramienta_deportiva


class AprobacionError(Exception):
    def __init__(self, status_code: int, detalle: str) -> None:
        super().__init__(detalle)
        self.status_code = status_code
        self.detalle = detalle


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def limpiar_argumentos(argumentos: dict) -> dict:
    """Quita cualquier intento del cliente de autoconfirmarse."""
    return {clave: valor for clave, valor in argumentos.items() if clave != "confirm"}


def expirar_vencidas(db: Session) -> int:
    """Marca como `expired` las aprobaciones pendientes más viejas que el TTL."""
    corte = (datetime.now(timezone.utc) - timedelta(seconds=entero_env("AGENT_APPROVAL_TTL_SECONDS", 3600))).isoformat()
    total = db.query(AgentApproval).filter(AgentApproval.status == "pending", AgentApproval.requested_en < corte).update(
        {"status": "expired", "decided_en": _ahora(), "note": "Vencida sin decisión"}, synchronize_session=False
    )
    if total:
        db.commit()
    return total


def crear_aprobacion(db: Session, invocation_id: str, user_id: str, tool_name: str, argumentos: dict) -> AgentApproval:
    aprobacion = AgentApproval(
        id=str(uuid.uuid4()), invocation_id=invocation_id, user_id=user_id, tool_name=tool_name,
        payload_json=json.dumps(limpiar_argumentos(argumentos), ensure_ascii=False), status="pending", requested_en=_ahora(),
    )
    db.add(aprobacion)
    return aprobacion


def _cerrar_invocacion(db: Session, aprobacion: AgentApproval, estado: str, salida: dict | None = None, error: str | None = None) -> None:
    invocacion = db.get(AgentToolInvocation, aprobacion.invocation_id) if aprobacion.invocation_id else None
    if invocacion is None:
        return
    invocacion.status = estado
    invocacion.terminado_en = _ahora()
    if salida is not None:
        invocacion.output_json = json.dumps(salida, ensure_ascii=False)
    if error:
        invocacion.error = error


async def decidir_aprobacion(db: Session, approval_id: str, decision: str, decidido_por: str, *, authorization: str | None = None) -> dict:
    """Decide una aprobación. El llamador YA verificó que `decidido_por` es administrador.

    `decision` es `approved` o `rejected`. Lanza `AprobacionError` (404 inexistente/ya decidida,
    410 vencida)."""
    if decision not in {"approved", "rejected"}:
        raise AprobacionError(400, "Decisión inválida")
    expirar_vencidas(db)
    ahora = _ahora()
    reclamada = db.query(AgentApproval).filter(AgentApproval.id == approval_id, AgentApproval.status == "pending").update(
        {"status": decision, "decided_en": ahora, "decided_by": decidido_por}, synchronize_session=False
    )
    db.commit()
    aprobacion = db.get(AgentApproval, approval_id)
    if not reclamada:
        if aprobacion is not None and aprobacion.status == "expired":
            raise AprobacionError(410, "La aprobación venció; solicita la acción de nuevo")
        raise AprobacionError(404, "Aprobación pendiente no encontrada o ya decidida")
    db.refresh(aprobacion)
    if decision == "rejected":
        _cerrar_invocacion(db, aprobacion, "rejected")
        db.commit()
        return {"id": aprobacion.id, "status": "rejected", "executed": False, "user_id": aprobacion.user_id, "tool": aprobacion.tool_name}
    argumentos = limpiar_argumentos(json.loads(aprobacion.payload_json or "{}"))
    try:
        resultado = await ejecutar_herramienta_deportiva(aprobacion.tool_name, argumentos, es_admin=True, aprobado=True, authorization=authorization)
    except Exception as exc:
        aprobacion.status = "failed"
        aprobacion.note = f"{type(exc).__name__}: {exc}"[:500]
        _cerrar_invocacion(db, aprobacion, "failed", error=aprobacion.note)
        db.commit()
        raise AprobacionError(400, str(exc)) from exc
    _cerrar_invocacion(db, aprobacion, "succeeded" if resultado.get("ok", True) else "failed", salida=resultado)
    db.commit()
    return {"id": aprobacion.id, "status": "approved", "executed": True, "result": resultado, "user_id": aprobacion.user_id, "tool": aprobacion.tool_name}
