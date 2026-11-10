"""services/h2h.py — Análisis exclusivo de historial Head to Head.

Port de h2h.py — misma lógica (suavizado de Laplace, HOME_ADVANTAGE_H2H=0.05,
umbrales de dominancia/muestra). `validar_h2h` devuelve (ok, razon) — si ok=False, el caller
(services/motor.py) saltea el módulo, igual que hacía datos.py antes de lanzarlo.
"""
from __future__ import annotations

from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import clamp_prob_minima, normalizar_probabilidades
from backend.api.services._matematica import safe_bool as _safe_bool
from backend.api.services._matematica import safe_int as _safe_int

MUESTRA_MINIMA = 3
MUESTRA_CONFIABLE = 5
MUESTRA_OPTIMA = 8

DOMINANCIA_CLARA = 0.60
DOMINANCIA_FUERTE = 0.70

HOME_ADVANTAGE_H2H = 0.05


def validar_h2h(d: dict) -> tuple[bool, str]:
    if not _safe_bool(d.get("h2h_disponible"), False):
        return False, "H2H no disponible (h2h_disponible=false)"

    h2h_total = _safe_int(d.get("h2h_total"), 0)
    if h2h_total < MUESTRA_MINIMA:
        return False, f"Muestra H2H insuficiente ({h2h_total} partidos, mínimo {MUESTRA_MINIMA})"

    return True, "ok"


def calcular_probs_h2h(h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total):
    pseudo_local = h2h_local_wins + 1
    pseudo_visit = h2h_visit_wins + 1
    pseudo_emp = h2h_empates + 1
    pseudo_total = h2h_total + 3

    prob_local_raw = pseudo_local / pseudo_total
    prob_visit_raw = pseudo_visit / pseudo_total
    prob_empate_raw = pseudo_emp / pseudo_total

    ajuste = HOME_ADVANTAGE_H2H
    prob_local_adj = prob_local_raw + ajuste
    prob_visit_adj = prob_visit_raw - ajuste
    prob_empate_adj = prob_empate_raw

    prob_local_adj, prob_empate_adj, prob_visit_adj = clamp_prob_minima(
        prob_local_adj, prob_empate_adj, prob_visit_adj
    )
    total = prob_local_adj + prob_visit_adj + prob_empate_adj

    return normalizar_probabilidades(prob_local_adj, prob_empate_adj, prob_visit_adj, total)


def detectar_tendencia(h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total):
    if h2h_total < 6:
        return "sin_datos"
    tasa_local = h2h_local_wins / h2h_total
    tasa_visit = h2h_visit_wins / h2h_total
    if tasa_local > 0.55:
        return "local_domina"
    elif tasa_visit > 0.55:
        return "visit_domina"
    return "equilibrado"


def calcular_score_h2h(h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total, prob_ganador, dominador, dominancia):
    score = 50
    penalizaciones: list[str] = []
    bonificaciones: list[str] = []

    if h2h_total >= MUESTRA_OPTIMA:
        score += 10
        bonificaciones.append(f"Muestra grande ({h2h_total} partidos): +10")
    elif h2h_total >= MUESTRA_CONFIABLE:
        score += 5
        bonificaciones.append(f"Muestra suficiente ({h2h_total} partidos): +5")
    else:
        penalidad = (MUESTRA_CONFIABLE - h2h_total) * 5
        score -= penalidad
        penalizaciones.append(f"Muestra pequeña ({h2h_total} partidos): -{penalidad}")

    if dominancia >= DOMINANCIA_FUERTE:
        score += 15
        bonificaciones.append(f"{dominador} domina H2H ({round(dominancia*100)}%): +15")
    elif dominancia >= DOMINANCIA_CLARA:
        score += 8
        bonificaciones.append(f"{dominador} ventaja H2H ({round(dominancia*100)}%): +8")
    elif dominancia < 0.40:
        score -= 5
        penalizaciones.append("H2H muy equilibrado (< 40% dominancia): -5")

    if h2h_total > 0:
        tasa_empate = h2h_empates / h2h_total
        if tasa_empate >= 0.40:
            score -= 8
            penalizaciones.append(f"Empates frecuentes en H2H ({round(tasa_empate*100)}%): -8")
        elif tasa_empate <= 0.15 and h2h_total >= 5:
            score += 5
            bonificaciones.append(f"Pocos empates en H2H ({round(tasa_empate*100)}%): +5")

    if prob_ganador > 0.55:
        score += 8
        bonificaciones.append(f"Prob. ganador alta ({round(prob_ganador*100, 1)}%): +8")
    elif prob_ganador < 0.38:
        score -= 8
        penalizaciones.append(f"Prob. ganador baja ({round(prob_ganador*100, 1)}%): -8")

    if abs(h2h_local_wins - h2h_visit_wins) <= 1 and h2h_empates >= h2h_total * 0.30:
        score = min(score, 52)
        penalizaciones.append("H2H equilibrado con muchos empates: cap 52")

    score = _clamp(score, 10, 95)
    return score, penalizaciones, bonificaciones


def analizar(d: dict) -> dict:
    h2h_local_wins = _safe_int(d.get("h2h_local_wins"), 0)
    h2h_visit_wins = _safe_int(d.get("h2h_visit_wins"), 0)
    h2h_empates = _safe_int(d.get("h2h_empates"), 0)
    h2h_total = _safe_int(d.get("h2h_total"), 0)

    suma_real = h2h_local_wins + h2h_visit_wins + h2h_empates
    if suma_real > h2h_total:
        h2h_total = suma_real

    prob_local, prob_empate, prob_visit = calcular_probs_h2h(h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total)

    probs = {"Local": prob_local, "Empate": prob_empate, "Visitante": prob_visit}
    pick = max(probs, key=probs.get)
    prob_ganador = probs[pick]

    if h2h_total > 0:
        tasa_local = h2h_local_wins / h2h_total
        tasa_visit = h2h_visit_wins / h2h_total
        if tasa_local >= tasa_visit:
            dominador, dominancia = "Local", tasa_local
        else:
            dominador, dominancia = "Visitante", tasa_visit
    else:
        dominador, dominancia = "Empate", 0.0

    tendencia = detectar_tendencia(h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total)

    confianza_score, penalizaciones, bonificaciones = calcular_score_h2h(
        h2h_local_wins, h2h_visit_wins, h2h_empates, h2h_total, prob_ganador, dominador, dominancia
    )

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    score_para_claude = (
        f"H2H: {d.get('local','Local')} {h2h_local_wins}W-{h2h_empates}E-{h2h_visit_wins}V "
        f"({h2h_total} partidos) | Dominancia {dominador}: {round(dominancia*100)}% | "
        f"Tendencia: {tendencia} | Prob H2H: Local {round(prob_local*100,1)}% "
        f"Empate {round(prob_empate*100,1)}% Visitante {round(prob_visit*100,1)}% | "
        f"Score H2H: {confianza_score}/100"
    )

    return {
        "ok": True,
        "fuente": "h2h",
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
        "h2h_local_wins": h2h_local_wins,
        "h2h_visit_wins": h2h_visit_wins,
        "h2h_empates": h2h_empates,
        "h2h_total": h2h_total,
        "dominancia": round(dominancia, 4),
        "dominador": dominador,
        "tendencia": tendencia,
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
    }
