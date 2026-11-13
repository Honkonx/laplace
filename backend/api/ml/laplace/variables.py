"""variables.py — catálogo de las variables del modelo y su cobertura por liga (MM-02).

Cada variable declara de qué columnas sale, con qué memoria y desde cuándo hay dato; el artefacto guarda la `version_variables` (huella corta de los nombres que usa) y qué ligas traen cada dato,
para que una versión diga exactamente qué usa y dónde, y para que ninguna variable use algo posterior a la fecha del partido (todas se calculan con el estado ANTES del partido).
"""
from __future__ import annotations

import hashlib
import json

CATALOGO: dict[str, dict] = {
    "sesgo": {"definicion": "constante", "columnas": [], "ventana": None},
    "dif_elo": {"definicion": "(Elo local + ventaja de local − Elo visitante) / 400", "columnas": ["goles_local", "goles_visitante"], "ventana": "K=8, multiplicador por diferencia de goles (tope 3)"},
    "log_lambda_local": {"definicion": "log de los goles esperados del local (ataque propio × defensa rival × media de la liga)", "columnas": ["goles_local", "goles_visitante"], "ventana": "memoria exponencial α=0,08"},
    "log_lambda_visitante": {"definicion": "ídem para el visitante", "columnas": ["goles_local", "goles_visitante"], "ventana": "memoria exponencial α=0,08"},
    "dif_experiencia": {"definicion": "(partidos del local − del visitante, tope 20) / 20", "columnas": [], "ventana": "toda la historia"},
    "abs_elo": {"definicion": "brecha de fuerza sin signo |dif_elo|", "columnas": ["goles_local", "goles_visitante"], "ventana": "como dif_elo"},
    "forma": {"definicion": "(puntos por partido del local − del visitante) / 3", "columnas": ["goles_local", "goles_visitante"], "ventana": "memoria exponencial α=0,15"},
    "localia": {"definicion": "dos variables: diferencia de goles del local EN CASA y del visitante FUERA, cada una menos la de la liga (localía por equipo)", "columnas": ["goles_local", "goles_visitante"], "ventana": "memoria exponencial α=0,08"},
    "tiros": {"definicion": "log(λ de tiros / media de la liga) y lo mismo para tiros a puerta, local y visitante (4 variables); 0 si la liga o el equipo no tienen tiros",
              "columnas": ["tiros_local", "tiros_visit", "tiros_arco_local", "tiros_arco_visit"], "ventana": "memoria exponencial α=0,08"},
}
BASE = ("sesgo", "dif_elo", "log_lambda_local", "log_lambda_visitante", "dif_experiencia")


def variables_usadas(extras) -> list[str]:
    return list(BASE) + [e for e in extras if e in CATALOGO]


def version_variables(extras) -> str:
    """Huella corta de las variables que usa una versión (cambia si cambia el conjunto, no si cambian sus pesos)."""
    return "vars-" + hashlib.sha256(json.dumps(variables_usadas(extras)).encode()).hexdigest()[:8]


def cobertura_por_liga(por_liga: dict[str, list[dict]], claves: tuple[str, ...] = ("tl", "tv", "al", "av")) -> dict[str, float]:
    """Fracción de partidos de cada liga que traen TODAS las claves (por defecto, los cuatro datos de tiros)."""
    salida = {}
    for codigo, partidos in por_liga.items():
        if partidos:
            salida[codigo] = sum(1 for p in partidos if all(p.get(k) is not None for k in claves)) / len(partidos)
    return salida


def ligas_con(por_liga: dict[str, list[dict]], minimo: float = 0.8, claves: tuple[str, ...] = ("tl", "tv", "al", "av")) -> list[str]:
    return sorted(c for c, f in cobertura_por_liga(por_liga, claves).items() if f >= minimo)
