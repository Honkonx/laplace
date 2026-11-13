"""services/agent_guardia_chat.py — en la charla libre la IA no produce probabilidades ni marcadores (H-008, 2026-11-11).

Regla de producto: «la IA explica y contrasta; las probabilidades salen de modelos medidos». Con el modo de charla libre, una IA podía contestar «el local tiene 87 % de ganar, marcador seguro 4-0»
con solo la etiqueta «no verificada». Aquí se detecta en código (no se le pide a la IA que se porte bien): si el texto trae un porcentaje, un marcador o una promesa de resultado que la
persona no escribió, se reemplaza por un aviso que la manda al camino medido.
"""
from __future__ import annotations

import re

_PORCENTAJE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_MARCADOR = re.compile(r"(?<![\d.:/])\b\d{1,2}\s*[-–]\s*\d{1,2}\b(?![\d.:/])")
_PROMESA = re.compile(r"\b(?:seguro|segura|garantizad[oa]s?|asegurad[oa]s?|fij[oa]s?|sin duda|100 ?%)\b.{0,30}\b(?:gana|ganar|ganará|resultado|marcador|pick|apuesta)\b", re.I)
AVISO = ("No puedo darte probabilidades, porcentajes ni marcadores desde la charla: solo salen del bot o del modelo, medidos y con respaldo. "
         "Pídeme «analiza Equipo A vs Equipo B» y te los muestro.")


def _figuras(texto: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0)) for rx in (_PORCENTAJE, _MARCADOR) for m in rx.finditer(texto)}


def sanear_charla(texto: str, mensaje_usuario: str) -> tuple[str, bool]:
    """(texto seguro, ¿se reemplazó?). Se permite repetir una cifra que la persona misma escribió (p. ej. «over 2.5», «1-0»)."""
    ajenas = _figuras(texto) - _figuras(mensaje_usuario)
    if ajenas or _PROMESA.search(texto):
        return AVISO, True
    return texto, False
