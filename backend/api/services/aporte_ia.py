"""services/aporte_ia.py — ¿cuánto aporta la IA al pronóstico? (MB-23). Solo lectura.

Compara, sobre los MISMOS partidos con resultado del laboratorio, la variante `python_baseline` (solo estadístico) con `python_plus_ia` (con IA): log loss y RPS medios, la diferencia
pareada con z, y el veredicto. Mientras no haya al menos 200 partidos pareados el veredicto es «sin evidencia» y no se recomienda reducir ni aumentar el gasto de IA.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

N_MINIMO = 200
BASE, CON_IA = "python_baseline", "python_plus_ia"


def medir(pares: list[tuple[float, float, float, float]]) -> dict:
    """`pares` = [(log loss base, log loss con IA, RPS base, RPS con IA)] de los mismos partidos. Diferencias positivas = la IA mejora."""
    n = len(pares)
    if n == 0:
        return {"n": 0, "veredicto": "sin evidencia", "motivo": "no hay partidos con las dos variantes y resultado"}
    dll = [a - b for a, b, _, _ in pares]
    drps = [a - b for _, _, a, b in pares]
    media = sum(dll) / n
    z, constante = None, False
    if n > 1:
        var = sum((x - media) ** 2 for x in dll) / (n - 1)
        z = round(media / math.sqrt(var / n), 2) if var > 0 else None
        constante = var == 0 and media != 0  # la misma diferencia en todos los partidos: no hay dispersión que medir
    r = {"n": n, "log_loss_base": round(sum(p[0] for p in pares) / n, 5), "log_loss_con_ia": round(sum(p[1] for p in pares) / n, 5), "mejora_log_loss": round(media, 5),
         "mejora_rps": round(sum(drps) / n, 5), "z": z, "veredicto": "sin evidencia"}
    if n < N_MINIMO:
        r["motivo"] = f"menos de {N_MINIMO} partidos pareados ({n}): informativo, no se cambia el gasto de IA"
    elif constante or (z is not None and abs(z) >= 3):
        r["veredicto"] = "la IA mejora el pronóstico" if media > 0 else "la IA empeora el pronóstico: reducir o quitar su gasto"
    else:
        r["motivo"] = "diferencia sin significancia (|z| < 3)"
    return r


def desde_base(db: Session) -> dict:
    from backend.api.models.predicciones import PronosticoExperimental as O

    def por_partido(variante: str) -> dict:
        filas = db.query(O.partido_id, O.log_loss, O.rps).filter(O.variante == variante, O.log_loss.is_not(None), O.rps.is_not(None)).all()
        return {p: (ll, rps) for p, ll, rps in filas}

    a, b = por_partido(BASE), por_partido(CON_IA)
    return medir([(a[p][0], b[p][0], a[p][1], b[p][1]) for p in a if p in b])
