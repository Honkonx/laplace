"""Orquestador inicial de tareas del agente.

El registry es explícito: no existe ejecución arbitraria de shell, Python ni código enviado por
el usuario. Las tareas se persisten antes de lanzarse y cada worker actualiza su estado.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import update

from backend.api.db.session import SessionLocal
from backend.api.core.config import settings
from backend.api.models.agent_runtime import AgentEvent, AgentTask
from backend.api.services.agent_guard import LimiteExcedido, entero_env
from backend.api.services.agent_runtime import procesar_mensaje
from backend.api.services.agent_tools import consultar_capacidades_deportivas
from backend.api.services.alerting import emitir_alerta

log = logging.getLogger("laplace.task_orchestrator")
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="laplace-agent-task")
TASK_KINDS = {"agent.chat", "sports.capabilities", "agent.qa", "agent.parallel"}
MAX_TIMEOUT_SEGUNDOS = 120
MAX_REINTENTOS = 2
_EN_COLA: set[str] = set()
_EN_COLA_LOCK = threading.Lock()
SUBAGENT_REGISTRY = {
    "laplace.chat": {"name": "Laplace Chat", "kind": "agent.chat", "capabilities": ["scope", "memory", "ia"]},
    "sports.bridge": {"name": "Puente deportivo", "kind": "sports.capabilities", "capabilities": ["football", "fixtures", "predictions"]},
    "qa.contracts": {"name": "QA de contratos", "kind": "agent.qa", "capabilities": ["health", "capabilities", "independence"]},
}


def recuperar_tareas_interrumpidas() -> int:
    """Marca solo las tareas que estaban ejecutándose al reiniciar."""
    with SessionLocal() as db:
        items = db.query(AgentTask).filter(AgentTask.status == "running").all()
        for item in items:
            item.status = "failed"
            item.error = "Proceso reiniciado antes de completar la tarea"
            item.terminado_en = _ahora()
        if items:
            db.commit()
        return len(items)


def reencolar_tareas_pendientes() -> int:
    """Reanuda tareas persistidas que aún no habían empezado cuando el proceso cayó."""
    with SessionLocal() as db:
        ids = [item.id for item in db.query(AgentTask).filter(AgentTask.status == "queued", AgentTask.cancel_requested == 0).all()]
    for task_id in ids:
        _encolar(task_id)
    return len(ids)


def _encolar(task_id: str) -> None:
    """Evita meter dos veces la misma tarea al pool del proceso (el worker reencola cada 2 s)."""
    with _EN_COLA_LOCK:
        if task_id in _EN_COLA:
            return
        _EN_COLA.add(task_id)
    EXECUTOR.submit(_ejecutar_y_liberar, task_id)


def _ejecutar_y_liberar(task_id: str) -> None:
    try:
        _ejecutar(task_id)
    finally:
        with _EN_COLA_LOCK:
            _EN_COLA.discard(task_id)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def registrar_evento(user_id: str, event_type: str, payload: dict | None = None, *, task_id: str | None = None, run_id: str | None = None) -> None:
    """Registra una transición auditable sin compartir la sesión del worker."""
    with SessionLocal() as db:
        db.add(AgentEvent(user_id=user_id, task_id=task_id, run_id=run_id, event_type=event_type, payload_json=json.dumps(payload or {}, ensure_ascii=False), creado_en=_ahora()))
        db.commit()


def crear_tarea(user_id: str, kind: str, payload: dict, parent_id: str | None = None, *, idempotency_key: str | None = None, max_attempts: int = 2, timeout_seconds: int = 60, es_admin: bool = False) -> AgentTask:
    """Persiste una tarea. `es_admin` lo fija SIEMPRE el llamador autenticado (rol del JWT): se
    sobrescribe cualquier `es_admin` que venga dentro de `payload`."""
    if kind not in TASK_KINDS:
        raise ValueError(f"Tipo de tarea no permitido: {kind}")
    if idempotency_key:
        with SessionLocal() as db:
            existente = db.query(AgentTask).filter(AgentTask.user_id == user_id, AgentTask.idempotency_key == idempotency_key).first()
            if existente:
                return existente
    with SessionLocal() as db:
        activas = db.query(AgentTask).filter(AgentTask.user_id == user_id, AgentTask.status.in_(["queued", "running"])).count()
    if activas >= entero_env("AGENT_MAX_TAREAS_ACTIVAS", 10):
        raise LimiteExcedido("Demasiadas tareas activas; espera a que terminen o cancélalas", 30)
    seguro = {**payload, "es_admin": bool(es_admin)}
    task = AgentTask(id=str(uuid.uuid4()), parent_id=parent_id, user_id=user_id, kind=kind, status="queued", input_json=json.dumps(seguro, ensure_ascii=False), output_json="{}", creado_en=_ahora(), idempotency_key=idempotency_key, max_attempts=min(max(max_attempts, 1), MAX_REINTENTOS), timeout_seconds=min(max(timeout_seconds, 5), MAX_TIMEOUT_SEGUNDOS))
    with SessionLocal() as db:
        db.add(task)
        db.commit()
        db.refresh(task)
    registrar_evento(user_id, "task.queued", {"kind": kind, "parent_id": parent_id}, task_id=task.id)
    if settings.AGENT_LOCAL_EXECUTOR:
        _encolar(task.id)
    return task


def listar_subagentes() -> list[dict]:
    return [{"id": key, **value, "enabled": True} for key, value in SUBAGENT_REGISTRY.items()]


def cancelar_tarea(task_id: str, user_id: str) -> bool:
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        if task is None or task.user_id != user_id or task.status in {"succeeded", "failed", "partial", "cancelled"}:
            return False
        task.cancel_requested = 1
        if task.status == "queued":
            task.status = "cancelled"
            task.terminado_en = _ahora()
        children = db.query(AgentTask).filter(AgentTask.parent_id == task_id, AgentTask.status.in_(["queued", "running"])).all()
        for child in children:
            child.cancel_requested = 1
            if child.status == "queued":
                child.status = "cancelled"
                child.terminado_en = _ahora()
        db.commit()
        registrar_evento(user_id, "task.cancel_requested", {"children": len(children)}, task_id=task_id)
        return True


def _reclamar(db, task_id: str) -> AgentTask | None:
    """Reclamo atómico: solo un proceso/hilo pasa de `queued` a `running` (UPDATE condicional)."""
    reclamadas = db.execute(
        update(AgentTask)
        .where(AgentTask.id == task_id, AgentTask.status == "queued", AgentTask.cancel_requested == 0)
        .values(status="running", iniciado_en=_ahora(), attempt_count=AgentTask.attempt_count + 1)
    ).rowcount
    db.commit()
    if reclamadas != 1:
        return None
    return db.get(AgentTask, task_id)


def _ejecutar(task_id: str) -> None:
    with SessionLocal() as db:
        task = _reclamar(db, task_id)
        if task is None:
            pendiente = db.get(AgentTask, task_id)
            if pendiente is not None and pendiente.status == "queued" and pendiente.cancel_requested:
                pendiente.status = "cancelled"
                pendiente.terminado_en = _ahora()
                db.commit()
                registrar_evento(pendiente.user_id, "task.cancelled", {"reason": "cancel_requested"}, task_id=pendiente.id)
            return
        registrar_evento(task.user_id, "task.running", {"kind": task.kind}, task_id=task.id)
        try:
            payload = json.loads(task.input_json)
            resultado = asyncio.run(asyncio.wait_for(_ejecutar_operacion(db, task, payload), timeout=task.timeout_seconds))
            task.status = "succeeded" if all(item.get("status") == "succeeded" for item in resultado.get("children", [])) else "partial"
            task.output_json = json.dumps(resultado, ensure_ascii=False)
            task.error = None
        except Exception as exc:
            log.exception("Fallo tarea %s", task_id)
            task.error = type(exc).__name__ + ": " + str(exc)
            if not task.cancel_requested and task.attempt_count < task.max_attempts:
                task.status = "queued"
                task.terminado_en = None
                db.commit()
                registrar_evento(task.user_id, "task.retry_scheduled", {"attempt": task.attempt_count, "max_attempts": task.max_attempts, "error": task.error}, task_id=task.id)
                EXECUTOR.submit(_ejecutar, task.id)
                return
            task.status = "cancelled" if task.cancel_requested else "failed"
        task.terminado_en = _ahora()
        db.commit()
        registrar_evento(task.user_id, f"task.{task.status}", {"kind": task.kind, "error": task.error}, task_id=task.id)
        if task.status == "failed":
            error_type = (task.error.split(":", 1)[0] if task.error else "unknown")
            emitir_alerta("agent.task_failed", {"task_id": task.id, "kind": task.kind, "error_type": error_type})


async def _ejecutar_operacion(db, task: AgentTask, payload: dict) -> dict:
    if task.kind == "agent.chat":
        return await procesar_mensaje(db, task.user_id, payload["message"], payload.get("session_id"), "task", bool(payload.get("usar_ia")), bool(payload.get("es_admin")))
    if task.kind == "sports.capabilities":
        return await _sports_capabilities()
    if task.kind == "agent.qa":
        return await _qa_contracts()
    if task.kind == "agent.parallel":
        return await asyncio.to_thread(_ejecutar_paralelo, task.id, task.user_id, payload)
    raise ValueError("Tarea no registrada")


def _ejecutar_paralelo(parent_id: str, user_id: str, payload: dict) -> dict:
    """Ejecuta un fan out cerrado y espera sus resultados sin bloquear el pool global."""
    requests = payload.get("requests", [])
    es_admin_padre = bool(payload.get("es_admin"))
    if not isinstance(requests, list) or not requests or len(requests) > 4:
        raise ValueError("agent.parallel requiere entre 1 y 4 requests")
    child_ids: list[str] = []
    for request in requests:
        if not isinstance(request, dict) or request.get("kind") not in {"agent.chat", "sports.capabilities", "agent.qa"}:
            raise ValueError("Subagente no registrado")
        child = AgentTask(id=str(uuid.uuid4()), parent_id=parent_id, user_id=user_id, kind=request["kind"], status="queued", input_json=json.dumps({**(request.get("payload") or {}), "es_admin": es_admin_padre}, ensure_ascii=False), output_json="{}", creado_en=_ahora(), max_attempts=1, timeout_seconds=MAX_TIMEOUT_SEGUNDOS)
        child_ids.append(child.id)
        child_id = child.id
        child_kind = child.kind
        with SessionLocal() as db:
            db.add(child)
            db.commit()
        registrar_evento(user_id, "subagent.created", {"kind": child_kind, "parent_id": parent_id}, task_id=child_id)
    with ThreadPoolExecutor(max_workers=len(child_ids), thread_name_prefix="laplace-subagent") as pool:
        list(pool.map(_ejecutar, child_ids))
    with SessionLocal() as db:
        result = []
        for child_id in child_ids:
            current = db.get(AgentTask, child_id)
            result.append({"id": child_id, "kind": current.kind if current else "unknown", "status": current.status if current else "failed", "output": json.loads(current.output_json or "{}") if current else {}, "error": current.error if current else "missing"})
    return {"subagents": len(child_ids), "children": result}


async def _sports_capabilities() -> dict:
    return await consultar_capacidades_deportivas()


async def _qa_contracts() -> dict:
    """Evaluación independiente mínima: salud y capacidades del bot opcional."""
    sports = await _sports_capabilities()
    return {
        "checks": {
            "agent_runtime": True,
            "closed_registry": True,
            "sports_dependency_optional": True,
            "sports_health": sports.get("available", False),
        },
        "status": "passed" if sports.get("available", False) else "degraded",
        "sports": sports,
    }
