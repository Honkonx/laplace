"""services/normalizacion.py — Helpers de normalización/matching de nombres de equipos.

Port de las funciones correspondientes en utils.py — usadas por
services/gateway.py para matchear equipos entre fuentes distintas (BSD, api-football,
LiveScore6 no tienen los mismos IDs).
"""
from __future__ import annotations

import re
import unicodedata


def normalizar_nombre(texto: str | None) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]", "", sin_acentos.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def score_similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0
    if a == b:
        return 100
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a:
        return 0
    comunes = tokens_a & tokens_b
    score = len(comunes) / len(tokens_a) * 100
    if a in b or b in a:
        score = max(score, 80)
    return round(score, 1)


def coincide_nombre(nombre_api: str, nombre_input: str) -> bool:
    a = normalizar_nombre(nombre_api)
    b = normalizar_nombre(nombre_input)
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return True
    wa = [w for w in a.split() if len(w) >= 4]
    wb = [w for w in b.split() if len(w) >= 4]
    return bool(wa and wb and wa[0] == wb[0])


def nombre_equipo_bsd(campo: object) -> str:
    """BSD API (bzzoiro.com) no es consistente en el shape de `home_team`/`away_team` en
    `/events/`: normalmente es `{"name": "..."}`, pero se confirmó en producción (2026-09-05,
    bug real que rompía TODO análisis que caía al fallback BSD de H2H) que a veces devuelve el
    nombre como string plano directo. Esta función normaliza ambos casos — usar SIEMPRE esto
    en vez de `(campo or {}).get("name", "")` para leer un team de BSD."""
    if isinstance(campo, dict):
        return campo.get("name") or ""
    if isinstance(campo, str):
        return campo
    return ""


def limpiar_sufijos(nombre: str) -> str:
    sufijos = [" W", " U17", " U19", " U20", " U21", " B", " II", " Reserves"]
    n = nombre
    for s in sufijos:
        if n.upper().endswith(s.upper()):
            n = n[: len(n) - len(s)].strip()
            break
    return n
