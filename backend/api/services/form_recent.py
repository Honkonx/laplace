"""services/form_recent.py — Análisis por forma reciente (últimos 5 partidos).

Port de form_recent.py — mismo HOME_ADVANTAGE_PCT=0.10, mismo
PROB_EMPATE_BASE=0.26. No tiene función `validar_*` en el original — siempre corre (usa
defaults de 2 victorias si no llegan datos), igual acá.
"""
from __future__ import annotations

from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import corregir_redondeo
from backend.api.services._matematica import safe_int as _safe_int

HOME_ADVANTAGE_PCT = 0.10
# Medido 2026-10-06 en 137.401 partidos históricos: empate = 26.3% (0.26 queda a 0.3 puntos, sin
# ajuste necesario). La ventaja de local de este módulo sí queda corta frente a lo medido (local
# 44.1%) pero es una decisión de forma, no de sesgo a Empate: no se toca sin walk-forward.
PROB_EMPATE_BASE = 0.26


def calcular_probs_forma(forma_local_wins: int, forma_visit_wins: int):
    ratio_local = forma_local_wins / 5.0
    ratio_visit = forma_visit_wins / 5.0

    total_ratios = ratio_local + ratio_visit
    if total_ratios == 0:
        ratio_local = ratio_visit = 0.5
        total_ratios = 1.0

    masa_1x2 = 1.0 - PROB_EMPATE_BASE
    prob_local_raw = masa_1x2 * (ratio_local / total_ratios)
    prob_visit_raw = masa_1x2 * (ratio_visit / total_ratios)
    prob_empate_raw = PROB_EMPATE_BASE

    ajuste = HOME_ADVANTAGE_PCT * prob_visit_raw
    prob_local_adj = prob_local_raw + ajuste
    prob_visit_adj = prob_visit_raw - ajuste
    prob_empate_adj = prob_empate_raw

    total = prob_local_adj + prob_empate_adj + prob_visit_adj
    if total <= 0:
        total = 1.0
    prob_local = prob_local_adj / total
    prob_empate = prob_empate_adj / total
    prob_visit = prob_visit_adj / total

    min_prob = 0.05
    if prob_local < min_prob:
        deficit = min_prob - prob_local
        prob_local = min_prob
        if prob_empate >= prob_visit:
            prob_empate -= deficit
        else:
            prob_visit -= deficit
    if prob_visit < min_prob:
        deficit = min_prob - prob_visit
        prob_visit = min_prob
        if prob_local >= prob_empate:
            prob_local -= deficit
        else:
            prob_empate -= deficit
    if prob_empate < min_prob:
        deficit = min_prob - prob_empate
        prob_empate = min_prob
        if prob_local >= prob_visit:
            prob_local -= deficit
        else:
            prob_visit -= deficit

    return corregir_redondeo(prob_local, prob_empate, prob_visit)


def calcular_score(forma_local_wins: int, forma_visit_wins: int, prob_ganador: float):
    score = 50
    penalizaciones: list[str] = []
    bonificaciones: list[str] = []

    if forma_local_wins >= 4:
        score += 12
        bonificaciones.append(f"Local {forma_local_wins}W últimos 5: +12")
    elif forma_local_wins == 3:
        score += 6
        bonificaciones.append("Local 3W últimos 5: +6")
    elif forma_local_wins <= 1:
        score -= 10
        penalizaciones.append(f"Local en racha negativa ({forma_local_wins}W/5): -10")

    if forma_visit_wins >= 4:
        score -= 10
        penalizaciones.append(f"Visitante en buena forma ({forma_visit_wins}W/5): -10")
    elif forma_visit_wins == 3:
        score -= 4
        penalizaciones.append("Visitante 3W últimos 5: -4")
    elif forma_visit_wins <= 1:
        score += 8
        bonificaciones.append(f"Visitante en racha negativa ({forma_visit_wins}W/5): +8")

    diff_forma = forma_local_wins - forma_visit_wins
    if diff_forma >= 3:
        score += 8
        bonificaciones.append(f"Diferencia de forma +{diff_forma}: +8")
    elif diff_forma <= -3:
        score -= 8
        penalizaciones.append(f"Diferencia de forma {diff_forma}: -8")

    if prob_ganador > 0.55:
        score += 8
        bonificaciones.append(f"Prob. ganador alta ({round(prob_ganador*100,1)}%): +8")
    elif prob_ganador < 0.38:
        score -= 8
        penalizaciones.append(f"Prob. ganador baja ({round(prob_ganador*100,1)}%): -8")

    if abs(diff_forma) <= 1 and forma_local_wins in (2, 3) and forma_visit_wins in (2, 3):
        score = min(score, 55)
        penalizaciones.append("Formas equilibradas — cap 55")

    score = _clamp(score, 10, 95)
    return score, penalizaciones, bonificaciones


def analizar(d: dict) -> dict:
    forma_local_wins = _clamp(_safe_int(d.get("forma_local_wins"), 2), 0, 5)
    forma_visit_wins = _clamp(_safe_int(d.get("forma_visit_wins"), 2), 0, 5)

    prob_local, prob_empate, prob_visit = calcular_probs_forma(forma_local_wins, forma_visit_wins)

    probs = {"Local": prob_local, "Empate": prob_empate, "Visitante": prob_visit}
    pick = max(probs, key=probs.get)
    prob_ganador = probs[pick]

    confianza_score, penalizaciones, bonificaciones = calcular_score(forma_local_wins, forma_visit_wins, prob_ganador)

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    score_para_claude = (
        f"Forma reciente: {d.get('local','Local')} {forma_local_wins}W/5 | "
        f"{d.get('visitante','Visitante')} {forma_visit_wins}W/5 | "
        f"Prob forma: Local {round(prob_local*100,1)}% Empate {round(prob_empate*100,1)}% "
        f"Visitante {round(prob_visit*100,1)}% | Score forma: {confianza_score}/100"
    )

    return {
        "ok": True,
        "fuente": "form_recent",
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
        "forma_local_wins": forma_local_wins,
        "forma_visit_wins": forma_visit_wins,
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
    }
