"""pronostico.py — del par (λ local, λ visitante) a TODO lo que el modelo dice de un partido. Solo librería estándar."""
from __future__ import annotations

import math

from backend.api.ml import dixon_coles

MAX_GOLES = 10
LINEAS_TOTAL = (1.5, 2.5, 3.5)


def matriz_goles(lam_h: float, lam_a: float, rho: float = dixon_coles.RHO_POR_DEFECTO) -> list[list[float]]:
    """P(local=i, visitante=j) normalizada, con la corrección Dixon-Coles de baja puntuación.

    Las pmf se calculan UNA vez por equipo (10 + 10 llamadas en vez de 100 + 100) y la corrección solo toca las 4 celdas de 0-0, 0-1, 1-0 y 1-1 (en las demás vale 1):
    misma salida que la versión por celda, ≈ 5 veces más rápida (MM-04)."""
    pmf_h = [dixon_coles._pmf(i, lam_h) for i in range(MAX_GOLES)]  # noqa: SLF001
    pmf_a = [dixon_coles._pmf(j, lam_a) for j in range(MAX_GOLES)]  # noqa: SLF001
    m = [[ph * pa for pa in pmf_a] for ph in pmf_h]
    for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)):
        m[i][j] *= max(dixon_coles._tau(i, j, lam_h, lam_a, rho), 0.0)  # noqa: SLF001
    total = sum(sum(f) for f in m) or 1.0
    return [[p / total for p in f] for f in m]


def resumen_matriz(m: list[list[float]], top_marcadores: int = 5) -> dict:
    ph = pe = pa = btts = 0.0
    total_goles = [0.0] * (2 * MAX_GOLES)
    marcadores = []
    for i, fila in enumerate(m):
        for j, p in enumerate(fila):
            ph, pe, pa = (ph + p, pe, pa) if i > j else (ph, pe + p, pa) if i == j else (ph, pe, pa + p)
            if i > 0 and j > 0:
                btts += p
            total_goles[i + j] += p
            marcadores.append((p, i, j))
    marcadores.sort(reverse=True)
    return {
        "p1x2": {"local": ph, "empate": pe, "visitante": pa},
        "btts": {"si": btts, "no": 1 - btts},
        "over_under": {str(l): {"mas": sum(total_goles[int(l) + 1:]), "menos": sum(total_goles[:int(l) + 1])} for l in LINEAS_TOTAL},
        "marcadores": [{"marcador": f"{i}-{j}", "prob": p} for p, i, j in marcadores[:top_marcadores]],
    }


def confianza_desde_probs(p: tuple[float, float, float]) -> float:
    """1 - entropía normalizada: 0 = nada informativo (1/3 cada uno), 1 = certeza. Es dispersión, no un acierto garantizado."""
    h = -sum(x * math.log(x) for x in p if x > 0)
    return round(max(0.0, 1 - h / math.log(3)), 4)


def pronosticar(lam_h: float, lam_a: float, rho: float = dixon_coles.RHO_POR_DEFECTO, p1x2: tuple[float, float, float] | None = None) -> dict:
    """Pronóstico completo. `p1x2` permite sustituir el 1X2 por el de un modelo calibrado conservando goles, marcadores y totales."""
    r = resumen_matriz(matriz_goles(lam_h, lam_a, rho))
    if p1x2 is not None:
        r["p1x2"] = {"local": p1x2[0], "empate": p1x2[1], "visitante": p1x2[2]}
    p = (r["p1x2"]["local"], r["p1x2"]["empate"], r["p1x2"]["visitante"])
    r["goles_esperados"] = {"local": round(lam_h, 3), "visitante": round(lam_a, 3), "total": round(lam_h + lam_a, 3)}
    r["confianza"] = confianza_desde_probs(p)
    return r
