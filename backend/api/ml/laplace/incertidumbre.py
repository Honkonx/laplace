"""ml/laplace/incertidumbre.py — intervalos de las probabilidades 1x2 y abstención informada (MM-14).

La regresión logística tiene covarianza de pesos aproximada `Σ ≈ H⁻¹ / n` (H = Hessiano de la pérdida media con su regularización). Con el método delta, la varianza de
`p_k` es `g'Σg` con `g[j][m] = p_k (δ_kj − p_j) x_m`. Entrenar usa numpy (`covarianza_pesos`); servir no (`intervalo`, Python puro). El intervalo refleja la incertidumbre
de los PESOS dada la información del partido, no el azar del resultado (un partido parejo sigue siendo 1/3 de cada cosa aunque no haya incertidumbre de pesos).
La covarianza es la de los pesos universales: no vale para pesos especializados por liga.
"""
from __future__ import annotations

import math

Z80 = 1.2815515655446004
ANCHO_ABSTENCION = 0.20  # si algún intervalo al 80 % mide más que esto, se avisa que el pronóstico es poco fiable


def covarianza_pesos(X: list[list[float]], pesos: list[list[float]], l2: float) -> list[list[float]]:
    """Σ de los 3·d pesos (orden clase-mayor: peso[clase][variable]) por el Hessiano de la pérdida media; la dirección no identificable del softmax se resuelve con pseudo-inversa."""
    import numpy as np

    Xa, W = np.asarray(X, dtype=float), np.asarray(pesos, dtype=float)
    n, d = Xa.shape
    Z = Xa @ W.T
    Z -= Z.max(axis=1, keepdims=True)
    P = np.exp(Z)
    P /= P.sum(axis=1, keepdims=True)
    H = np.zeros((3 * d, 3 * d))
    for i in range(n):
        p, x = P[i], Xa[i]
        S = np.diag(p) - np.outer(p, p)
        H += np.kron(S, np.outer(x, x))
    H /= n
    mascara = np.ones(d)
    mascara[0] = 0.0  # el sesgo no se regulariza
    H += np.diag(np.tile(l2 * mascara, 3))
    return [[round(float(v), 8) for v in fila] for fila in (np.linalg.pinv(H) / n)]


def intervalo(covarianza: list[list[float]], pesos: list[list[float]], x: list[float], z: float = Z80) -> dict:
    """Probabilidades y su intervalo (por defecto al 80 %) para un vector de variables `x`."""
    d = len(x)
    logits = [sum(w * xi for w, xi in zip(fila, x)) for fila in pesos]
    m = max(logits)
    e = [math.exp(v - m) for v in logits]
    s = sum(e)
    p = [v / s for v in e]
    salida = {}
    ancho = 0.0
    for k, nombre in enumerate(("local", "empate", "visitante")):
        g = [p[k] * ((1.0 if k == j else 0.0) - p[j]) * x[mm] for j in range(3) for mm in range(d)]
        var = sum(g[a] * covarianza[a][b] * g[b] for a in range(3 * d) for b in range(3 * d))
        sd = math.sqrt(max(var, 0.0))
        bajo, alto = max(0.0, p[k] - z * sd), min(1.0, p[k] + z * sd)
        salida[nombre] = {"p": round(p[k], 4), "bajo": round(bajo, 4), "alto": round(alto, 4)}
        ancho = max(ancho, alto - bajo)
    return {"p1x2_ic80": salida, "ancho_maximo": round(ancho, 4), "poco_fiable": ancho > ANCHO_ABSTENCION}
