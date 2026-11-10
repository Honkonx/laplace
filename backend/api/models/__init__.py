"""models/__init__.py — importa todos los modelos para que Base.metadata los conozca.

Necesario para que Alembic autogenerate detecte las tablas (mismo patrón que
alembic/env.py de PAGINA1 — importa los modelos explícitamente, no confía en descubrimiento
automático).
"""
from backend.api.models.auditoria import AccionAdminAuditoria, HistorialPlan, IntentoLoginFallido
from backend.api.models.agent_runtime import AgentApproval, AgentEvent, AgentFeedback, AgentKnowledge, AgentLearningProposal, AgentMemory, AgentMemoryHistory, AgentMessage, AgentPolicyVersion, AgentRun, AgentSession, AgentTask, AgentToolInvocation
from backend.api.models.jobs import Job
from backend.api.models.metricas import EstadoFuenteDeportiva, MetricaIaProveedor
from backend.api.models.laplace_agents import LaplaceAgentMemoria
from backend.api.models.partidos import (
    FixtureIdCache,
    PartidoDia,
    RecomendacionDia,
    ResultadoPartido,
    StatsCache,
)
from backend.api.models.predicciones import (
    AnalisisComparativo,
    AnalisisIndividual,
    AnalisisModulo,
    CacheConsenso,
    CachePrediccion,
    ConsensoIaValidacion,
    Prediccion,
    PrediccionUsuario,
    HistorialPrediccionWeb,
    PrediccionVarianteAgente,
    ExperimentoPronostico,
    PronosticoExperimental,
)
from backend.api.models.push import PushToken
from backend.api.models.scheduler import SchedulerRun
from backend.api.models.tokens import TokenRevocado
from backend.api.models.usuarios import CodigoAcceso, UsoDiarioApp, UsoDiarioIaApp, Usuario

__all__ = [
    "Job",
    "MetricaIaProveedor",
    "EstadoFuenteDeportiva",
    "LaplaceAgentMemoria",
    "FixtureIdCache",
    "PartidoDia",
    "RecomendacionDia",
    "ResultadoPartido",
    "StatsCache",
    "AnalisisComparativo",
    "AnalisisIndividual",
    "AnalisisModulo",
    "CacheConsenso",
    "CachePrediccion",
    "ConsensoIaValidacion",
    "Prediccion",
    "PrediccionUsuario",
    "HistorialPrediccionWeb",
    "PrediccionVarianteAgente",
    "ExperimentoPronostico",
    "PronosticoExperimental",
    "PushToken",
    "SchedulerRun",
    "CodigoAcceso",
    "UsoDiarioApp",
    "UsoDiarioIaApp",
    "Usuario",
    "TokenRevocado",
    "HistorialPlan",
    "IntentoLoginFallido",
    "AccionAdminAuditoria",
    "AgentSession",
    "AgentMessage",
    "AgentMemory",
    "AgentMemoryHistory",
    "AgentKnowledge",
    "AgentRun",
    "AgentTask",
    "AgentFeedback",
    "AgentLearningProposal",
    "AgentToolInvocation",
    "AgentEvent",
    "AgentApproval",
    "AgentPolicyVersion",
]
