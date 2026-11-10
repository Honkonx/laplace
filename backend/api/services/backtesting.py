"""services/backtesting.py — backtesting walk-forward honesto + track record público.

Contexto real (`INVESTIGACION_REPOS_BOTS_DEPORTIVOS_2026-09.md`, sección del
repo con "backtesting walk-forward real (RPS/Brier/log-loss/ECE) y un track record público
auto-regenerado" — investigado 2026-09, no clonado): la pieza que le faltaba a Laplace es
publicar métricas de acierto reales, verificables, con su tamaño de muestra — no un código
ajeno portado, sino la misma idea aplicada a los datos propios de este proyecto.

Por qué esto SÍ es "walk-forward" y no solo "calibración retrospectiva" (confirmado leyendo el
código real del motor, no asumido): el motor Poisson/Dixon-Coles + consenso ponderado
(`pronostico.py`, `consenso.py`) usa estadísticas de forma reciente por equipo calculadas EN EL
MOMENTO de cada análisis, con pesos fijados a mano (ver docstring de `services/calibracion.py`)
— nunca se re-entrena ni se ajusta con el resultado de partidos ya jugados. Cada fila de
`AnalisisComparativo` con `pick_final`/probabilidades guardadas es, por construcción, una
predicción hecha ANTES de conocerse el resultado real (`goles_local`/`goles_visitante` se
completan después, vía `services/resultados.py`) — no hay fuga de información del futuro hacia
el pasado que evaluar, así que usar el histórico completo tal cual como set de evaluación es
honesto, sin necesidad de separar folds de train/test artificiales.

Reusa el mismo estilo de queries y el mismo criterio de "mostrar el número real aunque la
muestra sea chica" que `services/calibracion.py` (ver su docstring y
`.claude/rules/product-philosophy.md`) — no reinventa el patrón de `_con_confiabilidad`, ni el
umbral de `AnalisisModulo` vs columnas anchas (ese fallback ya lo resuelve
`calcular_metricas_calibracion`, que este módulo reusa en vez de duplicar sus queries).

Métrica nueva acá: **RPS (Ranked Probability Score)**, la métrica estándar de la literatura de
pronóstico de fútbol (Epstein 1969 / Constantinou & Fenton) para evaluar probabilidades sobre
un resultado de 3 categorías ordenadas (Local / Empate / Visitante, en ese orden convencional).
Fórmula multiclase con r=3 categorías:

    RPS = (1/(r-1)) * sum_{i=1}^{r-1} (cumP_i - cumO_i)^2
        = 0.5 * [(P_local - O_local)^2 + (P_local+P_empate - O_local-O_empate)^2]

Rango [0, 1], menor es mejor (0 = probabilidad perfecta). A diferencia del Brier score
multiclase sin ranking (que ya calcula `calibracion.py`), el RPS penaliza menos un error "cerca"
en el orden (predecir Empate cuando fue Visitante duele menos que predecir Local cuando fue
Visitante) — complementa al Brier, no lo reemplaza, por eso el endpoint público expone ambas.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services.calibracion import MUESTRA_MINIMA_BRIER, calcular_metricas_calibracion, comparativo_valido

# Mismo umbral que Brier score (ver `calibracion.py`): el RPS es, igual que el Brier, una
# métrica de error puro (no una calibración ajustada tipo Platt/isotonic) — sigue siendo
# interpretable con muestras moderadas, no hace falta el umbral más alto de winrate (30).
MUESTRA_MINIMA_RPS = MUESTRA_MINIMA_BRIER


def _resultado_one_hot(goles_local: int, goles_visitante: int) -> tuple[float, float, float]:
    """(o_local, o_empate, o_visit) — exactamente uno es 1.0, mismo criterio que
    `calibracion._brier_score_multiclase`."""
    if goles_local > goles_visitante:
        return 1.0, 0.0, 0.0
    if goles_visitante > goles_local:
        return 0.0, 0.0, 1.0
    return 0.0, 1.0, 0.0


def _rps_partido(p_local: float, p_empate: float, p_visit: float, o_local: float, o_empate: float, o_visit: float) -> float:
    """RPS de un solo partido — ver fórmula en el docstring del módulo. `p_visit`/`o_visit` no
    entran en la fórmula explícitamente porque la suma acumulada de las 3 categorías siempre da
    1.0 (son probabilidades/one-hot completas) — la 3ra categoría queda implícita en las
    primeras 2 sumas acumuladas, por eso el rango con r=3 solo tiene 2 términos (i=1,2)."""
    cum_p1, cum_p2 = p_local, p_local + p_empate
    cum_o1, cum_o2 = o_local, o_local + o_empate
    return 0.5 * ((cum_p1 - cum_o1) ** 2 + (cum_p2 - cum_o2) ** 2)


def _rps_promedio(db: Session) -> dict:
    """Mismo filtro/columnas que `calibracion._brier_score_multiclase` (probabilidades del
    módulo Poisson + resultado real, ambos a la vez) — RPS y Brier se calculan sobre el mismo
    conjunto de partidos verificados, para que sean comparables entre sí en el reporte final."""
    filas = (
        db.query(
            AnalisisComparativo.prob_local_py,
            AnalisisComparativo.prob_empate_py,
            AnalisisComparativo.prob_visit_py,
            AnalisisComparativo.goles_local,
            AnalisisComparativo.goles_visitante,
        )
        .filter(
            comparativo_valido(),
            AnalisisComparativo.goles_local.isnot(None),
            AnalisisComparativo.goles_visitante.isnot(None),
            AnalisisComparativo.prob_local_py.isnot(None),
            AnalisisComparativo.prob_empate_py.isnot(None),
            AnalisisComparativo.prob_visit_py.isnot(None),
        )
        .all()
    )
    n = len(filas)
    if n == 0:
        return {
            "muestra": 0, "rps_promedio": None, "muestra_minima_requerida": MUESTRA_MINIMA_RPS,
            "confiable": False,
            "nota": "0 partidos con probabilidades del módulo Poisson Y resultado real "
                    "(goles_local/goles_visitante) a la vez todavía — no hay nada que calcular.",
        }

    suma = 0.0
    for p_local, p_empate, p_visit, gl, gv in filas:
        o_local, o_empate, o_visit = _resultado_one_hot(gl, gv)
        suma += _rps_partido(p_local, p_empate, p_visit, o_local, o_empate, o_visit)

    rps = round(suma / n, 4)
    return {
        "muestra": n, "rps_promedio": rps, "muestra_minima_requerida": MUESTRA_MINIMA_RPS,
        "confiable": n >= MUESTRA_MINIMA_RPS,
        "nota": (
            "Muestra moderada — el número es indicativo, no una calibración validada."
            if n >= MUESTRA_MINIMA_RPS
            else f"Muestra insuficiente ({n}/{MUESTRA_MINIMA_RPS}) — el valor es real pero no "
                 "confiable como medida de acierto probabilístico, solo referencia."
        ),
    }


def calcular_track_record(db: Session) -> dict:
    """Punto de entrada único del track record público — reusa `calcular_metricas_calibracion`
    (no duplica el cálculo de winrate/Brier/volumen real) y agrega el RPS walk-forward. Mismo
    criterio de honestidad que `calibracion.py`: el número real siempre se devuelve, con su
    `confiable`/`muestra_minima_requerida`, nunca se esconde ni se maquilla (ver
    `.claude/rules/product-philosophy.md`)."""
    calibracion = calcular_metricas_calibracion(db)
    return {
        "volumen_real": calibracion["volumen_real"],
        "pick_final": calibracion["pick_final"],
        "brier_score": calibracion["brier_score_poisson"],
        "rps": _rps_promedio(db),
        "metodologia": (
            "Backtesting walk-forward: cada fila evaluada es una predicción que ya existía "
            "ANTES de conocerse el resultado real del partido (el motor no se re-entrena con "
            "resultados pasados) — no hay separación artificial de folds porque no hay fuga "
            "de información del futuro que evitar."
        ),
        "advertencia_general": calibracion["advertencia_general"],
    }
