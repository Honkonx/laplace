"""deriva.py — alerta de deriva de lo que el modelo está produciendo (MP-12 del plan `11_PLAN_MODELO_PREDICTIVO…`).

La deriva del ERROR (RPS en vivo frente al histórico) es `MD-13`; esta es la deriva de lo que ENTRA y SALE: si la distribución de las probabilidades que el modelo da hoy se aparta de la de las semanas anteriores
(PSI, índice de estabilidad de población) algo cambió en los datos, en una fuente o en el modelo. Es una alarma, no un veredicto: no cambia ningún pronóstico y exige un mínimo de pronósticos para no dispararse con ruido.
PSI < 0,1 estable; 0,1–0,25 cambio moderado; > 0,25 cambio grande (convención de la industria); aquí la alarma salta en `UMBRAL_ALARMA`.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.ml_modelo import MlPrediccion

UMBRAL_ALARMA = 0.25
MINIMO_POR_VENTANA = 60
DIAS_RECIENTES = 30
DIAS_REFERENCIA = 120
CLASES = ("local", "empate", "visitante")


def psi(referencia: list[float], nuevo: list[float], tramos: int = 10, epsilon: float = 1e-4) -> float:
    """Índice de estabilidad de población entre dos muestras: los tramos son los deciles de la REFERENCIA. 0 = misma distribución."""
    if not referencia or not nuevo:
        raise ValueError("se necesitan datos en las dos muestras")
    orden = sorted(referencia)
    cortes = sorted({orden[min(len(orden) - 1, int(len(orden) * k / tramos))] for k in range(1, tramos)})

    def proporciones(valores: list[float]) -> list[float]:
        cuentas = [0] * (len(cortes) + 1)
        for v in valores:
            cuentas[sum(1 for c in cortes if v > c)] += 1
        return [max(c / len(valores), epsilon) for c in cuentas]

    p, q = proporciones(referencia), proporciones(nuevo)
    return sum((b - a) * math.log(b / a) for a, b in zip(p, q, strict=True))


def deriva_de_variables(referencia: dict[str, list[float]], nuevo: dict[str, list[float]], umbral: float = UMBRAL_ALARMA) -> dict:
    """PSI de cada variable (por columna) entre dos conjuntos; `alarma` si alguna supera el umbral. Sirve para las variables de entrada del entrenamiento frente a las de hoy."""
    valores = {k: round(psi(referencia[k], nuevo[k]), 4) for k in referencia if k in nuevo and referencia[k] and nuevo[k]}
    peor = max(valores, key=valores.get) if valores else None
    return {"psi": valores, "peor": peor, "umbral": umbral, "alarma": bool(peor and valores[peor] > umbral)}


def _probabilidades(db: Session, modelo_id: int, desde: datetime, hasta: datetime) -> dict[str, list[float]]:
    salida: dict[str, list[float]] = {c: [] for c in CLASES}
    consulta = select(MlPrediccion.probabilidades_json).where(MlPrediccion.modelo_id == modelo_id, MlPrediccion.creada_en >= desde.strftime("%Y-%m-%dT%H:%M:%S"),
                                                              MlPrediccion.creada_en < hasta.strftime("%Y-%m-%dT%H:%M:%S"))
    for (texto,) in db.execute(consulta):
        try:
            p = json.loads(texto)
            for c in CLASES:
                salida[c].append(float(p[c]))
        except (ValueError, KeyError, TypeError):
            continue
    return salida


def deriva_de_salidas(db: Session, modelo_id: int, ahora: datetime | None = None, umbral: float = UMBRAL_ALARMA) -> dict:
    """Compara las probabilidades de los últimos `DIAS_RECIENTES` días con las de los `DIAS_REFERENCIA` anteriores, del mismo modelo. Sin `MINIMO_POR_VENTANA` pronósticos en cada ventana no dice nada (no hay base)."""
    ahora = ahora or datetime.now(UTC).replace(tzinfo=None)
    inicio_reciente = ahora - timedelta(days=DIAS_RECIENTES)
    ref = _probabilidades(db, modelo_id, inicio_reciente - timedelta(days=DIAS_REFERENCIA), inicio_reciente)
    rec = _probabilidades(db, modelo_id, inicio_reciente, ahora + timedelta(days=1))
    n_ref, n_rec = len(ref["local"]), len(rec["local"])
    informe = {"modelo_id": modelo_id, "n_referencia": n_ref, "n_reciente": n_rec, "umbral": umbral, "minimo_por_ventana": MINIMO_POR_VENTANA}
    if n_ref < MINIMO_POR_VENTANA or n_rec < MINIMO_POR_VENTANA:
        return {**informe, "alarma": False, "psi": {}, "motivo": f"sin pronósticos suficientes para comparar (mínimo {MINIMO_POR_VENTANA} en cada ventana)"}
    valores = {c: round(psi(ref[c], rec[c]), 4) for c in CLASES}
    peor = max(valores, key=valores.get)
    return {**informe, "psi": valores, "peor": peor, "alarma": valores[peor] > umbral, "motivo": f"la probabilidad de «{peor}» cambió de distribución (PSI {valores[peor]})" if valores[peor] > umbral else "estable"}
