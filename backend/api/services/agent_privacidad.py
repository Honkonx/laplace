"""services/agent_privacidad.py — privacidad del agente: redacción de secretos y datos personales, modo incógnito y borrado en cascada (MA-41, MA-42).

- `redactar` enmascara claves, tokens, correos y números largos ANTES de guardar un mensaje y antes de enviarlo al proveedor de IA.
- `incognito`: mientras esté activo el agente responde pero no guarda mensajes, ejecuciones ni memoria (vive en el proceso: al reiniciar vuelve a lo normal, que es lo conservador).
- `olvidar_usuario` borra todo lo de un usuario; las tablas de auditoría se anonimizan para no perder la trazabilidad de seguridad. Una prueba falla si aparece una tabla `agent_*` que no esté
  clasificada aquí (MA-41).
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.models.agent_runtime import (
    AgentApproval,
    AgentEvent,
    AgentFeedback,
    AgentMemory,
    AgentMemoryHistory,
    AgentMessage,
    AgentRun,
    AgentSession,
    AgentTask,
    AgentToolInvocation,
)

ANONIMO = "usuario-olvidado"
# (modelo, columna del usuario) que se BORRAN
TABLAS_A_BORRAR = (
    (AgentMessage, "user_id"), (AgentRun, "user_id"), (AgentSession, "user_id"), (AgentTask, "user_id"), (AgentFeedback, "user_id"),
    (AgentMemory, "owner_id"), (AgentMemoryHistory, "owner_id"),
)
# se conservan sin identificar al usuario (auditoría de seguridad)
TABLAS_A_ANONIMIZAR = ((AgentApproval, "user_id"), (AgentEvent, "user_id"), (AgentToolInvocation, "user_id"))
# no son del usuario: conocimiento, políticas y propuestas globales
TABLAS_GLOBALES = frozenset({"agent_knowledge", "agent_learning_proposals", "agent_policy_versions", "agent_uso_diario"})  # agent_uso_diario: solo conteos; borrarla devolvería el cupo al usuario

_PATRONES = (
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "[clave]"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "[token]"),
    (re.compile(r"\bAIzaSy[A-Za-z0-9_-]{30,}"), "[clave]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "[token]"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"), "[token-telegram]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[jwt]"),
    (re.compile(r"(?i)\b(bearer|authorization:?)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [token]"),
    (re.compile(r"(?i)\b(clave|contraseña|contrasena|password|passwd|token|secret|api[_ -]?key)\s*(?:es|=|:)\s*\S{6,}"), r"\1 [oculto]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[correo]"),
    (re.compile(r"(?<![\d.])(?:\d[ -]?){13,19}(?![\d])"), "[número]"),
)

_INCOGNITO: set[str] = set()


def redactar(texto: str) -> tuple[str, int]:
    """(texto enmascarado, cuántos fragmentos se enmascararon)."""
    total = 0
    for patron, reemplazo in _PATRONES:
        texto, n = patron.subn(reemplazo, texto)
        total += n
    return texto, total


def activar_incognito(user_id: str) -> None:
    _INCOGNITO.add(str(user_id))


def desactivar_incognito(user_id: str) -> None:
    _INCOGNITO.discard(str(user_id))


def en_incognito(user_id: str) -> bool:
    return str(user_id) in _INCOGNITO


def olvidar_usuario(db: Session, user_id: str) -> dict:
    """Borra mensajes, ejecuciones, sesiones, tareas, comentarios y memorias del usuario (y su índice de búsqueda), y anonimiza la auditoría. Devuelve cuántas filas tocó en cada tabla."""
    uid = str(user_id)
    hecho: dict[str, int] = {}
    # el índice de búsqueda (FTS5, solo SQLite) no se borra en cascada: se limpia a mano antes que las tablas de origen
    try:
        hecho["agent_search_fts"] = db.execute(text("DELETE FROM agent_search_fts WHERE owner_id = :u"), {"u": uid}).rowcount or 0
    except Exception:  # noqa: BLE001 — en otros motores o sin la tabla virtual no hay índice que limpiar
        db.rollback()
    for modelo, columna in TABLAS_A_BORRAR:
        hecho[modelo.__tablename__] = db.query(modelo).filter(getattr(modelo, columna) == uid).delete(synchronize_session=False)
    for modelo, columna in TABLAS_A_ANONIMIZAR:
        hecho[modelo.__tablename__] = db.query(modelo).filter(getattr(modelo, columna) == uid).update({columna: ANONIMO}, synchronize_session=False)
    db.commit()
    desactivar_incognito(uid)
    return hecho
