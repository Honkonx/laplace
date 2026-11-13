"""services/discrepancia_ia.py — ¿«la IA discrepa» predice que el consenso se equivoca? (MB-15)

Tabla 2×2 con lo que ya guarda `analisis_comparativo` (columna `consenso` = COINCIDEN | DIVERGEN, `pick_correcto` del pick final): acierto del consenso cuando la IA coincide frente a cuando
diverge, con intervalo de Wilson por grupo y z de dos proporciones. Mientras no haya al menos `N_MINIMO` partidos evaluados en cada grupo el veredicto es «sin evidencia» y el ajuste de −8
puntos de `consenso_ia.CONSENSO_AJUSTE` NO se toca. Solo lectura: no escribe en la base.
"""
from __future__ import annotations

import math

N_MINIMO = 200
Z95 = 1.96


def _wilson(aciertos: int, n: int) -> tuple[float, float] | None:
    if n == 0:
        return None
    p, z2 = aciertos / n, Z95 * Z95
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    margen = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return round(max(0.0, centro - margen), 4), round(min(1.0, centro + margen), 4)


def _grupo(filas: list[tuple[str | None, int | None]], nivel: str) -> dict:
    evaluados = [c for n, c in filas if n == nivel and c in (0, 1)]
    aciertos = sum(evaluados)
    n = len(evaluados)
    return {"n": n, "aciertos": aciertos, "tasa": round(aciertos / n, 4) if n else None, "ic95": _wilson(aciertos, n)}


def medir(filas: list[tuple[str | None, int | None]]) -> dict:
    """`filas` = [(consenso, pick_correcto)]; devuelve la tabla, la diferencia y un veredicto honesto."""
    coinciden, divergen = _grupo(filas, "COINCIDEN"), _grupo(filas, "DIVERGEN")
    resultado = {"coinciden": coinciden, "divergen": divergen, "diferencia": None, "z": None, "veredicto": "sin evidencia", "n_minimo_por_grupo": N_MINIMO}
    if not coinciden["n"] or not divergen["n"]:
        resultado["motivo"] = "falta algún grupo con resultados"
        return resultado
    p1, p2, n1, n2 = coinciden["tasa"], divergen["tasa"], coinciden["n"], divergen["n"]
    resultado["diferencia"] = round(p1 - p2, 4)
    agrupada = (coinciden["aciertos"] + divergen["aciertos"]) / (n1 + n2)
    error = math.sqrt(agrupada * (1 - agrupada) * (1 / n1 + 1 / n2))
    resultado["z"] = round((p1 - p2) / error, 2) if error else None
    if min(n1, n2) < N_MINIMO:
        resultado["motivo"] = f"menos de {N_MINIMO} partidos evaluados en algún grupo ({n1} y {n2}): informativo, el ajuste actual no se cambia"
    elif resultado["z"] is not None and abs(resultado["z"]) >= 3:
        resultado["veredicto"] = "discrepar predice error" if resultado["diferencia"] > 0 else "discrepar NO predice error (al revés)"
    else:
        resultado["motivo"] = "diferencia sin significancia (|z| < 3)"
    return resultado


def desde_base(db) -> dict:
    from backend.api.models.predicciones import AnalisisComparativo as A

    return medir([(c, k) for c, k in db.query(A.consenso, A.pick_correcto).filter(A.consenso.in_(["COINCIDEN", "DIVERGEN"])).all()])
