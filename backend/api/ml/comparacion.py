"""comparacion.py — ¿la diferencia entre dos pronósticos es real o ruido? (MM-00 del plan del modelo: el plan de mejoras (repo de trabajo)).

Compara dos listas de pronósticos sobre LOS MISMOS partidos con la pérdida (log loss por defecto; menos es mejor) y devuelve: diferencia media por partido (positiva = `b` mejor que `a`),
error estándar, estadístico z, prueba de Diebold-Mariano con la corrección de Harvey-Leybourne-Newbold (horizonte 1) e intervalo del 95 % por bootstrap en bloques (los partidos de una
misma semana se parecen entre sí: remuestrear partidos sueltos subestima el error). Solo librería estándar: el arnés corre también donde no hay numpy.
Un cambio al modelo se acepta con z ≥ 3 y ≥ 0,001 de log loss (`07` §1); todo experimento, aceptado o rechazado, se anota en `registro_experimentos.md`.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

from backend.api.ml import metricas

Prediccion = tuple[tuple[float, float, float], str]


def _normal_sf2(z: float) -> float:
    """P(|Z| > |z|) de una normal estándar."""
    return math.erfc(abs(z) / math.sqrt(2))


def comparar_perdidas(perdida_a: Sequence[float], perdida_b: Sequence[float], bloques: Sequence[int] | None = None, n_boot: int = 1000, semilla: int = 7) -> dict:
    """Diferencia pareada d_i = perdida_a[i] - perdida_b[i] (positiva = `b` mejor). `bloques[i]` agrupa partidos (p. ej. semana) para el bootstrap."""
    n = len(perdida_a)
    if n != len(perdida_b) or n < 3:
        raise ValueError("se necesitan al menos 3 partidos y listas de igual largo")
    d = [a - b for a, b in zip(perdida_a, perdida_b)]
    media = sum(d) / n
    var = sum((x - media) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    z = media / se if se > 0 else 0.0
    hln = math.sqrt((n - 1) / n)  # corrección de Harvey-Leybourne-Newbold con horizonte 1
    z_hln = z * hln
    salida = {"n": n, "diferencia_media": media, "error_estandar": se, "z": z, "dm_hln": z_hln,
              "p_dm_hln": _normal_sf2(z_hln),  # aproximación normal (la t de n-1 grados es indistinguible con n grande)
              "perdida_a": sum(perdida_a) / n, "perdida_b": sum(perdida_b) / n}
    ids = list(bloques) if bloques is not None else list(range(n))
    suma: dict[int, float] = {}
    cuenta: dict[int, int] = {}
    for i, x in zip(ids, d):
        suma[i] = suma.get(i, 0.0) + x
        cuenta[i] = cuenta.get(i, 0) + 1
    claves = list(suma)
    rng = random.Random(semilla)
    medias = []
    for _ in range(n_boot):
        elegidos = [claves[rng.randrange(len(claves))] for _ in claves]
        medias.append(sum(suma[k] for k in elegidos) / sum(cuenta[k] for k in elegidos))
    medias.sort()
    salida["ic95"] = (medias[int(0.025 * (n_boot - 1))], medias[int(0.975 * (n_boot - 1))])
    salida["bloques"] = len(claves)
    return salida


def comparar_predicciones(a: Sequence[Prediccion], b: Sequence[Prediccion], bloques: Sequence[int] | None = None,
                          perdida: Callable = metricas.log_loss, **kwargs) -> dict:
    """`a` y `b`: listas alineadas de (probabilidades, resultado). Devuelve `comparar_perdidas` más la decisión de la puerta de calidad."""
    if len(a) != len(b) or any(x[1] != y[1] for x, y in zip(a, b)):
        raise ValueError("las listas no son del mismo conjunto de partidos")
    r = comparar_perdidas([perdida(p, res) for p, res in a], [perdida(p, res) for p, res in b], bloques, **kwargs)
    r["acepta"] = bool(r["diferencia_media"] >= 0.001 and r["z"] >= 3.0 and r["ic95"][0] > 0)
    return r


def veredicto(r: dict) -> str:
    """Una línea legible para informes: qué pasó y si cumple la puerta (z ≥ 3, ≥ 0,001, IC95 sin cero)."""
    signo = "mejora" if r["diferencia_media"] > 0 else "empeora"
    return (f"{signo} {abs(r['diferencia_media']):.5f} por partido (n={r['n']}, z={r['z']:.1f}, IC95 [{r['ic95'][0]:+.5f}, {r['ic95'][1]:+.5f}])"
            + (" — cumple la puerta" if r.get("acepta") else " — NO cumple la puerta"))
