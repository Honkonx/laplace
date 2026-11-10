"""Aprendizaje mínimo y real del agente: políticas aprobadas y agregado de feedback.

- Una `AgentPolicyVersion` activa (aprobada por un administrador) cambia el comportamiento:
  `content_json` admite `bloquear_temas` (lista de términos que el agente trata como fuera de
  alcance) e `instrucciones` (texto breve que se añade al prompt de IA). Las de ámbito `global`
  aplican a todos; las de ámbito `usuario`, solo a quien las creó.
- El feedback con `run_id` se agrega por herramienta y modo (tasa de 👍 = rating >= 4).
"""
from __future__ import annotations

import json
import re
import unicodedata

from sqlalchemy.orm import Session

from backend.api.models.agent_runtime import AgentFeedback, AgentPolicyVersion, AgentRun

MAX_TEMAS = 50
MAX_INSTRUCCION = 600


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()).strip()


def politicas_activas(db: Session, user_id: str) -> dict:
    """Reglas vigentes para el usuario: `{"bloquear_temas": [...], "instrucciones": [...]}`."""
    filas = db.query(AgentPolicyVersion).filter(AgentPolicyVersion.status == "active").order_by(AgentPolicyVersion.topic_key).all()
    bloqueos: list[str] = []
    instrucciones: list[str] = []
    for fila in filas:
        # Lista cerrada de ámbitos: solo "global" rige para todos; "usuario" solo para su dueño. Cualquier otro
        # valor (dato antiguo o mal escrito) NO se aplica, en vez de tratarse como global por omisión.
        if fila.scope == "usuario":
            if fila.created_by != user_id:
                continue
        elif fila.scope != "global":
            continue
        try:
            contenido = json.loads(fila.content_json or "{}")
        except ValueError:
            continue
        if not isinstance(contenido, dict):
            continue
        for tema in contenido.get("bloquear_temas", []) if isinstance(contenido.get("bloquear_temas"), list) else []:
            tema_plano = _plano(str(tema))
            if 2 <= len(tema_plano) <= 60 and len(bloqueos) < MAX_TEMAS:
                bloqueos.append(tema_plano)
        texto = contenido.get("instrucciones")
        if isinstance(texto, str) and texto.strip():
            instrucciones.append(texto.strip()[:MAX_INSTRUCCION])
    return {"bloquear_temas": bloqueos, "instrucciones": instrucciones}


def tema_bloqueado(mensaje: str, politicas: dict) -> str | None:
    texto = _plano(mensaje)
    return next((tema for tema in politicas.get("bloquear_temas", []) if tema in texto), None)


def estadisticas_feedback(db: Session) -> dict:
    """Agregado de feedback ligado a ejecuciones: por herramienta y por modo."""
    filas = db.query(AgentFeedback.rating, AgentRun.output_json).join(AgentRun, AgentRun.id == AgentFeedback.run_id).all()
    por_herramienta: dict[str, list[int]] = {}
    por_modo: dict[str, list[int]] = {}
    for rating, salida in filas:
        try:
            datos = json.loads(salida or "{}")
        except ValueError:
            datos = {}
        herramienta = str(datos.get("tool") or "sin_herramienta")
        modo = str(datos.get("mode") or "desconocido").split(" · ")[0]
        por_herramienta.setdefault(herramienta, []).append(int(rating))
        por_modo.setdefault(modo, []).append(int(rating))

    def resumen(grupos: dict[str, list[int]]) -> list[dict]:
        return sorted(
            ({"clave": clave, "total": len(v), "rating_medio": round(sum(v) / len(v), 2), "tasa_pulgar_arriba": round(sum(1 for x in v if x >= 4) / len(v), 3)} for clave, v in grupos.items()),
            key=lambda item: (-item["total"], item["clave"]),
        )

    return {"total_con_run": len(filas), "por_herramienta": resumen(por_herramienta), "por_modo": resumen(por_modo), "definicion_pulgar_arriba": "rating >= 4"}
