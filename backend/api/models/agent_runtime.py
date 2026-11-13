"""Persistencia del runtime conversacional y de tareas del agente Laplace."""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    modo: Mapped[str] = mapped_column(String(32), nullable=False, default="reglas")
    herramienta: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="laplace")
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="agent")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    activo: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sensibilidad: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    expira_en: Mapped[str | None] = mapped_column(String(32), nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentMemoryHistory(Base):
    """Historial append-only de altas, cambios y bajas lógicas de memoria."""

    __tablename__ = "agent_memory_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentKnowledge(Base):
    __tablename__ = "agent_knowledge"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    topic_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, default="laplace")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded")
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    terminado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    iniciado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)
    terminado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentLearningProposal(Base):
    __tablename__ = "agent_learning_proposals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_key: Mapped[str] = mapped_column(String(255), nullable=False)
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    revisado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AgentToolInvocation(Base):
    """Auditoría de cada herramienta solicitada desde un canal del agente."""

    __tablename__ = "agent_tool_invocations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    terminado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AgentEvent(Base):
    """Evento append-only de tareas, herramientas y decisiones del agente."""

    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentApproval(Base):
    """Aprobación humana persistente para acciones externas o sensibles."""

    __tablename__ = "agent_approvals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invocation_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="pending")
    requested_en: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_en: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentPolicyVersion(Base):
    """Versión revisable de una regla o conocimiento propuesto por aprendizaje."""

    __tablename__ = "agent_policy_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    topic_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="draft")
    content_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_en: Mapped[str] = mapped_column(String(32), nullable=False)
    activated_en: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deactivated_en: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AgentUsoDiario(Base):
    """Contador diario de uso por usuario (IA y predicciones) que sobrevive a los reinicios (MA-51). Guarda solo cuántas veces, nunca contenido."""

    __tablename__ = "agent_uso_diario"
    clave: Mapped[str] = mapped_column(String(255), primary_key=True)  # "<usuario>" para IA, "<usuario>:pred" para predicciones
    dia: Mapped[str] = mapped_column(String(10), primary_key=True)
    usos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
