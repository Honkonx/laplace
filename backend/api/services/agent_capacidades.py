"""Capacidades del agente y uso restante de un usuario, solo lectura.

Alimenta `GET /api/v1/agent/capabilities` y `GET /api/v1/agent/usage`. Los topes salen de las mismas
funciones de `agent_guard` que los aplican (`entero_env`), para que lo que se muestra sea lo que se exige.
Los contadores de uso se LEEN bajo el mismo candado de `agent_guard`, sin consumir cupo.
"""
from __future__ import annotations

import time
from datetime import date

from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.models.agent_runtime import AgentTask
from backend.api.services import agent_guard, ai_client, conocimiento_referencia
from backend.api.services.agent_tools import listar_herramientas_deportivas

MENSAJE_MAX_CARACTERES = 12000  # `ChatInput.message`
TIMEOUT_TAREA_MAX_SEGUNDOS = 120  # `TaskInput.timeout_seconds`


def proveedores_ia_configurados() -> list[str]:
    """Proveedores del rol «agente» con credencial presente, en orden de cascada. Nunca expone la credencial."""
    return [n for n in ai_client.orden_proveedores("agente") if ai_client._PROVEEDORES[n].configurado()]


def limites(es_admin: bool) -> dict:
    return {
        "ia_por_minuto": agent_guard.entero_env("AGENT_IA_MAX_POR_MINUTO", 5),
        "ia_por_dia": agent_guard.entero_env("AGENT_IA_MAX_POR_DIA", 60) * (5 if es_admin else 1),
        "tareas_activas_max": agent_guard.entero_env("AGENT_MAX_TAREAS_ACTIVAS", 10),
        "mensaje_max_caracteres": MENSAJE_MAX_CARACTERES,
        "timeout_tarea_max_segundos": TIMEOUT_TAREA_MAX_SEGUNDOS,
        "aprobacion_vigencia_segundos": agent_guard.entero_env("AGENT_APPROVAL_TTL_SECONDS", 3600),
    }


def _herramienta(t: dict) -> dict:
    return {"name": t["name"], "description": t["description"], "read_only": t["read_only"], "admin_only": t["admin_only"],
            "requires_confirmation": t["requires_confirmation"], "category": "conocimiento" if t["name"].startswith("knowledge.") else "deportiva"}


def capacidades(es_admin: bool) -> dict:
    proveedores = proveedores_ia_configurados()
    return {
        "rol": "admin" if es_admin else "usuario",
        "modos": [
            {"id": "reglas", "disponible": True, "descripcion": "Respuestas deterministas desde datos y reglas; no usa IA."},
            {"id": "ia", "disponible": bool(settings.AGENT_IA_ACTIVA and proveedores), "proveedores_configurados": len(proveedores),
             "proveedores": proveedores if es_admin else [],
             "descripcion": "Conversación y redacción con un proveedor de IA; las cifras siempre salen de los datos verificados."},
        ],
        "herramientas": [_herramienta(t) for t in listar_herramientas_deportivas(es_admin=es_admin)],
        "limites": limites(es_admin),
        "conocimiento": conocimiento_referencia.version_conocimiento(),
    }


def cupo_ia(usuario: str, es_admin: bool) -> dict:
    """Cupo de IA restante del usuario (minuto y día) sin gastar nada."""
    tope = limites(es_admin)
    ahora = time.monotonic()
    ventana, usadas_dia = agent_guard.consultar_uso_ia(usuario)
    reinicia = int(60 - (ahora - ventana[0])) + 1 if ventana else None
    return {
        "por_minuto": {"limite": tope["ia_por_minuto"], "usadas": len(ventana), "restantes": max(tope["ia_por_minuto"] - len(ventana), 0), "reinicia_en_segundos": reinicia},
        "por_dia": {"limite": tope["ia_por_dia"], "usadas": usadas_dia, "restantes": max(tope["ia_por_dia"] - usadas_dia, 0)},
    }


def uso(db: Session, usuario: str, es_admin: bool) -> dict:
    activas = db.query(AgentTask).filter(AgentTask.user_id == usuario, AgentTask.status.in_(["queued", "running"])).count()
    return {"fecha": date.today().isoformat(), "rol": "admin" if es_admin else "usuario", "ia_activa": bool(settings.AGENT_IA_ACTIVA),
            **cupo_ia(usuario, es_admin), "tareas_activas": activas, "tareas_activas_max": limites(es_admin)["tareas_activas_max"]}
