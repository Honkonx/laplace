"""
services/calibracion.py — Métricas reales de winrate/calibración del motor de predicción,
leídas directo de `AnalisisComparativo`/`AnalisisModulo`. Solo lectura, nunca escribe.

Contexto (auditoría 2026-09-09, ver `.claude/rules/product-philosophy.md`): el motor
Poisson/Dixon-Coles + consenso ponderado (`pronostico.py`, `consenso.py`) nunca fue calibrado
con datos reales — los pesos son valores puestos a mano. Este módulo NO calibra nada — solo
mide, con honestidad, qué tan confiable es medir algo hoy con el volumen real de datos
verificados que hay en la BD. Ver `.claude/rules/empirical-verification-before-fix.md`: un
número calculado no es lo mismo que un número estadísticamente válido.

Dos fuentes de datos por módulo, en orden de preferencia:
  1. `AnalisisModulo` (una fila por módulo por partido, pensada para esto desde v5 — ver su
     docstring en `models/predicciones.py`) — hoy vacía en la BD real (0 filas, confirmado
     2026-09-09): el pipeline que la llena (`guardar_analisis_multimodelo`, ver
     `db/analisis_repo.py`) existe pero nada la está invocando todavía con `modulos_data`
     poblado.
  2. Fallback: las columnas anchas por módulo de `AnalisisComparativo`
     (`pick_python_correcto`, `pick_form_correcto`, `pick_h2h_correcto`, `pick_odds_correcto`,
     `pick_tabla_correcto`, `pick_externo_correcto`) — sí tienen datos (cuando hay partidos
     verificados), es el camino real que usa hoy `services/resultados.py` al marcar picks.
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.api.models.predicciones import CORTE_MOTOR_CON_PUERTA_CALIDAD, AnalisisComparativo, AnalisisModulo

# Umbral de muestra mínima para considerar un winrate "confiable" — no es un número mágico
# universal, es el criterio pedido explícitamente para esta pieza (ver prompt de la ronda que
# creó este módulo, 2026-09-09): por debajo de esto se sigue mostrando el número real (nunca se
# esconde, ver product-philosophy.md) pero marcado como muestra insuficiente.
MUESTRA_MINIMA_WINRATE = 30

# El corte de calidad del motor (`CORTE_MOTOR_CON_PUERTA_CALIDAD`) vive en
# `models/predicciones.py` — ver su comentario. Lo que se analizó antes no entra en estas métricas.

# Umbral para Brier score — más bajo que el de winrate porque el Brier score (a diferencia de
# Platt scaling/isotonic regression) es una métrica de error cuadrático que sigue siendo
# interpretable con muestras moderadas; no es una "calibración" ajustada, es solo una medida de
# qué tan lejos están las probabilidades emitidas del resultado real. Igual se marca como no
# confiable por debajo de este umbral — un Brier de n=5 es tan ruido como un winrate de n=5.
MUESTRA_MINIMA_BRIER = 20

# `historico` y `bsd_ml` NO tienen columnas anchas equivalentes en `AnalisisComparativo` (solo
# poisson/forma/h2h/odds/tabla/externo) y no se crean columnas ni migraciones para ellos: se miden
# desde `AnalisisModulo`, que `analisis_completo._persistir` llena con TODOS los módulos que
# corrieron (`_modulos_data_para_guardar`) y donde `resultados.py` marca `pick_correcto`. Ese es el
# camino preferido de `calcular_metricas_calibracion`; este fallback de columnas anchas solo se
# usa mientras `analisis_modulos` no tenga filas posteriores al corte, y en ese caso `historico`/
# `bsd_ml` aparecen sin medir (no hay de dónde leerlos), nunca con datos inventados.
MODULOS_SOLO_EN_ANALISIS_MODULO = ("historico", "bsd_ml")

MODULOS_COLUMNAS_ANCHAS = {
    "poisson": (AnalisisComparativo.pick_python, AnalisisComparativo.pick_python_correcto),
    "forma": (AnalisisComparativo.pick_form, AnalisisComparativo.pick_form_correcto),
    "h2h": (AnalisisComparativo.pick_h2h, AnalisisComparativo.pick_h2h_correcto),
    "odds": (AnalisisComparativo.pick_odds, AnalisisComparativo.pick_odds_correcto),
    "tabla": (AnalisisComparativo.pick_tabla, AnalisisComparativo.pick_tabla_correcto),
    "externo": (AnalisisComparativo.pick_externo, AnalisisComparativo.pick_externo_correcto),
}


def comparativo_valido():
    """Condición SQLAlchemy: análisis hecho con el motor posterior al corte de calidad Y creado ANTES
    del inicio del partido (si se conoce la hora de inicio). Un pronóstico hecho tras el pitazo no es
    una predicción: en la BD real había análisis de MLS creados después del partido que daban un 75%
    de acierto (auditoría 2026-10-06). Con `hora_kickoff` vacío (todo lo anterior a 2026-10-07) no hay
    forma de saberlo y la fila se mantiene, como antes."""
    kickoff_utc = func.substr(func.replace(func.replace(AnalisisComparativo.hora_kickoff, "T", " "), "Z", ""), 1, 19)
    sin_kickoff = or_(AnalisisComparativo.hora_kickoff.is_(None), AnalisisComparativo.hora_kickoff == "")
    return and_(
        AnalisisComparativo.creado_en >= CORTE_MOTOR_CON_PUERTA_CALIDAD,
        or_(sin_kickoff, AnalisisComparativo.creado_en < kickoff_utc),
    )


def _winrate(aciertos: int, evaluados: int) -> float | None:
    return round(100 * aciertos / evaluados, 1) if evaluados else None


def _con_confiabilidad(evaluados: int, aciertos: int, umbral: int) -> dict:
    return {
        "evaluados": evaluados,
        "aciertos": aciertos,
        "winrate_pct": _winrate(aciertos, evaluados),
        "muestra_minima_requerida": umbral,
        "confiable": evaluados >= umbral,
        "nota": (
            "Suficiente para un winrate orientativo, pero sigue siendo poco dato — revisar de "
            "nuevo con más volumen antes de tomar decisiones de peso."
            if evaluados >= umbral
            else f"Muestra insuficiente ({evaluados}/{umbral} partidos verificados) — este número "
                 "es real pero NO es estadísticamente confiable, no usar para recalibrar pesos."
        ),
    }


def _metricas_por_modulo_desde_analisis_modulo(db: Session) -> dict[str, dict] | None:
    """Usa `AnalisisModulo` si tiene filas reales — fuente preferida (más granular, permite
    guardar varios análisis del mismo módulo por partido). Devuelve None si está vacía, para
    que el caller haga fallback a las columnas anchas de `AnalisisComparativo`."""
    total = (
        db.query(func.count(AnalisisModulo.id))
        .filter(AnalisisModulo.creado_en >= CORTE_MOTOR_CON_PUERTA_CALIDAD)
        .scalar() or 0
    )
    if total == 0:
        return None

    # Dos queries simples por módulo (en vez de una sola con `case()` condicional) — evita
    # expresiones de conteo condicional que se comportan distinto entre dialectos SQLite/
    # Postgres para un booleano derivado; con el volumen real de datos de este proyecto el costo
    # extra de queries es irrelevante.
    salida: dict[str, dict] = {}
    valido = AnalisisModulo.creado_en >= CORTE_MOTOR_CON_PUERTA_CALIDAD
    for modulo, in db.query(AnalisisModulo.modulo).filter(valido).distinct().all():
        evaluados = (
            db.query(func.count(AnalisisModulo.id))
            .filter(valido, AnalisisModulo.modulo == modulo, AnalisisModulo.pick_correcto.isnot(None))
            .scalar() or 0
        )
        aciertos = (
            db.query(func.count(AnalisisModulo.id))
            .filter(valido, AnalisisModulo.modulo == modulo, AnalisisModulo.pick_correcto == 1)
            .scalar() or 0
        )
        salida[modulo] = _con_confiabilidad(evaluados, aciertos, MUESTRA_MINIMA_WINRATE)
    return salida


def _metricas_por_modulo_desde_columnas_anchas(db: Session) -> dict[str, dict]:
    salida: dict[str, dict] = {}
    for nombre, (col_pick, col_correcto) in MODULOS_COLUMNAS_ANCHAS.items():
        evaluados = (
            db.query(func.count(AnalisisComparativo.id))
            .filter(comparativo_valido(), col_pick.isnot(None), col_pick != "", col_correcto.isnot(None))
            .scalar() or 0
        )
        aciertos = (
            db.query(func.count(AnalisisComparativo.id))
            .filter(comparativo_valido(), col_correcto == 1)
            .scalar() or 0
        )
        salida[nombre] = _con_confiabilidad(evaluados, aciertos, MUESTRA_MINIMA_WINRATE)
    for nombre in MODULOS_SOLO_EN_ANALISIS_MODULO:
        salida[nombre] = {
            **_con_confiabilidad(0, 0, MUESTRA_MINIMA_WINRATE),
            "nota": "Sin medir: este módulo solo se registra en `analisis_modulos`, que no tiene "
                    "filas válidas todavía.",
        }
    return salida


def _brier_score_multiclase(db: Session) -> dict:
    """Brier score multiclase (1 local / X empate / 2 visitante) del módulo Poisson —
    `mean((p_local-o_local)^2 + (p_empate-o_empate)^2 + (p_visit-o_visit)^2)`, rango [0, 2],
    menor es mejor calibrado (0 = probabilidad perfecta). Requiere `goles_local`/
    `goles_visitante` reales (derivan el resultado real one-hot) y las 3 probabilidades del
    módulo Poisson (`prob_local_py`/`prob_empate_py`/`prob_visit_py`) — ambas cosas a la vez,
    sobre la misma fila.

    A diferencia de Platt scaling / isotonic regression (que ajustan un modelo nuevo sobre las
    probabilidades y necesitan cientos de muestras para no sobreajustar), el Brier score es solo
    una medida de error — válido de calcular con `n` moderado, aunque con `n` chico su propio
    valor tiene mucha varianza (mismo motivo que winrate: se marca `confiable` solo con
    `MUESTRA_MINIMA_BRIER` o más filas)."""
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
            "muestra": 0, "brier_score": None, "muestra_minima_requerida": MUESTRA_MINIMA_BRIER,
            "confiable": False,
            "nota": "0 partidos con probabilidades del módulo Poisson Y resultado real "
                    "(goles_local/goles_visitante) a la vez todavía — no hay nada que calcular.",
        }

    suma = 0.0
    for p_local, p_empate, p_visit, gl, gv in filas:
        if gl > gv:
            o_local, o_empate, o_visit = 1.0, 0.0, 0.0
        elif gv > gl:
            o_local, o_empate, o_visit = 0.0, 0.0, 1.0
        else:
            o_local, o_empate, o_visit = 0.0, 1.0, 0.0
        suma += (p_local - o_local) ** 2 + (p_empate - o_empate) ** 2 + (p_visit - o_visit) ** 2

    brier = round(suma / n, 4)
    return {
        "muestra": n, "brier_score": brier, "muestra_minima_requerida": MUESTRA_MINIMA_BRIER,
        "confiable": n >= MUESTRA_MINIMA_BRIER,
        "nota": (
            "Muestra moderada — el número es indicativo, no una calibración validada."
            if n >= MUESTRA_MINIMA_BRIER
            else f"Muestra insuficiente ({n}/{MUESTRA_MINIMA_BRIER}) — el valor es real pero no "
                 "confiable como medida de calibración, solo referencia."
        ),
    }


def calcular_metricas_calibracion(db: Session) -> dict:
    """Punto de entrada único — usado tanto por `backend/scripts/laplace_auditor.py` (consola +
    JSON) como por `GET /api/v1/admin/calibracion` (mismo cálculo, sin duplicar lógica)."""
    total_filas_comparativo = db.query(func.count(AnalisisComparativo.id)).scalar() or 0
    total_filas_modulo = db.query(func.count(AnalisisModulo.id)).scalar() or 0
    validas_comparativo = (
        db.query(func.count(AnalisisComparativo.id)).filter(comparativo_valido()).scalar() or 0
    )

    evaluados_final = (
        db.query(func.count(AnalisisComparativo.id))
        .filter(comparativo_valido(), AnalisisComparativo.pick_correcto.isnot(None))
        .scalar() or 0
    )
    aciertos_final = (
        db.query(func.count(AnalisisComparativo.id))
        .filter(comparativo_valido(), AnalisisComparativo.pick_correcto == 1)
        .scalar() or 0
    )

    por_modulo = _metricas_por_modulo_desde_analisis_modulo(db)
    fuente_por_modulo = "analisis_modulos"
    if por_modulo is None:
        por_modulo = _metricas_por_modulo_desde_columnas_anchas(db)
        fuente_por_modulo = "analisis_comparativo (columnas anchas — analisis_modulos no tiene filas válidas todavía)"

    return {
        "volumen_real": {
            "total_filas_analisis_comparativo": total_filas_comparativo,
            "total_filas_analisis_modulos": total_filas_modulo,
            "filas_validas_para_calibracion": validas_comparativo,
            "filas_excluidas_por_motor_previo": total_filas_comparativo - validas_comparativo,
            "corte_motor_valido": CORTE_MOTOR_CON_PUERTA_CALIDAD,
        },
        "pick_final": _con_confiabilidad(evaluados_final, aciertos_final, MUESTRA_MINIMA_WINRATE),
        "por_modulo": por_modulo,
        "fuente_por_modulo": fuente_por_modulo,
        "brier_score_poisson": _brier_score_multiclase(db),
        "advertencia_general": (
            "Estas métricas NO son una calibración estadística válida del motor todavía — "
            "son un conteo honesto de lo que hay hoy en la base de datos. Se muestra el número real "
            "aunque sea insuficiente, en vez de esconderlo o simular una calibración que no existe."
        ),
    }
