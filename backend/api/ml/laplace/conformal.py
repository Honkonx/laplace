"""ml/laplace/conformal.py — predicción conforme (split conformal) para el 1X2: un CONJUNTO de resultados plausibles con cobertura garantizada, en vez de una cifra con falsa precisión.

Idea (Vovk, Angelopoulos y Bates): con una muestra de calibración de partidos ya jugados se mide, para cada uno, cuán «sorprendente» fue el resultado real: `s = 1 − p(resultado real)`. El umbral `q̂` es el cuantil
⌈(n+1)(1−α)⌉/n de esas puntuaciones; para un partido nuevo, el conjunto es {resultados con 1 − p ≤ q̂}. Si los partidos son intercambiables, el conjunto contiene el resultado real con probabilidad ≥ 1 − α.
La garantía es MARGINAL (promedio sobre partidos), no por partido, y exige intercambiabilidad: por eso `evaluar_conformal.py` mide la cobertura real fuera de muestra y por liga antes de usarlo en producto.

No cambia las probabilidades del modelo: solo dice cuántos resultados siguen siendo plausibles (con un 1X2 de ~50 % de acierto, un conjunto al 90 % suele traer 2-3 de los 3 resultados, y eso es información honesta).
"""
from __future__ import annotations

import math

CLASES = ("H", "D", "A")


def puntuacion(p: tuple[float, float, float], resultado: str) -> float:
    """Cuán sorprendente fue el resultado real: 1 − p(resultado)."""
    return 1.0 - p[CLASES.index(resultado)]


def umbral(puntuaciones: list[float], alfa: float) -> float | None:
    """Cuantil ⌈(n+1)(1−α)⌉/n de las puntuaciones de calibración; None si no hay muestra suficiente para la cobertura pedida (devolver el conjunto completo es lo seguro)."""
    n = len(puntuaciones)
    k = math.ceil((n + 1) * (1.0 - alfa))
    if n == 0 or k > n:
        return None
    return sorted(puntuaciones)[k - 1]


def conjunto(p: tuple[float, float, float], q: float | None) -> tuple[str, ...]:
    """Resultados plausibles (en el orden H, D, A). Sin umbral (muestra insuficiente) se devuelven los tres: nunca se excluye algo sin respaldo. Nunca queda vacío: se incluye al menos el más probable."""
    if q is None:
        return CLASES
    incluidos = tuple(c for c, pc in zip(CLASES, p) if 1.0 - pc <= q)
    return incluidos or (CLASES[max(range(3), key=lambda i: p[i])],)


def cobertura_y_tamano(casos: list[tuple[tuple[float, float, float], str]], q: float | None) -> tuple[float, float]:
    """(fracción de casos cuyo resultado real está en el conjunto, tamaño medio del conjunto)."""
    if not casos:
        return 0.0, 0.0
    dentro = sum(1 for p, r in casos if r in conjunto(p, q))
    tam = sum(len(conjunto(p, q)) for p, _ in casos) / len(casos)
    return dentro / len(casos), tam
