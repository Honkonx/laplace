"""services/agent_dialogo.py — estado de diálogo por sesión: seguimientos cortos que heredan el último partido (MA-31).

«¿Y mañana?», «¿y las cuotas?», «¿y el over 2.5?», «¿y con IA?» no traen equipos: se reescriben usando el último partido que el usuario nombró en la sesión. Si no hay partido previo
(o el mensaje no es un seguimiento claro) no se toca nada y el enrutador normal decide. La herencia es visible: el mensaje reescrito queda en la ejecución (`routed_message`).
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from backend.api.models.agent_runtime import AgentMessage, AgentSession
from backend.api.services.agent_runtime_reglas import _normalizar_humano, _partido_desde_mensaje, _texto_normalizado

TURNOS_ATRAS = 8
MAX_PALABRAS = 7


def ultimo_partido(db: Session, sesion: AgentSession) -> tuple[tuple[str, str], str] | None:
    """((local, visitante), fecha 'hoy'|'mañana'|'') del último partido que el usuario nombró en la sesión."""
    filas = db.query(AgentMessage).filter(AgentMessage.session_id == sesion.id, AgentMessage.role == "user").order_by(AgentMessage.id.desc()).limit(TURNOS_ATRAS).all()
    for fila in filas:
        partido = _partido_desde_mensaje(fila.content)
        if partido:
            fecha = "mañana" if re.search(r"manana|mañana", _texto_normalizado(fila.content)) else ""
            return partido, fecha
    return None


def reescribir(mensaje: str, partido: tuple[str, str], fecha: str = "") -> str | None:
    """Mensaje completo equivalente al seguimiento, o None si no es un seguimiento reconocible."""
    texto = _texto_normalizado(_normalizar_humano(mensaje)).strip(" ?!.,")
    if not texto.startswith("y ") or len(texto.split()) > MAX_PALABRAS:
        return None
    a, b = partido
    cola = texto[2:].strip()
    if re.fullmatch(r"(?:el |para )?manana", cola):
        return f"analiza {a} vs {b} mañana"
    if re.fullmatch(r"(?:el |para )?hoy", cola):
        return f"analiza {a} vs {b}"
    if re.search(r"\bcuotas?\b|\bodds\b|\bmercado\b", cola):
        return f"cuotas {a} vs {b}" + (f" {fecha}" if fecha else "")
    if re.search(r"\bover\b|\bunder\b|mas de|menos de", cola):
        linea = re.search(r"\d(?:[.,]\d)?", cola)
        return f"over {linea.group(0).replace(',', '.') if linea else '2.5'} en {a} vs {b}"
    if re.search(r"ambos marcan|\bbtts\b", cola):
        return f"ambos marcan en {a} vs {b}"
    if re.search(r"solo ia|con ia|\bia\b", cola):
        return f"predicción solo IA {a} vs {b}" + (f" {fecha}" if fecha else "")
    if re.search(r"\bbot\b|estadistic", cola):
        return f"predicción bot {a} vs {b}" + (f" {fecha}" if fecha else "")
    if re.fullmatch(r"(?:el |la )?(?:visitante|local|empate|visita)", cola) or re.search(r"\bquien gana\b|\bprobabilidad", cola):
        return f"analiza {a} vs {b}" + (f" {fecha}" if fecha else "")
    return None


def seguimiento(db: Session, sesion: AgentSession, mensaje: str) -> str | None:
    """Reescribe el seguimiento con el último partido de la sesión; None si no aplica."""
    previo = ultimo_partido(db, sesion)
    return reescribir(mensaje, previo[0], previo[1]) if previo else None
