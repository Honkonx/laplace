"""ml/evaluacion_consenso.py — piezas puras (sin numpy) para medir el consenso REAL con histórico.

Reutilizan `services/consenso.calcular_consenso` tal cual (no reimplementan la votación): solo
sustituyen temporalmente `PESOS_BASE` para evaluar pesos candidatos y reconstruyen el dict de
resultados por módulo que el consenso espera. El script `backend/scripts/evaluar_consenso_historico.py`
añade lo que sí necesita numpy/scikit-learn (regresión logística, optimización de pesos, bootstrap).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from contextlib import contextmanager

from backend.api.ml import metricas
from backend.api.services import consenso

ETIQUETAS = ("Local", "Empate", "Visitante")
RESULTADO_A_ETIQUETA = {"H": "Local", "D": "Empate", "A": "Visitante"}


@contextmanager
def pesos_consenso(pesos: dict[str, float] | None):
    """Sustituye `consenso.PESOS_BASE` durante el bloque (módulos no listados quedan en 0)."""
    original = dict(consenso.PESOS_BASE)
    try:
        if pesos is not None:
            consenso.PESOS_BASE.update({m: float(pesos.get(m, 0.0)) for m in original})
        yield
    finally:
        consenso.PESOS_BASE.clear()
        consenso.PESOS_BASE.update(original)


def a_resultados(modulos: dict[str, tuple], pesos: dict[str, float] | None = None) -> dict[str, dict]:
    """{modulo: (p_local, p_empate, p_visit, confianza_score)} -> dict de `consenso.calcular_consenso`.

    Con `pesos` se omiten los módulos de peso 0: un módulo "ok" con peso 0 seguiría contando en el
    número de módulos y en los bonus del score, así que quitarlo equivale a que el motor lo saltara."""
    salida: dict[str, dict] = {}
    for nombre, (ph, pd_, pa, score) in modulos.items():
        if pesos is not None and pesos.get(nombre, 0.0) <= 0:
            continue
        salida[nombre] = {
            "ok": True, "pick": ETIQUETAS[max(range(3), key=lambda i: (ph, pd_, pa)[i])],
            "prob_local": ph, "prob_empate": pd_, "prob_visitante": pa, "confianza_score": score,
        }
    return salida


def evaluar_consenso(modulos: dict[str, tuple], pesos: dict[str, float] | None = None) -> dict | None:
    """Corre el consenso real sobre los módulos dados. None si no queda ningún módulo."""
    resultados = a_resultados(modulos, pesos)
    if not resultados:
        return None
    with pesos_consenso(pesos):
        c = consenso.calcular_consenso(resultados)
    pp = c["prob_ponderada"]
    probs = (pp["local"], pp["empate"], pp["visitante"])
    return {
        "probs": probs, "pick": c["pick_final"], "idx": max(range(3), key=lambda i: probs[i]),
        "nivel": c["nivel"], "score": c["score_consenso"], "confianza": c["confianza_final"],
        "n_modulos": c["total_modulos"], "modulos_ok": sorted(resultados),
    }


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centro - margen, 4), round(centro + margen, 4))


def tabla_por_grupos(filas: Iterable[dict], clave: Callable[[dict], str | None]) -> list[dict]:
    """Frecuencia real de acierto del pick por grupo. Cada fila: {probs, res} (res en H/D/A) más lo
    que lea `clave`. Devuelve n, accuracy (IC Wilson 95%), probabilidad media del pick y log-loss."""
    grupos: dict[str, list[dict]] = {}
    for f in filas:
        k = clave(f)
        if k is not None:
            grupos.setdefault(k, []).append(f)
    salida = []
    for k in sorted(grupos):
        g = grupos[k]
        aciertos = sum(1 for f in g if max(range(3), key=lambda i: f["probs"][i]) == metricas.INDICE[f["res"]])
        n = len(g)
        lo, hi = wilson(aciertos, n)
        salida.append({
            "grupo": k, "n": n, "accuracy": round(aciertos / n, 4), "ic95": [lo, hi],
            "prob_media_pick": round(sum(max(f["probs"]) for f in g) / n, 4),
            "log_loss": round(sum(metricas.log_loss(f["probs"], f["res"]) for f in g) / n, 4),
        })
    return salida


def distribucion_picks(filas: Iterable[dict]) -> dict:
    """Reparto de picks (H/D/A) frente al reparto real de resultados: detecta sesgo a Empate."""
    picks = [0, 0, 0]
    reales = [0, 0, 0]
    for f in filas:
        picks[max(range(3), key=lambda i: f["probs"][i])] += 1
        reales[metricas.INDICE[f["res"]]] += 1
    n = sum(picks) or 1
    return {"picks": {e: round(c / n, 4) for e, c in zip("HDA", picks)},
            "reales": {e: round(c / n, 4) for e, c in zip("HDA", reales)}, "n": sum(picks)}
