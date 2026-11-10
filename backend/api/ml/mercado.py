"""ml/mercado.py — probabilidades implícitas de cuotas decimales, sin el margen de la casa.

`quitar_margen_proporcional` es el método simple (divide por el overround). `quitar_margen_shin`
(Shin 1993) asume que parte del margen protege al corredor de apostadores informados, y corrige
el sesgo favorito-longshot: reparte el margen más sobre los resultados improbables. Ninguno es
"la verdad" — se comparan por log-loss en la evaluación histórica y se usa el que mide mejor.
"""
from __future__ import annotations

import math


def cuotas_validas(*cuotas: float | None) -> bool:
    return all(c is not None and c > 1.0 and math.isfinite(c) for c in cuotas)


def quitar_margen_proporcional(h: float, d: float, a: float) -> tuple[float, float, float]:
    brutas = (1.0 / h, 1.0 / d, 1.0 / a)
    total = sum(brutas)
    return tuple(p / total for p in brutas)  # type: ignore[return-value]


def quitar_margen_shin(h: float, d: float, a: float, iteraciones: int = 100) -> tuple[float, float, float]:
    """Método de Shin por bisección sobre z (proporción de apostadores informados)."""
    brutas = [1.0 / h, 1.0 / d, 1.0 / a]
    total = sum(brutas)
    if total <= 1.0:  # sin margen (o arbitraje): no hay nada que quitar
        return tuple(p / total for p in brutas)  # type: ignore[return-value]

    def probs(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * (b * b) / total) - z) / (2 * (1 - z)) for b in brutas]

    bajo, alto = 0.0, 0.4
    for _ in range(iteraciones):
        z = (bajo + alto) / 2
        if sum(probs(z)) > 1.0:
            bajo = z
        else:
            alto = z
    p = probs((bajo + alto) / 2)
    s = sum(p)
    return tuple(x / s for x in p)  # type: ignore[return-value]
