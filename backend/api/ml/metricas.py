"""ml/metricas.py — métricas de probabilidades 1X2 (Local, Empate, Visitante).

Todas reciben `probs` = (p_local, p_empate, p_visitante) y `resultado` en {"H", "D", "A"}.
Menor es mejor en las tres. Referencias de escala para fútbol de 3 resultados: pronosticar
siempre la tasa base da RPS ≈ 0.23 y log-loss ≈ 1.09; un buen modelo de mercado ronda RPS ≈ 0.19.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

INDICE = {"H": 0, "D": 1, "A": 2}
EPS = 1e-12


def _one_hot(resultado: str) -> tuple[float, float, float]:
    return tuple(1.0 if i == INDICE[resultado] else 0.0 for i in range(3))  # type: ignore[return-value]


def rps(probs: tuple[float, float, float], resultado: str) -> float:
    """Ranked Probability Score (Epstein 1969): penaliza menos fallar por una categoría vecina."""
    o = _one_hot(resultado)
    c1p, c2p = probs[0], probs[0] + probs[1]
    c1o, c2o = o[0], o[0] + o[1]
    return 0.5 * ((c1p - c1o) ** 2 + (c2p - c2o) ** 2)


def brier(probs: tuple[float, float, float], resultado: str) -> float:
    o = _one_hot(resultado)
    return sum((p - x) ** 2 for p, x in zip(probs, o))


def log_loss(probs: tuple[float, float, float], resultado: str) -> float:
    return -math.log(max(probs[INDICE[resultado]], EPS))


def promedio(metrica, predicciones: Iterable[tuple[tuple[float, float, float], str]]) -> float | None:
    valores = [metrica(p, r) for p, r in predicciones]
    return sum(valores) / len(valores) if valores else None


def resumen(predicciones: list[tuple[tuple[float, float, float], str]]) -> dict:
    """RPS/Brier/log-loss promedio y accuracy del pick de mayor probabilidad."""
    n = len(predicciones)
    if n == 0:
        return {"n": 0, "rps": None, "brier": None, "log_loss": None, "accuracy": None}
    aciertos = sum(1 for p, r in predicciones if max(range(3), key=lambda i: p[i]) == INDICE[r])
    return {
        "n": n,
        "rps": round(promedio(rps, predicciones), 5),
        "brier": round(promedio(brier, predicciones), 5),
        "log_loss": round(promedio(log_loss, predicciones), 5),
        "accuracy": round(aciertos / n, 4),
    }
