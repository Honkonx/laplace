"""services/odds.py — Análisis de probabilidades implícitas desde cuotas de mercado.

Port de odds.py — mismos umbrales (OVERROUND_IDEAL=1.06,
OVERROUND_MAX_RAZONABLE=1.15, FAVORITO_CLARO=1.70, etc.). `value_bet` siempre False —
odds.py no tiene una probabilidad propia de referencia para comparar (a diferencia de
pronostico.py, que sí calcula value bet contra su propia prob Poisson).
"""
from __future__ import annotations

from backend.api.ml import mercado
from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import normalizar_probabilidades
from backend.api.services._matematica import safe_bool as _safe_bool
from backend.api.services._matematica import safe_float as _safe_float_base

OVERROUND_MAX_RAZONABLE = 1.15
OVERROUND_IDEAL = 1.06
ODD_MINIMA = 1.01
FAVORITO_CLARO = 1.70
FAVORITO_ABIERTO = 2.50
MARGEN_DOMINANTE = 0.15


def _safe_float(val, default=0.0):
    """odds.py recibe cuotas de una fuente externa que a veces llegan NaN/Inf — a diferencia
    del resto de los módulos, acá se descartan explícitamente (ver _matematica.safe_float)."""
    return _safe_float_base(val, default, finito=True)


def validar_odds(d: dict) -> tuple[bool, str]:
    if not _safe_bool(d.get("odds_disponibles"), False):
        return False, "Odds no disponibles (odds_disponibles=false)"

    odds_local = _safe_float(d.get("odds_local"), 0.0)
    odds_empate = _safe_float(d.get("odds_empate"), 0.0)
    odds_visit = _safe_float(d.get("odds_visit"), 0.0)

    if odds_local < ODD_MINIMA:
        return False, f"Odd local inválida ({odds_local})"
    if odds_empate < ODD_MINIMA:
        return False, f"Odd empate inválida ({odds_empate})"
    if odds_visit < ODD_MINIMA:
        return False, f"Odd visitante inválida ({odds_visit})"

    return True, "ok"


def calcular_probs_implicitas(odds_local, odds_empate, odds_visit):
    prob_bruta_local = 1.0 / odds_local
    prob_bruta_empate = 1.0 / odds_empate
    prob_bruta_visit = 1.0 / odds_visit

    overround = prob_bruta_local + prob_bruta_empate + prob_bruta_visit

    # Método de Shin (2026-10-07): corrige el sesgo favorito-longshot que la normalización proporcional
    # deja intacto y es el mismo con el que se entrenó el apilador de `modelo_historico` y se midió el
    # mercado en la evaluación (mejora el log-loss 0,0006, IC95 excluye 0). Con overround <= 1 no hay
    # margen que repartir y `quitar_margen_shin` cae solo a la normalización proporcional.
    try:
        prob_local, prob_empate, prob_visit = mercado.quitar_margen_shin(odds_local, odds_empate, odds_visit)
    except (ValueError, ZeroDivisionError):
        prob_local, prob_empate, prob_visit = normalizar_probabilidades(
            prob_bruta_local, prob_bruta_empate, prob_bruta_visit, overround
        )

    return (
        prob_local,
        prob_empate,
        prob_visit,
        round(prob_bruta_local, 4),
        round(prob_bruta_empate, 4),
        round(prob_bruta_visit, 4),
        round(overround, 4),
    )


def calcular_score_odds(odds_local, odds_empate, odds_visit, prob_local, prob_empate, prob_visit,
                         overround, favorito, odd_favorito, prob_ganador):
    score = 50
    penalizaciones: list[str] = []
    bonificaciones: list[str] = []

    margen_pct = (overround - 1.0) * 100
    if overround <= OVERROUND_IDEAL:
        score += 8
        bonificaciones.append(f"Odds de calidad (margen {round(margen_pct,1)}%): +8")
    elif overround > OVERROUND_MAX_RAZONABLE:
        score -= 12
        penalizaciones.append(f"Odds de baja calidad (margen {round(margen_pct,1)}%): -12")

    if odd_favorito < FAVORITO_CLARO:
        score += 15
        bonificaciones.append(f"Favorito claro {favorito} (@{odd_favorito}): +15")
    elif odd_favorito < 2.00:
        score += 8
        bonificaciones.append(f"Favorito moderado {favorito} (@{odd_favorito}): +8")
    elif odd_favorito > FAVORITO_ABIERTO:
        score -= 12
        penalizaciones.append(f"Partido muy abierto (menor odd @{odd_favorito}): -12")

    probs_ord = sorted([prob_local, prob_empate, prob_visit], reverse=True)
    margen_picks = probs_ord[0] - probs_ord[1]
    if margen_picks >= MARGEN_DOMINANTE:
        score += 8
        bonificaciones.append(f"Diferencia de probabilidad amplia ({round(margen_picks*100,1)}pp): +8")
    elif margen_picks < 0.05:
        score -= 8
        penalizaciones.append(f"Probabilidades muy igualadas ({round(margen_picks*100,1)}pp): -8")

    if prob_ganador > 0.55:
        score += 5
        bonificaciones.append(f"Prob. implícita alta ({round(prob_ganador*100,1)}%): +5")
    elif prob_ganador < 0.38:
        score -= 5
        penalizaciones.append(f"Prob. implícita baja ({round(prob_ganador*100,1)}%): -5")

    if favorito == "Empate":
        score -= 5
        penalizaciones.append("Empate como favorito de mercado: -5")

    score = _clamp(score, 10, 95)
    return score, penalizaciones, bonificaciones


def analizar(d: dict) -> dict:
    odds_local = _safe_float(d.get("odds_local"), 0.0)
    odds_empate = _safe_float(d.get("odds_empate"), 0.0)
    odds_visit = _safe_float(d.get("odds_visit"), 0.0)

    (prob_local, prob_empate, prob_visit, prob_impl_local, prob_impl_empate, prob_impl_visit,
     overround) = calcular_probs_implicitas(odds_local, odds_empate, odds_visit)

    probs = {"Local": prob_local, "Empate": prob_empate, "Visitante": prob_visit}
    pick = max(probs, key=probs.get)
    prob_ganador = probs[pick]

    odds_map = {"Local": odds_local, "Empate": odds_empate, "Visitante": odds_visit}
    favorito = min(odds_map, key=odds_map.get)
    odd_favorito = odds_map[favorito]

    margen_pct = round((overround - 1.0) * 100, 2)

    confianza_score, penalizaciones, bonificaciones = calcular_score_odds(
        odds_local, odds_empate, odds_visit, prob_local, prob_empate, prob_visit,
        overround, favorito, odd_favorito, prob_ganador
    )

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    score_para_claude = (
        f"Odds: {d.get('local','Local')} @{odds_local} ({round(prob_impl_local*100,1)}% impl) | "
        f"Empate @{odds_empate} ({round(prob_impl_empate*100,1)}%) | "
        f"{d.get('visitante','Visitante')} @{odds_visit} ({round(prob_impl_visit*100,1)}%) | "
        f"Overround: {round(overround,3)} (+{margen_pct}%) | "
        f"Prob norm: Local {round(prob_local*100,1)}% Empate {round(prob_empate*100,1)}% "
        f"Visit {round(prob_visit*100,1)}% | Favorito mercado: {favorito} @{odd_favorito} | "
        f"Score odds: {confianza_score}/100"
    )

    return {
        "ok": True,
        "fuente": "odds",
        "pick": pick,
        "prob_local": prob_local,
        "prob_empate": prob_empate,
        "prob_visitante": prob_visit,
        "over25_prob": None,
        "btts_prob": None,
        "value_bet": False,
        "value_pct": 0.0,
        "confianza_score": confianza_score,
        "confianza": confianza,
        "marcador_probable": None,
        "score_para_claude": score_para_claude,
        "penalizaciones": penalizaciones,
        "bonificaciones": bonificaciones,
        "odds_local": odds_local,
        "odds_empate": odds_empate,
        "odds_visit": odds_visit,
        "prob_impl_local": prob_impl_local,
        "prob_impl_empate": prob_impl_empate,
        "prob_impl_visit": prob_impl_visit,
        "overround": overround,
        "margen_pct": margen_pct,
        "favorito": favorito,
        "odd_favorito": odd_favorito,
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
    }
