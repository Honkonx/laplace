"""ml/dixon_coles.py — Poisson bivariado con corrección Dixon-Coles y decaimiento temporal.

Por qué existe (auditoría 2026-09-29): el motor en producción (`services/pronostico.py`) usa el
promedio de goles de TODA la temporada por equipo y una ventaja de local fija (0.35 goles) para
cualquier liga. Este modelo aprende, por liga y solo con partidos ANTERIORES al que se predice:
  - fuerza de ataque y de defensa de cada equipo, con más peso a los partidos recientes
    (`exp(-xi * dias)`, half-life por defecto ≈ 365 días);
  - la ventaja de local propia de esa liga y el nivel de goles propio de esa liga;
  - encogimiento (ridge) hacia el promedio: un equipo con pocos partidos no recibe una fuerza
    extrema por azar — clave al inicio de temporada y con equipos recién ascendidos.
La corrección de baja puntuación (`tau`) es la de Dixon & Coles (1997); `rho` se estima aparte
por búsqueda en rejilla (log-loss) porque ajustarlo junto con el resto complica el gradiente sin
cambiar el resultado de forma apreciable.

AJUSTE (numpy/scipy) y PREDICCIÓN (Python puro) están separados: `ajustar()` importa numpy y
scipy de forma perezosa; `probabilidades()` no necesita nada fuera de la librería estándar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

XI_POR_DEFECTO = 0.0019  # ≈ half-life de 365 días (Dixon & Coles usaron ~0.0018-0.0020/día)
RIDGE_POR_DEFECTO = 2.0
RHO_POR_DEFECTO = -0.10
MAX_GOLES = 10
LAMBDA_MIN, LAMBDA_MAX = 0.15, 5.0
MIN_PARTIDOS_AJUSTE = 30


@dataclass
class ModeloLiga:
    """Parámetros ajustados de una liga a una fecha de corte."""

    mu: float
    gamma: float
    ataque: dict[str, float] = field(default_factory=dict)
    defensa: dict[str, float] = field(default_factory=dict)
    rho: float = RHO_POR_DEFECTO
    n_partidos: int = 0
    fecha_corte: int | None = None  # ordinal de la fecha del último partido usado

    def a_dict(self) -> dict:
        return {
            "mu": round(self.mu, 5), "gamma": round(self.gamma, 5), "rho": self.rho,
            "n_partidos": self.n_partidos, "fecha_corte": self.fecha_corte,
            "ataque": {k: round(v, 4) for k, v in self.ataque.items()},
            "defensa": {k: round(v, 4) for k, v in self.defensa.items()},
        }

    @classmethod
    def de_dict(cls, d: dict) -> ModeloLiga:
        return cls(
            mu=d["mu"], gamma=d["gamma"], rho=d.get("rho", RHO_POR_DEFECTO),
            ataque=dict(d["ataque"]), defensa=dict(d["defensa"]),
            n_partidos=d.get("n_partidos", 0), fecha_corte=d.get("fecha_corte"),
        )


def ajustar(
    partidos: list[tuple[int, str, str, int, int]],
    fecha_ref: int,
    xi: float = XI_POR_DEFECTO,
    ridge: float = RIDGE_POR_DEFECTO,
    rho: float = RHO_POR_DEFECTO,
) -> ModeloLiga | None:
    """Ajusta un modelo con los partidos `(dia_ordinal, local, visitante, gl, gv)` de UNA liga.

    Solo usa partidos con `dia_ordinal < fecha_ref` (nunca el futuro). Devuelve None si hay
    menos de `MIN_PARTIDOS_AJUSTE` partidos: por debajo de eso solo se ajustaría ruido."""
    import numpy as np
    from scipy.optimize import minimize

    previos = [p for p in partidos if p[0] < fecha_ref]
    if len(previos) < MIN_PARTIDOS_AJUSTE:
        return None

    equipos = sorted({p[1] for p in previos} | {p[2] for p in previos})
    idx = {e: i for i, e in enumerate(equipos)}
    n = len(equipos)
    h = np.array([idx[p[1]] for p in previos])
    a = np.array([idx[p[2]] for p in previos])
    gl = np.array([p[3] for p in previos], dtype=float)
    gv = np.array([p[4] for p in previos], dtype=float)
    w = np.exp(-xi * (fecha_ref - np.array([p[0] for p in previos], dtype=float)))

    def nll(theta):
        att, dfn, mu, gam = theta[:n], theta[n:2 * n], theta[2 * n], theta[2 * n + 1]
        eta_h = np.clip(mu + gam + att[h] - dfn[a], -3, 3)
        eta_a = np.clip(mu + att[a] - dfn[h], -3, 3)
        lam_h, lam_a = np.exp(eta_h), np.exp(eta_a)
        val = np.sum(w * (lam_h - gl * eta_h + lam_a - gv * eta_a)) + ridge * (att @ att + dfn @ dfn)
        r_h, r_a = w * (lam_h - gl), w * (lam_a - gv)
        g_att = np.bincount(h, r_h, n) + np.bincount(a, r_a, n) + 2 * ridge * att
        g_def = -np.bincount(a, r_h, n) - np.bincount(h, r_a, n) + 2 * ridge * dfn
        grad = np.concatenate([g_att, g_def, [r_h.sum() + r_a.sum(), r_h.sum()]])
        return val, grad

    x0 = np.zeros(2 * n + 2)
    x0[2 * n] = math.log(max(float((gl.sum() + gv.sum()) / (2 * len(gl))), 0.5))
    theta = minimize(nll, x0, jac=True, method="L-BFGS-B", options={"maxiter": 300}).x
    return ModeloLiga(
        mu=float(theta[2 * n]), gamma=float(theta[2 * n + 1]),
        ataque={e: float(theta[i]) for e, i in idx.items()},
        defensa={e: float(theta[n + i]) for e, i in idx.items()},
        rho=rho, n_partidos=len(previos), fecha_corte=int(max(p[0] for p in previos)),
    )


def _pmf(k: int, lam: float) -> float:
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def _tau(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1.0 - lam_h * lam_a * rho
    if x == 0 and y == 1:
        return 1.0 + lam_h * rho
    if x == 1 and y == 0:
        return 1.0 + lam_a * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def _acotar(x: float) -> float:
    return min(LAMBDA_MAX, max(LAMBDA_MIN, x))


def lambdas(modelo: ModeloLiga, local: str, visitante: str) -> tuple[float, float, bool]:
    """(lambda_local, lambda_visitante, conocidos). Un equipo ausente del ajuste cuenta como
    promedio de la liga (ataque=defensa=0) y `conocidos=False` avisa al caller."""
    conocidos = local in modelo.ataque and visitante in modelo.ataque
    att_h, def_h = modelo.ataque.get(local, 0.0), modelo.defensa.get(local, 0.0)
    att_a, def_a = modelo.ataque.get(visitante, 0.0), modelo.defensa.get(visitante, 0.0)
    lam_h = math.exp(modelo.mu + modelo.gamma + att_h - def_a)
    lam_a = math.exp(modelo.mu + att_a - def_h)
    return _acotar(lam_h), _acotar(lam_a), conocidos


def probabilidades_desde_lambdas(lam_h: float, lam_a: float, rho: float) -> tuple[float, float, float]:
    """(P local, P empate, P visitante) de la matriz Poisson con corrección Dixon-Coles."""
    ph = pe = pa = total = 0.0
    for i in range(MAX_GOLES):
        p_i = _pmf(i, lam_h)
        for j in range(MAX_GOLES):
            p = p_i * _pmf(j, lam_a) * max(_tau(i, j, lam_h, lam_a, rho), 0.0)
            total += p
            if i > j:
                ph += p
            elif i == j:
                pe += p
            else:
                pa += p
    return ph / total, pe / total, pa / total


def probabilidades(modelo: ModeloLiga, local: str, visitante: str) -> tuple[float, float, float]:
    lam_h, lam_a, _ = lambdas(modelo, local, visitante)
    return probabilidades_desde_lambdas(lam_h, lam_a, modelo.rho)
