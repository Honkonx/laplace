"""Hipótesis conversacional mínima para el laboratorio de pronósticos.

No forma parte del motor ni del consenso. Sólo recibe los nombres de los equipos y la
competición; su salida queda congelada para compararla después contra el marcador oficial.
"""
from __future__ import annotations

import json
import re

from backend.api.services.ai_client import AnalisisIAError, generar_texto_ia_con_meta

PROMPT_VERSION = "ia-scout-v1"


def construir_prompt(local: str, visitante: str, liga: str) -> str:
    return f"""Eres un observador experimental de fútbol. No uses datos inventados ni presentes esto como consejo de apuesta.
Con sólo los nombres del partido, entrega una hipótesis conservadora para registrar y evaluar después.
Partido: {local} vs {visitante}. Competición: {liga}.
Responde exclusivamente JSON válido, sin markdown:
{{"pick":"local|empate|visitante","prob_local":0.00,"prob_empate":0.00,"prob_visitante":0.00,"marcador_probable":"0-0"}}
Las tres probabilidades deben sumar 1.00. Si no hay base suficiente, usa probabilidades cercanas y no inventes lesiones, forma ni estadísticas."""


def _extraer_json(texto: str) -> dict:
    limpio = texto.strip()
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio, flags=re.IGNORECASE)
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio < 0 or fin < inicio:
        raise ValueError("la IA no devolvió JSON")
    data = json.loads(limpio[inicio:fin + 1])
    if not isinstance(data, dict):
        raise ValueError("la IA no devolvió un objeto JSON")
    pick = str(data.get("pick") or "").strip().casefold()
    if pick not in {"local", "empate", "visitante"}:
        raise ValueError("pick IA inválido")
    try:
        probs = [float(data[key]) for key in ("prob_local", "prob_empate", "prob_visitante")]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("probabilidades IA incompletas") from exc
    if any(p < 0 or p > 1 for p in probs) or not 0.98 <= sum(probs) <= 1.02:
        raise ValueError("probabilidades IA inválidas")
    total = sum(probs)
    return {
        "pick": pick,
        "prob_local": round(probs[0] / total, 4),
        "prob_empate": round(probs[1] / total, 4),
        "prob_visitante": round(probs[2] / total, 4),
        "marcador_probable": str(data.get("marcador_probable") or "")[:32] or None,
    }


async def generar_hipotesis(local: str, visitante: str, liga: str) -> tuple[dict, str, str, str]:
    """Devuelve hipótesis validada, respuesta cruda, proveedor y modelo."""
    try:
        texto, proveedor, modelo = await generar_texto_ia_con_meta(
            construir_prompt(local, visitante, liga), max_tokens=180, temperature=0.2, rol="laboratorio"
        )
    except AnalisisIAError:
        raise
    return _extraer_json(texto), texto, proveedor, modelo
