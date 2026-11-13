"""goles.py — mercados de goles del modelo (ambos marcan, más/menos, goles esperados, marcador) calibrados y validados.

Por qué existe: las λ crudas (medias móviles de goles) dispersan demasiado a los equipos; medido el 2026-11-10 sobre 43.158 partidos fuera de muestra, sus mercados de goles
eran PEORES que la tasa base de la liga (ambos marcan 0,6985 vs 0,6899). Aquí se (1) encogen las λ hacia la media de la liga con un exponente `s` ajustado por máxima
verosimilitud de Poisson, (2) se calibra cada mercado con una regresión logística sobre la probabilidad cruda y la tasa base de la liga, y (3) se valida contra la tasa base en
un tramo reservado (el último 15 % de cada liga): un mercado solo se muestra si ahí le gana a la tasa base. Entrenar y servir sin numpy.
"""
from __future__ import annotations

import math

from backend.api.ml import dixon_coles
from backend.api.ml.laplace import pronostico

MERCADOS = ("btts", "o15", "o25", "o35")
LINEA_DE = {"o15": "1.5", "o25": "2.5", "o35": "3.5"}
LINEA_DE_INV = {v: k for k, v in LINEA_DE.items()}
FRACCION_RESERVA = 0.15
MIN_FILAS = 2000
TOPE_LAMBDA = (0.15, 5.0)


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoide(z: float) -> float:
    return 1 / (1 + math.exp(-max(min(z, 30.0), -30.0)))


def encoger(lam: float, media: float, s: float) -> float:
    """Acerca la λ a la media de la liga: s=1 no cambia nada, s=0 usa solo la media."""
    return min(TOPE_LAMBDA[1], max(TOPE_LAMBDA[0], media * (lam / media) ** s))


def probs_crudas(lam_h: float, lam_a: float, rho: float = dixon_coles.RHO_POR_DEFECTO) -> dict[str, float]:
    r = pronostico.resumen_matriz(pronostico.matriz_goles(lam_h, lam_a, rho))
    return {"btts": r["btts"]["si"], "o15": r["over_under"]["1.5"]["mas"], "o25": r["over_under"]["2.5"]["mas"], "o35": r["over_under"]["3.5"]["mas"]}


def resultados_reales(gl: int, gv: int) -> dict[str, int]:
    t = gl + gv
    return {"btts": int(gl > 0 and gv > 0), "o15": int(t > 1), "o25": int(t > 2), "o35": int(t > 3)}


def tasas_de_liga(filas: list[tuple]) -> dict:
    """Tasas observadas de cada mercado y goles totales medios en las filas (gl, gv) de UNA liga."""
    n = len(filas)
    reales = [resultados_reales(f[4], f[5]) for f in filas]
    return {**{m: sum(r[m] for r in reales) / n for m in MERCADOS}, "media_total": sum(f[4] + f[5] for f in filas) / n}


def _resolver(A: list[list[float]], b: list[float]) -> list[float]:
    """Gauss con pivoteo parcial (sistema pequeño)."""
    n = len(b)
    M = [fila[:] + [b[i]] for i, fila in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        piv = M[c][c] or 1e-12
        for r in range(c + 1, n):
            f = M[r][c] / piv
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][k] * x[k] for k in range(i + 1, n))) / (M[i][i] or 1e-12)
    return x


def ajustar_platt(X: list[list[float]], y: list[int], l2: float = 1e-3, iteraciones: int = 30) -> list[float]:
    """Regresión logística binaria por Newton (Hessiano pequeño). Parte de «confiar en el crudo» (0, 1, 0): sin evidencia se queda cerca de él."""
    d = len(X[0])
    w = [0.0, 1.0] + [0.0] * (d - 2)
    n = len(X)
    for _ in range(iteraciones):
        g, H = [l2 * (w[j] - (1.0 if j == 1 else 0.0)) * (j > 0) for j in range(d)], [[(l2 if (i == j and j > 0) else 0.0) for j in range(d)] for i in range(d)]
        for xi, yi in zip(X, y):
            p = sigmoide(sum(a * b for a, b in zip(w, xi)))
            e, v = p - yi, p * (1 - p)
            for i in range(d):
                g[i] += e * xi[i] / n
                for j in range(d):
                    H[i][j] += v * xi[i] * xi[j] / n
        paso = _resolver(H, g)
        w = [a - b for a, b in zip(w, paso)]
        if max(abs(b) for b in paso) < 1e-7:
            break
    return w


def _x(raw: float, tasa: float) -> list[float]:
    return [1.0, logit(raw), logit(tasa)]


def ajustar_exponente(filas: list[tuple]) -> float:
    """Exponente de encogimiento por máxima verosimilitud de Poisson sobre una rejilla (filas = (lam_h, lam_a, media_h, media_v, gl, gv))."""
    mejor, mejor_dev = 1.0, math.inf
    for k in range(10, 121, 5):
        s = k / 100
        dev = 0.0
        for lh, la, mh, mv, gl, gv in filas:
            a, b = encoger(lh, mh, s), encoger(la, mv, s)
            dev += (a - gl * math.log(a)) + (b - gv * math.log(b))
        if dev < mejor_dev:
            mejor, mejor_dev = s, dev
    return mejor


def _log_loss(p: float, y: int) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -math.log(p if y else 1 - p)


def _muestra(filas: list[tuple], tope: int = 30000) -> list[tuple]:
    """Submuestreo regular (cada k-ésima fila) para acotar el costo de la matriz de goles al ajustar; la reserva se mide completa."""
    k = max(1, len(filas) // tope)
    return filas[::k]


def _crudas_de(filas: list[tuple], s: float, rho: float) -> list[dict[str, float]]:
    return [probs_crudas(encoger(lh, mh, s), encoger(la, mv, s), rho) for lh, la, mh, mv, _, _ in filas]


def calibrar(por_liga: dict[str, list[tuple]], rho: float = dixon_coles.RHO_POR_DEFECTO) -> dict | None:
    """Ajusta el encogimiento y la calibración de cada mercado con todas las ligas y los valida con el último 15 % de cada una.

    `por_liga[codigo]` = filas (lam_h, lam_a, media_h, media_v, gl, gv) en orden de fecha, sin fuga. Devuelve None si hay muy pocas filas."""
    todas = [f for fs in por_liga.values() for f in fs]
    if len(todas) < MIN_FILAS:
        return None
    s = ajustar_exponente(todas)
    entren, reserva = {}, {}
    for c, fs in por_liga.items():
        corte = int(len(fs) * (1 - FRACCION_RESERVA))
        entren[c], reserva[c] = fs[:corte], fs[corte:]
    tasas_e = {c: tasas_de_liga(fs) for c, fs in entren.items() if len(fs) >= 100}
    s_e = ajustar_exponente([f for c in tasas_e for f in entren[c]])
    X: dict[str, list] = {m: [] for m in MERCADOS}
    Y: dict[str, list] = {m: [] for m in MERCADOS}
    for c, t in tasas_e.items():
        for fila, raw in zip(_muestra(entren[c]), _crudas_de(_muestra(entren[c]), s_e, rho)):
            real = resultados_reales(fila[4], fila[5])
            for m in MERCADOS:
                X[m].append(_x(raw[m], t[m]))
                Y[m].append(real[m])
    parciales = {m: ajustar_platt(X[m], Y[m]) for m in MERCADOS}
    acum = {m: [0.0, 0.0, 0] for m in MERCADOS}  # ll modelo, ll tasa base, n
    err_mod = err_base = 0.0
    n_res = 0
    for c, t in tasas_e.items():
        if not reserva[c]:
            continue
        for fila, raw in zip(reserva[c], _crudas_de(reserva[c], s_e, rho)):
            real = resultados_reales(fila[4], fila[5])
            for m in MERCADOS:
                p = sigmoide(sum(a * b for a, b in zip(parciales[m], _x(raw[m], t[m]))))
                acum[m][0] += _log_loss(p, real[m])
                acum[m][1] += _log_loss(t[m], real[m])
                acum[m][2] += 1
            err_mod += abs(encoger(fila[0], fila[2], s_e) + encoger(fila[1], fila[3], s_e) - fila[4] - fila[5])
            err_base += abs(t["media_total"] - fila[4] - fila[5])
            n_res += 1
    reserva_inf = {m: {"n": a[2], "log_loss": round(a[0] / a[2], 5), "log_loss_tasa_base": round(a[1] / a[2], 5)} for m, a in acum.items() if a[2]}
    reserva_inf["goles_totales"] = {"n": n_res, "error_abs": round(err_mod / max(n_res, 1), 4), "error_abs_media_liga": round(err_base / max(n_res, 1), 4)}
    util = {m: bool(reserva_inf.get(m)) and reserva_inf[m]["log_loss"] < reserva_inf[m]["log_loss_tasa_base"] for m in MERCADOS}
    util["total"] = reserva_inf["goles_totales"]["error_abs"] < reserva_inf["goles_totales"]["error_abs_media_liga"]
    # parámetros finales: con TODAS las filas (la reserva solo sirvió para decidir qué mercados se muestran)
    tasas = {c: tasas_de_liga(fs) for c, fs in por_liga.items() if len(fs) >= 100}
    XF: dict[str, list] = {m: [] for m in MERCADOS}
    YF: dict[str, list] = {m: [] for m in MERCADOS}
    for c, t in tasas.items():
        for fila, raw in zip(_muestra(por_liga[c]), _crudas_de(_muestra(por_liga[c]), s, rho)):
            real = resultados_reales(fila[4], fila[5])
            for m in MERCADOS:
                XF[m].append(_x(raw[m], t[m]))
                YF[m].append(real[m])
    return {"s": s, "platt": {m: ajustar_platt(XF[m], YF[m]) for m in MERCADOS}, "util": util, "reserva": reserva_inf, "rho": rho, "n": len(todas), "tasas_liga": tasas}


def pronosticar(lam_h: float, lam_a: float, medias: tuple[float, float], calib: dict | None, tasas: dict | None, p1x2: tuple[float, float, float] | None = None) -> dict:
    """Pronóstico completo con los mercados de goles calibrados y la lista `validados` de los que superaron a la tasa base fuera de muestra.

    Sin calibración (artefactos anteriores) o sin tasas de la liga, los mercados salen de las λ crudas y `validados` queda vacía: los consumidores no los muestran."""
    if not calib or not tasas:
        r = pronostico.pronosticar(lam_h, lam_a, p1x2=p1x2)
        r["validados"] = []
        return r
    lh, la = encoger(lam_h, medias[0], calib["s"]), encoger(lam_a, medias[1], calib["s"])
    r = pronostico.pronosticar(lh, la, calib.get("rho", dixon_coles.RHO_POR_DEFECTO), p1x2=p1x2)
    raw = probs_crudas(lh, la, calib.get("rho", dixon_coles.RHO_POR_DEFECTO))
    cal = {m: sigmoide(sum(a * b for a, b in zip(calib["platt"][m], _x(raw[m], tasas[m])))) for m in MERCADOS}
    r["btts"] = {"si": cal["btts"], "no": 1 - cal["btts"]}
    r["over_under"] = {LINEA_DE[m]: {"mas": cal[m], "menos": 1 - cal[m]} for m in ("o15", "o25", "o35")}
    r["validados"] = [m for m in MERCADOS if calib["util"].get(m)] + (["total"] if calib["util"].get("total") else [])
    return r
