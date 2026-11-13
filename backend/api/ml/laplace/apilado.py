"""apilado.py — el 1X2 del modelo Laplace combinado con las cuotas del mercado (sin margen), cuando el partido las tiene.

Medido el 2026-11-10 en 20.960 partidos con cuotas (prueba desde 2023-07, apilador ajustado con 2021-07..2023-07): modelo 1,0131, mercado 0,9957, apilado 0,9946 de log loss.
La mejora sobre el mercado es real pero pequeña (≈0,001): el apilado NO reemplaza al `p1x2` del modelo (que sigue siendo puramente propio y es lo que se mide en vivo); se
ofrece aparte como `p1x2_con_mercado`, solo cuando el apilador le ganó al mercado en la evaluación. Entrenar usa numpy; aplicar no.
"""
from __future__ import annotations

import math
from datetime import date

from backend.api.ml import metricas
from backend.api.ml.laplace import entrenamiento

CORTE_VALIDACION = date(2021, 7, 1).toordinal()
COTA_MAX, COTA_MIN = 1000.0, 1.01


def cuotas_validas(cuotas) -> tuple[float, float, float] | None:
    """Tres cuotas decimales reales (> 1,01 y acotadas) o None: lo que llega por API no es de fiar."""
    try:
        h, d, a = (float(x) for x in cuotas)
    except (TypeError, ValueError):
        return None
    return (h, d, a) if all(COTA_MIN <= x <= COTA_MAX and math.isfinite(x) for x in (h, d, a)) else None


def caracteristicas(pm: tuple[float, float, float], pk: tuple[float, float, float]) -> list[float]:
    return [1.0] + [math.log(max(x, 1e-6)) for x in pm] + [math.log(max(x, 1e-6)) for x in pk]


def aplicar(apilador: dict | None, p1x2: tuple[float, float, float], cuotas) -> tuple[float, float, float] | None:
    c = cuotas_validas(cuotas)
    if not apilador or not apilador.get("util") or c is None:
        return None
    return entrenamiento.probs_lineal(apilador["pesos"], caracteristicas(p1x2, entrenamiento.sin_margen(c)))


def _predicciones_con_cuotas(por_liga: dict, corte: int, hasta: int | None, hiper: dict | None = None) -> list[tuple]:
    """(p del modelo, p del mercado sin margen, resultado) de los partidos con cuotas entre `corte` y `hasta`, con el modelo entrenado SOLO con lo anterior a `corte`."""
    art = entrenamiento.entrenar_jerarquico(por_liga, corte, hiper=hiper, con_goles=False)
    salida = []
    for codigo, info in art["ligas"].items():
        if codigo not in por_liga:
            continue
        estado = entrenamiento.EstadoLiga.de_dict(info["estado"])
        pesos = entrenamiento.pesos_de(art, codigo)
        for p in sorted((q for q in por_liga[codigo] if q["dia"] >= corte and (hasta is None or q["dia"] < hasta)), key=lambda x: (x["dia"], x["local"])):
            c = p.get("cuotas") or (p.get("ap_prom") if isinstance(p.get("ap_prom"), tuple) else None)
            if c:
                salida.append((entrenamiento.probs_lineal(pesos, estado.features(p["local"], p["visitante"])), entrenamiento.sin_margen(c), p["resultado"]))
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], entrenamiento.tiros_de(p))
    return salida


def ajustar(por_liga: dict, corte_prueba: int, corte_validacion: int = CORTE_VALIDACION, hiper: dict | None = None) -> dict | None:
    """Ajusta el apilador con 2021-07..corte_prueba y lo mide en lo posterior; `util` solo si le gana al mercado solo. None si no hay cuotas suficientes."""
    try:
        val = _predicciones_con_cuotas(por_liga, corte_validacion, corte_prueba, hiper)
        prueba = _predicciones_con_cuotas(por_liga, corte_prueba, None, hiper)
    except ValueError:  # muy pocas ligas o partidos para entrenar: sin apilador
        return None
    if len(val) < 2000 or len(prueba) < 1000:
        return None
    pesos = entrenamiento.ajustar_logistica([caracteristicas(a, b) for a, b, _ in val], [r for *_, r in val])
    apiladas = [(entrenamiento.probs_lineal(pesos, caracteristicas(a, b)), r) for a, b, r in prueba]
    ll = lambda v: round(metricas.promedio(metricas.log_loss, v), 5)  # noqa: E731
    ev = {"n_validacion": len(val), "n_prueba": len(prueba), "log_loss_modelo": ll([(a, r) for a, _, r in prueba]),
          "log_loss_mercado": ll([(b, r) for _, b, r in prueba]), "log_loss_apilado": ll(apiladas)}
    return {"pesos": pesos, "evaluacion": ev, "util": ev["log_loss_apilado"] < ev["log_loss_mercado"]}
