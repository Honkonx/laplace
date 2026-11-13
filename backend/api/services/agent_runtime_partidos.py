"""services/agent_runtime_partidos.py — selección de fixtures y fechas naturales para el agente."""
from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher

from backend.api.services import agent_jerga
from backend.api.services.agent_runtime_reglas import _texto_normalizado


def _similitud_equipo(consulta: str, candidato: str) -> float:
    a, b = _texto_normalizado(consulta), _texto_normalizado(candidato)
    return SequenceMatcher(None, a, b).ratio()


def _seleccionar_fixture(fixtures: list[dict], local: str, visitante: str) -> dict | None:
    """Resuelve errores tipográficos sin elegir arbitrariamente un partido distinto."""
    exacto = next((item for item in fixtures if _texto_normalizado(str(item.get("local", ""))) == _texto_normalizado(local) and _texto_normalizado(str(item.get("visitante", ""))) == _texto_normalizado(visitante)), None)
    if exacto:
        return exacto
    mejor, score = None, 0.0
    for item in fixtures:
        actual = (_similitud_equipo(local, str(item.get("local", ""))) + _similitud_equipo(visitante, str(item.get("visitante", "")))) / 2
        if actual > score:
            mejor, score = item, actual
    return mejor if score >= 0.72 else None


def _fecha_natural(mensaje: str, hoy: date | None = None) -> str:
    """AAAAMMDD de la fecha que dice el mensaje (MS-7): hoy, mañana, pasado mañana, ayer, un día de la semana o «este finde»; hoy si no dice ninguna."""
    return agent_jerga.fecha(mensaje, hoy).strftime("%Y%m%d")


def _normalizar_fixture(item: dict) -> dict:
    return {"match_id": str(item.get("match_id", item.get("fixture_id", item.get("id", "")))), "local": str(item.get("local", item.get("home", ""))), "visitante": str(item.get("visitante", item.get("away", ""))), "league": str(item.get("liga", item.get("league", "")))}
