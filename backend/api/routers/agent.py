"""API del agente general Laplace, separada del gateway deportivo."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.db.session import get_db
from backend.api.models.agent_runtime import AgentApproval, AgentEvent, AgentFeedback, AgentKnowledge, AgentLearningProposal, AgentMemory, AgentMemoryHistory, AgentMessage, AgentPolicyVersion, AgentRun, AgentSession, AgentTask, AgentToolInvocation
from backend.api.schemas.agent_capacidades import CapacidadesAgente, UsoAgente
from backend.api.services import agent_capacidades
from backend.api.services.agent_approvals import AprobacionError, crear_aprobacion, decidir_aprobacion, expirar_vencidas, limpiar_argumentos
from backend.api.services.agent_guard import LimiteExcedido, autorizacion_sports, clasificar_memoria, consumir_ia
from backend.api.services.agent_knowledge import esta_activo
from backend.api.services.agent_learning import estadisticas_feedback
from backend.api.services.agent_runtime import procesar_mensaje, sincronizar_conocimiento_json
from backend.api.services.agent_tools import ejecutar_herramienta_deportiva, listar_herramientas_deportivas
from backend.api.services.task_orchestrator import TASK_KINDS, cancelar_tarea, crear_tarea, listar_subagentes, registrar_evento

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _es_admin(usuario: dict) -> bool:
    return usuario.get("rol") == "admin"


def _presupuesto_ia(usuario: dict, cantidad: int = 1) -> None:
    """429 si el usuario agotó su cupo de llamadas con IA (por minuto o por día)."""
    try:
        consumir_ia(usuario["sub"], es_admin=_es_admin(usuario), cantidad=cantidad)
    except LimiteExcedido as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.reintentar_en)}) from exc

PROVIDER_CATALOG = [
    ("anthropic", "Anthropic", "CLAUDE_MODEL", "ANTHROPIC_API_KEY", ["claude-sonnet-4-6", "claude-haiku-4-5"]),
    ("openai", "OpenAI", "OPENAI_MODEL", "OPENAI_API_KEY", ["gpt-5", "gpt-5-mini"]),
    ("gemini", "Google Gemini", "GEMINI_MODEL", "GOOGLE_API_KEY", ["gemini-2.5-flash", "gemini-flash-lite-latest"]),
    ("groq", "Groq", "GROQ_MODEL", "GROQ_API_KEY", ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]),
    ("openrouter", "OpenRouter", "OPENROUTER_MODEL", "OPENROUTER_API_KEY", ["nvidia/nemotron-3-super-120b-a12b:free", "google/gemini-2.5-flash"]),
    ("xai", "xAI Grok", "XAI_MODEL", "XAI_API_KEY", ["grok-3-mini", "grok-3"]),
    ("mistral", "Mistral", "MISTRAL_MODEL", "MISTRAL_API_KEY", ["mistral-small-latest", "mistral-large-latest"]),
    ("cohere", "Cohere", "COHERE_MODEL", "COHERE_API_KEY", ["command-a-03-2025", "command-r-plus"]),
    ("together", "Together AI", "TOGETHER_MODEL", "TOGETHER_API_KEY", ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]),
    ("fireworks", "Fireworks AI", "FIREWORKS_MODEL", "FIREWORKS_API_KEY", ["accounts/fireworks/models/llama-v3p3-70b-instruct"]),
    ("deepseek", "DeepSeek", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY", ["deepseek-chat", "deepseek-reasoner"]),
    # El runtime no ofrece Ollama local: solo Cloud con una clave administrada en el servidor.
    ("ollama_cloud", "Ollama Cloud", "OLLAMA_CLOUD_MODEL", "OLLAMA_API_KEY", [
        "gemma4:31b", "gpt-oss:120b", "gpt-oss:20b", "nemotron-3-nano:30b",
        "nemotron-3-super", "nemotron-3-ultra",
    ]),
]


@router.get("/providers")
def proveedores_ia(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    """Catálogo seguro: muestra capacidad/configuración, nunca el valor de una credencial."""
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede gestionar proveedores")
    providers = []
    for provider_id, name, model_setting, credential_setting, models in PROVIDER_CATALOG:
        credential = getattr(settings, credential_setting, "")
        configured = bool(credential)
        providers.append({"id": provider_id, "name": name, "configured": configured, "status": "configured" if configured else "not_configured", "selected_model": getattr(settings, model_setting, None), "models": models, "credential_source": "environment"})
    return {"providers": providers, "security": "Las credenciales se configuran en secretos del servidor y nunca se devuelven al navegador."}


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = None
    channel: str = Field(default="web", pattern="^(web|pwa|android|telegram_agent)$")
    usar_ia: bool = False


class TaskInput(BaseModel):
    kind: str
    payload: dict = Field(default_factory=dict)
    parent_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)
    max_attempts: int = Field(default=2, ge=1, le=2)
    timeout_seconds: int = Field(default=60, ge=5, le=120)


class MemoryInput(BaseModel):
    agent_id: str = Field(default="laplace", min_length=1, max_length=100)
    scope: str = Field(default="usuario", pattern="^(usuario|global)$")
    kind: str = Field(default="preferencia", min_length=1, max_length=32)
    topic_key: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="usuario", max_length=255)
    sensibilidad: str = Field(default="normal", pattern="^(normal|sensible|privada)$")
    expira_en: str | None = None


class FeedbackInput(BaseModel):
    run_id: str | None = None
    rating: int = Field(ge=1, le=5)
    label: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)


class ProposalInput(BaseModel):
    scope: str = Field(default="usuario", pattern="^(usuario|global)$")
    topic_key: str = Field(min_length=1, max_length=255)
    proposal: dict


class ToolInput(BaseModel):
    arguments: dict = Field(default_factory=dict)


@router.get("/capabilities", response_model=CapacidadesAgente)
def capacidades_agente(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    """Qué ofrece el agente a ESTE usuario: modos, herramientas visibles para su rol, límites y versión del
    conocimiento. No revela credenciales; los nombres de proveedor de IA solo los ve el administrador."""
    return agent_capacidades.capacidades(_es_admin(usuario))


@router.get("/usage", response_model=UsoAgente)
def uso_agente(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Cupo de IA restante del usuario (por minuto y por día) y tareas activas; solo lectura, no consume cupo."""
    return agent_capacidades.uso(db, usuario["sub"], _es_admin(usuario))


@router.get("/metrics")
def metricas_agente(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> Response:
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede consultar métricas")
    task_counts = {str(status): int(total) for status, total in db.query(AgentTask.status, func.count(AgentTask.id)).group_by(AgentTask.status).all()}
    lines = ["# HELP laplace_agent_tasks_total Tareas persistidas del agente por estado.", "# TYPE laplace_agent_tasks_total gauge"]
    for status, total in sorted(task_counts.items()):
        lines.append(f'laplace_agent_tasks_total{{status="{status}"}} {total}')
    lines.extend([
        f"laplace_agent_approvals_pending {db.query(AgentApproval).filter(AgentApproval.status == 'pending').count()}",
        f"laplace_agent_memories_active {db.query(AgentMemory).filter(AgentMemory.activo == 1).count()}",
        f"laplace_agent_tool_invocations_total {db.query(AgentToolInvocation).count()}",
        f"laplace_agent_events_total {db.query(AgentEvent).count()}",
    ])
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.post("/chat")
async def chat(body: ChatInput, authorization: str = Header(...), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    sincronizar_conocimiento_json(db)  # no-op salvo que cambien los archivos de knowledge/
    if body.usar_ia:
        _presupuesto_ia(usuario)
    try:
        return await procesar_mensaje(db, usuario["sub"], body.message, body.session_id, body.channel, body.usar_ia, _es_admin(usuario), authorization)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools")
def herramientas(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    """Catálogo común que pueden consumir web, PWA, Android y Telegram. Un usuario normal no ve las herramientas exclusivas de administrador."""
    return {"tools": listar_herramientas_deportivas(es_admin=_es_admin(usuario))}


@router.post("/tools/{tool_name:path}")
async def ejecutar_tool(tool_name: str, body: ToolInput, authorization: str = Header(...), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    # El cliente nunca se autoconfirma: `confirm` se descarta y la acción pasa por aprobación.
    argumentos = limpiar_argumentos(body.arguments)
    invocation = AgentToolInvocation(id=str(uuid.uuid4()), user_id=usuario["sub"], tool_name=tool_name, status="running", input_json=json.dumps(argumentos, ensure_ascii=False), output_json="{}", creado_en=datetime.now(timezone.utc).isoformat())
    db.add(invocation)
    db.commit()
    try:
        resultado = await ejecutar_herramienta_deportiva(tool_name, argumentos, es_admin=_es_admin(usuario), authorization=autorizacion_sports(usuario["sub"], authorization), usuario=usuario["sub"])
        invocation.status = "succeeded" if resultado.get("ok", True) else "waiting_confirmation"
        invocation.output_json = json.dumps(resultado, ensure_ascii=False)
        if resultado.get("requires_confirmation"):
            aprobacion = crear_aprobacion(db, invocation.id, usuario["sub"], tool_name, argumentos)
            invocation.status = "waiting_approval"
            db.commit()
            registrar_evento(usuario["sub"], "approval.requested", {"approval_id": aprobacion.id, "tool": tool_name}, run_id=None)
            return {**resultado, "approval_id": aprobacion.id, "status": "pending"}
        invocation.terminado_en = datetime.now(timezone.utc).isoformat()
        db.commit()
        return resultado
    except LimiteExcedido as exc:
        invocation.status = "denied"
        invocation.error = str(exc)
        invocation.terminado_en = datetime.now(timezone.utc).isoformat()
        db.commit()
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.reintentar_en)}) from exc
    except PermissionError as exc:
        invocation.status = "denied"
        invocation.error = str(exc)
        invocation.terminado_en = datetime.now(timezone.utc).isoformat()
        db.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        invocation.status = "failed"
        invocation.error = str(exc)
        invocation.terminado_en = datetime.now(timezone.utc).isoformat()
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        invocation.status = "failed"
        invocation.error = type(exc).__name__ + ": " + str(exc)
        invocation.terminado_en = datetime.now(timezone.utc).isoformat()
        db.commit()
        raise


@router.get("/approvals")
def aprobaciones(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    expirar_vencidas(db)
    query = db.query(AgentApproval)
    if usuario.get("rol") != "admin":
        query = query.filter(AgentApproval.user_id == usuario["sub"])
    items = query.order_by(AgentApproval.requested_en.desc()).limit(100).all()
    return {"approvals": [{"id": x.id, "invocation_id": x.invocation_id, "user_id": x.user_id, "tool": x.tool_name, "payload": json.loads(x.payload_json or "{}"), "status": x.status, "requested_at": x.requested_en, "decided_at": x.decided_en, "decided_by": x.decided_by, "note": x.note} for x in items]}


async def _resolver_aprobacion(approval_id: str, decision: str, usuario: dict, authorization: str, db: Session) -> dict:
    if not _es_admin(usuario):
        raise HTTPException(status_code=403, detail="Solo el administrador puede decidir aprobaciones")
    try:
        resultado = await decidir_aprobacion(db, approval_id, decision, usuario["sub"], authorization=autorizacion_sports(usuario["sub"], authorization, admin=True))
    except AprobacionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle) from exc
    registrar_evento(resultado["user_id"], f"approval.{decision}", {"approval_id": approval_id, "tool": resultado["tool"]})
    return {clave: valor for clave, valor in resultado.items() if clave not in {"user_id", "tool"}}


@router.post("/approvals/{approval_id}/approve")
async def aprobar(approval_id: str, authorization: str = Header(...), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return await _resolver_aprobacion(approval_id, "approved", usuario, authorization, db)


@router.post("/approvals/{approval_id}/reject")
async def rechazar(approval_id: str, authorization: str = Header(...), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    return await _resolver_aprobacion(approval_id, "rejected", usuario, authorization, db)


@router.get("/events")
def eventos(limit: int = Query(100, ge=1, le=500), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    query = db.query(AgentEvent)
    if usuario.get("rol") != "admin":
        query = query.filter(AgentEvent.user_id == usuario["sub"])
    items = query.order_by(AgentEvent.id.desc()).limit(limit).all()
    return {"events": [{"id": x.id, "user_id": x.user_id, "task_id": x.task_id, "run_id": x.run_id, "type": x.event_type, "payload": json.loads(x.payload_json or "{}"), "created_at": x.creado_en} for x in items]}
@router.get("/tools/invocations")
def invocaciones_tools(limit: int = Query(50, ge=1, le=200), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    query = db.query(AgentToolInvocation).filter(AgentToolInvocation.user_id == usuario["sub"])
    items = query.order_by(AgentToolInvocation.creado_en.desc()).limit(limit).all()
    return {"invocations": [{"id": x.id, "tool": x.tool_name, "status": x.status, "input": json.loads(x.input_json or "{}"), "output": json.loads(x.output_json or "{}"), "error": x.error, "created_at": x.creado_en, "finished_at": x.terminado_en} for x in items]}


@router.get("/sessions")
def sesiones(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    items = db.query(AgentSession).filter(AgentSession.user_id == usuario["sub"]).order_by(AgentSession.actualizado_en.desc()).limit(100).all()
    return {"sessions": [{"id": x.id, "title": x.title, "channel": x.channel, "status": x.status, "updated_at": x.actualizado_en} for x in items]}


@router.get("/sessions/{session_id}/messages")
def mensajes(session_id: str, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    sesion = db.get(AgentSession, session_id)
    if not sesion or sesion.user_id != usuario["sub"]:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    items = db.query(AgentMessage).filter(AgentMessage.session_id == session_id).order_by(AgentMessage.id.asc()).all()
    return {"messages": [{"role": x.role, "content": x.content, "mode": x.modo, "created_at": x.creado_en} for x in items]}


@router.get("/memory")
def memoria(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    items = db.query(AgentMemory).filter(AgentMemory.activo == 1, or_(AgentMemory.expira_en.is_(None), AgentMemory.expira_en > now), ((AgentMemory.scope == "global") | ((AgentMemory.scope == "usuario") & (AgentMemory.owner_id == usuario["sub"])))).order_by(AgentMemory.actualizado_en.desc()).limit(100).all()
    return {"memory": [{"id": x.id, "scope": x.scope, "kind": x.kind, "topic_key": x.topic_key, "content": x.content, "confidence": x.confidence, "source": x.source} for x in items]}


@router.post("/memory")
def guardar_memoria(body: MemoryInput, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if body.scope == "global" and usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear memoria global")
    owner_id = None if body.scope == "global" else usuario["sub"]
    sensibilidad_detectada, contenido_seguro = clasificar_memoria(body.content)
    if contenido_seguro is None:
        raise HTTPException(status_code=400, detail="El contenido parece una credencial; no se guarda en la memoria")
    if sensibilidad_detectada == "sensible" and body.sensibilidad == "normal":
        body.sensibilidad = "sensible"
    now = datetime.now(timezone.utc).isoformat()
    item = AgentMemory(agent_id=body.agent_id, scope=body.scope, owner_id=owner_id, kind=body.kind, topic_key=body.topic_key, content=body.content, confidence=body.confidence, source=body.source, metadata_json=json.dumps({"created_by": usuario["sub"]}), sensibilidad=body.sensibilidad, expira_en=body.expira_en, creado_en=now, actualizado_en=now)
    db.add(item)
    db.flush()
    db.add(AgentMemoryHistory(memory_id=item.id, owner_id=owner_id, action="create", before_json="{}", after_json=json.dumps({"content": body.content, "source": body.source, "expires_at": body.expira_en}, ensure_ascii=False), changed_by=usuario["sub"], creado_en=now))
    db.commit()
    return {"id": item.id, "scope": item.scope, "topic_key": item.topic_key, "saved": True}


@router.delete("/memory/{memory_id}")
def eliminar_memoria(memory_id: int, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    item = db.get(AgentMemory, memory_id)
    if item is None or (item.scope == "global" and usuario.get("rol") != "admin") or (item.scope == "usuario" and item.owner_id != usuario["sub"]):
        raise HTTPException(status_code=404, detail="Memoria no encontrada")
    now = datetime.now(timezone.utc).isoformat()
    before = {"content": item.content, "topic_key": item.topic_key, "scope": item.scope, "active": item.activo}
    item.activo = 0
    item.actualizado_en = now
    db.add(AgentMemoryHistory(memory_id=item.id, owner_id=item.owner_id, action="archive", before_json=json.dumps(before, ensure_ascii=False), after_json=json.dumps({"active": 0}), changed_by=usuario["sub"], creado_en=now))
    db.commit()
    return {"id": memory_id, "archived": True}


@router.get("/memory/{memory_id}/history")
def historial_memoria(memory_id: int, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    item = db.get(AgentMemory, memory_id)
    if item is None or (item.scope == "global" and usuario.get("rol") != "admin") or (item.scope == "usuario" and item.owner_id != usuario["sub"]):
        raise HTTPException(status_code=404, detail="Memoria no encontrada")
    rows = db.query(AgentMemoryHistory).filter(AgentMemoryHistory.memory_id == memory_id).order_by(AgentMemoryHistory.id.asc()).all()
    return {"history": [{"id": row.id, "action": row.action, "before": json.loads(row.before_json or "{}"), "after": json.loads(row.after_json or "{}"), "changed_by": row.changed_by, "created_at": row.creado_en} for row in rows]}


@router.get("/memory/export")
def exportar_memoria(formato: str = Query("json", pattern="^(json|jsonl)$"), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    items = db.query(AgentMemory).filter(AgentMemory.activo == 1, AgentMemory.sensibilidad == "normal", or_(AgentMemory.expira_en.is_(None), AgentMemory.expira_en > now), ((AgentMemory.scope == "global") | ((AgentMemory.scope == "usuario") & (AgentMemory.owner_id == usuario["sub"])))).order_by(AgentMemory.id.asc()).all()
    rows = [{"id": x.id, "agent_id": x.agent_id, "scope": x.scope, "kind": x.kind, "topic_key": x.topic_key, "content": x.content, "confidence": x.confidence, "source": x.source, "sensitivity": x.sensibilidad, "expires_at": x.expira_en, "created_at": x.creado_en, "updated_at": x.actualizado_en} for x in items]
    if formato == "jsonl":
        return Response("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), media_type="application/x-ndjson")
    return {"memory": rows, "format": "json"}


@router.get("/knowledge")
def conocimiento(_: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    sincronizar_conocimiento_json(db)
    items = [x for x in db.query(AgentKnowledge).order_by(AgentKnowledge.namespace, AgentKnowledge.topic_key).all() if esta_activo(x)][:500]
    return {"knowledge": [{"namespace": x.namespace, "topic_key": x.topic_key, "content": x.content, "source": x.source} for x in items]}


@router.get("/search")
def buscar(q: str = Query(min_length=2, max_length=200), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Búsqueda FTS5 en SQLite con fallback textual portable."""
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        phrase = q.replace('"', " ").strip()
        try:
            rows = db.execute(text("SELECT kind, ref_id, owner_id, scope, content, topic_key FROM agent_search_fts WHERE agent_search_fts MATCH :query LIMIT 100"), {"query": f'"{phrase}"'}).mappings().all()
            visible = [row for row in rows if row["kind"] == "knowledge" or (row["kind"] == "message" and row["owner_id"] == usuario["sub"]) or (row["kind"] == "memory" and (row["scope"] == "global" or row["owner_id"] == usuario["sub"]))]
            return {"query": q, "engine": "sqlite-fts5", "results": [{"type": row["kind"], "id": row["ref_id"], "topic_key": row["topic_key"], "content": row["content"]} for row in visible]}
        except Exception:
            db.rollback()
    term = f"%{q}%"
    messages = db.query(AgentMessage).filter(AgentMessage.user_id == usuario["sub"], AgentMessage.content.ilike(term)).order_by(AgentMessage.id.desc()).limit(25).all()
    memories = db.query(AgentMemory).filter(AgentMemory.activo == 1, or_(AgentMemory.expira_en.is_(None), AgentMemory.expira_en > datetime.now(timezone.utc).isoformat()), AgentMemory.content.ilike(term), ((AgentMemory.scope == "global") | ((AgentMemory.scope == "usuario") & (AgentMemory.owner_id == usuario["sub"])))).limit(25).all()
    knowledge = db.query(AgentKnowledge).filter((AgentKnowledge.content.ilike(term)) | (AgentKnowledge.topic_key.ilike(term))).limit(25).all()
    return {"query": q, "engine": "sql-like", "results": [{"type": "message", "id": x.id, "content": x.content, "created_at": x.creado_en} for x in messages] + [{"type": "memory", "id": x.id, "topic_key": x.topic_key, "content": x.content, "source": x.source} for x in memories] + [{"type": "knowledge", "id": x.id, "topic_key": x.topic_key, "content": x.content, "source": x.source} for x in knowledge]}


@router.post("/feedback")
def feedback(body: FeedbackInput, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if body.run_id:
        run = db.get(AgentRun, body.run_id)
        if run is None or run.user_id != usuario["sub"]:
            raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    item = AgentFeedback(user_id=usuario["sub"], run_id=body.run_id, rating=body.rating, label=body.label, comment=body.comment, creado_en=datetime.now(timezone.utc).isoformat())
    db.add(item)
    db.commit()
    return {"id": item.id, "saved": True}


@router.get("/learning/feedback-stats")
def feedback_stats(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Agregado de feedback por herramienta y modo (solo administrador)."""
    if not _es_admin(usuario):
        raise HTTPException(status_code=403, detail="Solo el administrador puede consultar el aprendizaje")
    return estadisticas_feedback(db)


@router.post("/learning/proposals")
def crear_propuesta(body: ProposalInput, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if body.scope == "global" and usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede proponer cambios globales")
    item = AgentLearningProposal(id=str(uuid.uuid4()), created_by=usuario["sub"], scope=body.scope, topic_key=body.topic_key, proposal_json=json.dumps(body.proposal, ensure_ascii=False), status="pending", creado_en=datetime.now(timezone.utc).isoformat())
    db.add(item)
    db.commit()
    return {"id": item.id, "status": item.status, "saved": True}


@router.get("/learning/proposals")
def propuestas(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    query = db.query(AgentLearningProposal)
    if usuario.get("rol") != "admin":
        query = query.filter(AgentLearningProposal.created_by == usuario["sub"])
    items = query.order_by(AgentLearningProposal.creado_en.desc()).limit(100).all()
    return {"proposals": [{"id": x.id, "created_by": x.created_by, "scope": x.scope, "topic_key": x.topic_key, "proposal": json.loads(x.proposal_json), "status": x.status, "review_note": x.review_note, "created_at": x.creado_en, "reviewed_at": x.revisado_en} for x in items]}


@router.post("/learning/proposals/{proposal_id}/review")
def revisar_propuesta(proposal_id: str, status: str = Query(pattern="^(approved|rejected)$"), note: str | None = Query(default=None, max_length=2000), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede revisar propuestas")
    item = db.get(AgentLearningProposal, proposal_id)
    if item is None or item.status != "pending":
        raise HTTPException(status_code=404, detail="Propuesta pendiente no encontrada")
    item.status = status
    item.review_note = note
    item.revisado_en = datetime.now(timezone.utc).isoformat()
    applied = False
    version_id = None
    if status == "approved":
        # `created_by` de una política de ámbito "usuario" es su DUEÑO (quien la propuso), no el admin que la
        # revisa: `politicas_activas` la aplica solo a ese usuario. Antes se guardaba al admin revisor, así que
        # la política regía para el admin y no para su autor, y reemplazaba la de otros usuarios con el mismo tema.
        # El revisor queda en el evento de auditoría.
        dueno = item.created_by if item.scope == "usuario" else usuario["sub"]
        previous = db.query(AgentPolicyVersion).filter(AgentPolicyVersion.scope == item.scope, AgentPolicyVersion.topic_key == item.topic_key, AgentPolicyVersion.status == "active")
        if item.scope == "usuario":
            previous = previous.filter(AgentPolicyVersion.created_by == dueno)
        previous = previous.all()
        for policy in previous:
            policy.status = "superseded"
            policy.deactivated_en = item.revisado_en
        last = db.query(AgentPolicyVersion).filter(AgentPolicyVersion.scope == item.scope, AgentPolicyVersion.topic_key == item.topic_key).order_by(AgentPolicyVersion.version.desc()).first()
        version = (last.version if last else 0) + 1
        version_id = str(uuid.uuid4())
        db.add(AgentPolicyVersion(id=version_id, scope=item.scope, topic_key=item.topic_key, version=version, status="active", content_json=item.proposal_json, created_by=dueno, created_en=item.revisado_en, activated_en=item.revisado_en))
        registrar_evento(usuario["sub"], "policy.approved", {"proposal_id": item.id, "scope": item.scope, "topic_key": item.topic_key, "owner": dueno})
        applied = True
    db.commit()
    return {"id": item.id, "status": item.status, "applied": applied, "policy_version_id": version_id, "message": "Propuesta revisada y versionada."}


@router.get("/learning/policies")
def politicas(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    query = db.query(AgentPolicyVersion)
    if usuario.get("rol") != "admin":
        query = query.filter(AgentPolicyVersion.scope == "usuario", AgentPolicyVersion.created_by == usuario["sub"])
    items = query.order_by(AgentPolicyVersion.topic_key, AgentPolicyVersion.version.desc()).limit(200).all()
    return {"policies": [{"id": x.id, "scope": x.scope, "topic_key": x.topic_key, "version": x.version, "status": x.status, "content": json.loads(x.content_json or "{}"), "created_by": x.created_by, "created_at": x.created_en, "activated_at": x.activated_en, "deactivated_at": x.deactivated_en} for x in items]}


@router.post("/learning/policies/{policy_id}/rollback")
def rollback_politica(policy_id: str, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede revertir políticas")
    target = db.get(AgentPolicyVersion, policy_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Versión de política no encontrada")
    now = datetime.now(timezone.utc).isoformat()
    active = db.query(AgentPolicyVersion).filter(AgentPolicyVersion.scope == target.scope, AgentPolicyVersion.topic_key == target.topic_key, AgentPolicyVersion.status == "active")
    if target.scope == "usuario":
        active = active.filter(AgentPolicyVersion.created_by == target.created_by)  # solo las del mismo dueño
    for item in active.all():
        item.status = "superseded"
        item.deactivated_en = now
    target.status = "active"
    target.activated_en = now
    target.deactivated_en = None
    db.commit()
    registrar_evento(usuario["sub"], "policy.rollback", {"policy_id": policy_id, "scope": target.scope, "topic_key": target.topic_key})
    return {"id": target.id, "version": target.version, "status": target.status, "rolled_back": True}


@router.get("/runs")
def runs(limit: int = Query(50, ge=1, le=200), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    items = db.query(AgentRun).filter(AgentRun.user_id == usuario["sub"]).order_by(AgentRun.creado_en.desc()).limit(limit).all()
    return {"runs": [{"id": x.id, "agent": x.agent_name, "status": x.status, "created_at": x.creado_en, "finished_at": x.terminado_en, "output": json.loads(x.output_json or "{}")} for x in items]}


def _llamadas_ia_de_tarea(kind: str, payload: dict) -> int:
    """Cuántas llamadas con IA puede disparar una tarea (para el presupuesto del usuario)."""
    if kind == "agent.chat":
        return 1 if payload.get("usar_ia") else 0
    if kind == "agent.parallel" and isinstance(payload.get("requests"), list):
        return sum(1 for item in payload["requests"][:4] if isinstance(item, dict) and item.get("kind") == "agent.chat" and isinstance(item.get("payload"), dict) and item["payload"].get("usar_ia"))
    return 0


@router.post("/tasks")
def crear_task(body: TaskInput, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    if body.kind not in TASK_KINDS:
        raise HTTPException(status_code=400, detail=f"Tipo no permitido. Disponibles: {sorted(TASK_KINDS)}")
    payload = dict(body.payload)
    payload.pop("es_admin", None)  # lo fija crear_tarea con el rol real del JWT, nunca el cliente
    if body.parent_id:
        parent = db.get(AgentTask, body.parent_id)
        if parent is None or parent.user_id != usuario["sub"]:
            raise HTTPException(status_code=404, detail="Tarea padre no encontrada")
    llamadas_ia = _llamadas_ia_de_tarea(body.kind, payload)
    if llamadas_ia:
        _presupuesto_ia(usuario, llamadas_ia)
    try:
        task = crear_tarea(usuario["sub"], body.kind, payload, body.parent_id, idempotency_key=body.idempotency_key, max_attempts=body.max_attempts, timeout_seconds=body.timeout_seconds, es_admin=_es_admin(usuario))
    except LimiteExcedido as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.reintentar_en)}) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": task.id, "status": task.status, "kind": task.kind}


@router.get("/tasks")
def tareas(limit: int = Query(50, ge=1, le=200), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    items = db.query(AgentTask).filter(AgentTask.user_id == usuario["sub"]).order_by(AgentTask.creado_en.desc()).limit(limit).all()
    return {"tasks": [{"id": x.id, "parent_id": x.parent_id, "kind": x.kind, "status": x.status, "cancel_requested": bool(x.cancel_requested), "created_at": x.creado_en, "started_at": x.iniciado_en, "finished_at": x.terminado_en, "output": json.loads(x.output_json or "{}"), "error": x.error} for x in items]}


@router.get("/tasks/{task_id}")
def tarea(task_id: str, usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    item = db.get(AgentTask, task_id)
    if item is None or item.user_id != usuario["sub"]:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return {"id": item.id, "parent_id": item.parent_id, "kind": item.kind, "status": item.status, "cancel_requested": bool(item.cancel_requested), "created_at": item.creado_en, "started_at": item.iniciado_en, "finished_at": item.terminado_en, "output": json.loads(item.output_json or "{}"), "error": item.error}


@router.get("/subagents")
def subagents(_: dict = Depends(obtener_usuario_actual)) -> dict:
    return {"subagents": listar_subagentes()}


@router.post("/tasks/{task_id}/cancel")
def cancelar(task_id: str, usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    if not cancelar_tarea(task_id, usuario["sub"]):
        raise HTTPException(status_code=404, detail="Tarea no encontrada o ya terminada")
    return {"id": task_id, "cancel_requested": True}
