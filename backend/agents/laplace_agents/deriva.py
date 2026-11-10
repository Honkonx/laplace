"""laplace_agents/deriva.py — detector simple de deriva entre corridas: compara la distribución
de picks (`{pick: conteo}`, la misma que ya calcula `consistencia.detectar_uniformidad`) de la
corrida ACTUAL del agente contra la de la ÚLTIMA corrida registrada en la memoria propia
(`laplace_agents/memoria.py`), y marca una alerta honesta si la proporción de algún pick saltó
más de lo esperado entre corridas — el mismo tipo de anomalía que ya se investigó y arregló a
mano el 2026-09-09/10 (92.6% → 56.7% de picks "Empate" en un día real, ver `README.md`).

No es un modelo estadístico — mismo espíritu que `consistencia.py`: comparación simple de
proporciones con un umbral fijo y documentado, no calibrado con datos reales (todavía no hay
volumen suficiente de corridas reales para calibrarlo empíricamente)."""
from __future__ import annotations

# Muestra mínima en AMBAS corridas (actual y anterior) para que un delta signifique algo real —
# mismo criterio que `consistencia.MUESTRA_MINIMA_PARA_ALERTA` (5), aplicado acá a cada lado de
# la comparación por separado.
MUESTRA_MINIMA_PARA_COMPARAR = 5

# 0.25 = 25 puntos porcentuales de salto en la proporción de un mismo pick entre dos corridas.
# Más laxo que el 0.75 de `consistencia.UMBRAL_PORCENTAJE_ALERTA` a propósito: ese umbral mide
# el NIVEL absoluto de uniformidad dentro de una sola corrida (partidos todos iguales); este
# mide el CAMBIO entre dos corridas de partidos distintos (día a día), que tiene ruido natural
# esperable solo por tratarse de otro conjunto de partidos. Documentado, no calibrado con datos
# reales — mismo aviso honesto que ya lleva `consistencia.UMBRAL_PORCENTAJE_ALERTA`.
UMBRAL_DELTA_ALERTA = 0.25


def _proporciones(distribucion: dict[str, int]) -> dict[str, float]:
    total = sum(distribucion.values())
    if not total:
        return {}
    return {pick: conteo / total for pick, conteo in distribucion.items()}


def detectar_deriva(
    distribucion_actual: dict[str, int],
    distribucion_anterior: dict[str, int] | None,
    total_actual: int | None = None,
    total_anterior: int | None = None,
) -> dict:
    """Sin corrida anterior (memoria vacía o primera corrida real del agente) nunca hay alerta
    — no hay nada contra qué comparar. Con muestra chica en cualquiera de las dos corridas
    (< `MUESTRA_MINIMA_PARA_COMPARAR`) tampoco: un delta calculado sobre pocos partidos no
    significa nada real, mismo criterio que ya aplica `consistencia.py` dentro de una corrida.

    `total_actual`/`total_anterior` opcionales — si no se pasan, se derivan sumando los
    conteos de cada distribución (permite pasar el total real ya calculado por el caller, ej.
    `total_analizados_con_pick`, sin recalcularlo)."""
    total_actual = total_actual if total_actual is not None else sum(distribucion_actual.values())
    total_anterior = (
        total_anterior if total_anterior is not None
        else (sum(distribucion_anterior.values()) if distribucion_anterior else 0)
    )

    resultado = {
        "hay_corrida_anterior": bool(distribucion_anterior),
        "proporciones_actual": _proporciones(distribucion_actual),
        "proporciones_anterior": _proporciones(distribucion_anterior) if distribucion_anterior else {},
        "deltas": {},
        "alerta_deriva": False,
        "pick_con_mayor_delta": None,
    }

    if (
        not distribucion_anterior
        or total_actual < MUESTRA_MINIMA_PARA_COMPARAR
        or total_anterior < MUESTRA_MINIMA_PARA_COMPARAR
    ):
        return resultado

    prop_actual = resultado["proporciones_actual"]
    prop_anterior = resultado["proporciones_anterior"]
    picks = set(prop_actual) | set(prop_anterior)
    deltas = {
        pick: round(prop_actual.get(pick, 0.0) - prop_anterior.get(pick, 0.0), 4)
        for pick in picks
    }
    resultado["deltas"] = deltas

    if deltas:
        pick_max, delta_max = max(deltas.items(), key=lambda kv: abs(kv[1]))
        if abs(delta_max) >= UMBRAL_DELTA_ALERTA:
            resultado["alerta_deriva"] = True
            resultado["pick_con_mayor_delta"] = pick_max

    return resultado
