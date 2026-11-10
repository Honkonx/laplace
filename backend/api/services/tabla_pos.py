"""services/tabla_pos.py — Análisis por posición en tabla y momentum.

Port de tabla_pos.py — mismas zonas relativas (Champions/Europa/Mid-top/
Mid-bottom/Descenso), mismos umbrales de brecha (3/6/10) y momentum.
"""
from __future__ import annotations

from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import clamp_prob_minima, normalizar_probabilidades
from backend.api.services._matematica import safe_int as _safe_int

POS_DEFAULT = 10
LIGA_TAMANO_DEFAULT = 20

BRECHA_MINIMA = 3
BRECHA_MODERADA = 6
BRECHA_CLARA = 10

FORMA_ALTA = 4
FORMA_BAJA = 1

HOME_ADVANTAGE_TABLA = 0.04


def validar_tabla(d: dict) -> tuple[bool, str]:
    pos_local = _safe_int(d.get("pos_local"), POS_DEFAULT)
    pos_visit = _safe_int(d.get("pos_visit"), POS_DEFAULT)

    if pos_local == POS_DEFAULT and pos_visit == POS_DEFAULT:
        return False, "Sin datos de tabla (ambas posiciones son default 10/10)"
    if pos_local < 1 or pos_visit < 1:
        return False, f"Posición inválida (local={pos_local}, visit={pos_visit})"

    return True, "ok"


def calcular_zona(pos: int, n_equipos: int = LIGA_TAMANO_DEFAULT) -> str:
    ratio = pos / n_equipos
    if ratio <= 0.20:
        return "Champions"
    elif ratio <= 0.40:
        return "Europa"
    elif ratio <= 0.60:
        return "Mid-top"
    elif ratio <= 0.80:
        return "Mid-bottom"
    return "Descenso"


def zona_a_valor(zona: str) -> int:
    return {"Champions": 5, "Europa": 4, "Mid-top": 3, "Mid-bottom": 2, "Descenso": 1}.get(zona, 3)


def calcular_momentum(pos: int, forma_wins: int) -> str:
    en_forma = forma_wins >= FORMA_ALTA
    sin_forma = forma_wins <= FORMA_BAJA
    pos_baja = pos > 12
    pos_alta = pos <= 6

    if sin_forma and pos_alta:
        return "bajando"
    elif en_forma and pos_baja:
        return "subiendo"
    elif en_forma and pos_alta:
        return "estable_positivo"
    elif sin_forma and pos_baja:
        return "estable_negativo"
    return "estable"


# Punto de partida con posiciones iguales = frecuencias reales de resultado en 137.401 partidos
# históricos (football-data, 2026-10-06): local 44.1%, empate 26.3%, visitante 29.6%. Antes eran
# 40/28/32 (sin respaldo medido): sobrestimaban el empate 1.7 puntos y subestimaban al local 3.4.
BASE_LOCAL = 0.441
BASE_EMPATE = 0.263
BASE_VISITANTE = 0.296


def calcular_probs_tabla(pos_local, pos_visit, zona_local, zona_visit, momentum_local, momentum_visit):
    prob_local = BASE_LOCAL
    prob_empate = BASE_EMPATE
    prob_visit = BASE_VISITANTE

    brecha = pos_visit - pos_local
    ajuste_brecha = _clamp(brecha * 0.015, -0.20, 0.20)

    val_zona_local = zona_a_valor(zona_local)
    val_zona_visit = zona_a_valor(zona_visit)
    diff_zona = val_zona_local - val_zona_visit
    ajuste_zona = _clamp(diff_zona * 0.03, -0.09, 0.09)

    momentum_map = {
        "estable_positivo": 0.02,
        "subiendo": 0.03,
        "estable": 0.00,
        "estable_negativo": -0.02,
        "bajando": -0.03,
    }
    ajuste_mom_local = momentum_map.get(momentum_local, 0.0)
    ajuste_mom_visit = momentum_map.get(momentum_visit, 0.0)

    ajuste_total = ajuste_brecha + ajuste_zona + ajuste_mom_local - ajuste_mom_visit

    prob_local += ajuste_total
    prob_visit -= ajuste_total * 0.7
    prob_empate = 1.0 - prob_local - prob_visit

    prob_local, prob_empate, prob_visit = clamp_prob_minima(prob_local, prob_empate, prob_visit)
    total = prob_local + prob_empate + prob_visit

    return normalizar_probabilidades(prob_local, prob_empate, prob_visit, total)


def calcular_score_tabla(pos_local, pos_visit, zona_local, zona_visit, momentum_local, momentum_visit,
                          brecha, prob_ganador):
    score = 50
    penalizaciones: list[str] = []
    bonificaciones: list[str] = []

    if brecha >= BRECHA_CLARA:
        score += 15
        bonificaciones.append(f"Brecha de tabla clara ({brecha} pos): +15")
    elif brecha >= BRECHA_MODERADA:
        score += 8
        bonificaciones.append(f"Brecha de tabla moderada ({brecha} pos): +8")
    elif brecha >= BRECHA_MINIMA:
        score += 4
        bonificaciones.append(f"Brecha de tabla leve ({brecha} pos): +4")
    elif abs(brecha) < BRECHA_MINIMA:
        score -= 8
        penalizaciones.append(f"Posiciones muy similares (brecha {abs(brecha)}): -8")

    if brecha < -BRECHA_MODERADA:
        score -= 8
        penalizaciones.append(f"Visitante mucho mejor posicionado ({abs(brecha)} pos): -8")

    val_local = zona_a_valor(zona_local)
    val_visit = zona_a_valor(zona_visit)
    diff_zona = val_local - val_visit

    if diff_zona >= 2:
        score += 10
        bonificaciones.append(f"Diferencia de zona clara ({zona_local} vs {zona_visit}): +10")
    elif diff_zona <= -2:
        score -= 10
        penalizaciones.append(f"Visitante en zona superior ({zona_visit} vs {zona_local}): -10")
    elif diff_zona == 0:
        score -= 5
        penalizaciones.append(f"Misma zona ({zona_local}): -5")

    if momentum_local == "subiendo":
        score += 6
        bonificaciones.append("Local con momentum ascendente: +6")
    elif momentum_local == "bajando":
        score -= 6
        penalizaciones.append("Local con momentum descendente: -6")

    if momentum_visit == "subiendo":
        score -= 5
        penalizaciones.append("Visitante con momentum ascendente: -5")
    elif momentum_visit == "bajando":
        score += 5
        bonificaciones.append("Visitante con momentum descendente: +5")

    if prob_ganador > 0.55:
        score += 5
        bonificaciones.append(f"Prob. resultante alta ({round(prob_ganador*100,1)}%): +5")
    elif prob_ganador < 0.38:
        score -= 5
        penalizaciones.append(f"Prob. resultante baja ({round(prob_ganador*100,1)}%): -5")

    if zona_local == "Descenso" and zona_visit == "Descenso":
        score = min(score, 50)
        penalizaciones.append("Ambos en zona de descenso — volatilidad alta: cap 50")

    score = _clamp(score, 10, 95)
    return score, penalizaciones, bonificaciones


def analizar(d: dict) -> dict:
    pos_local = _safe_int(d.get("pos_local"), POS_DEFAULT)
    pos_visit = _safe_int(d.get("pos_visit"), POS_DEFAULT)
    forma_lw = _clamp(_safe_int(d.get("forma_local_wins"), 2), 0, 5)
    forma_vw = _clamp(_safe_int(d.get("forma_visit_wins"), 2), 0, 5)

    pos_local = max(1, pos_local)
    pos_visit = max(1, pos_visit)

    brecha = pos_visit - pos_local

    if pos_local < pos_visit:
        favorito_tabla = "Local"
    elif pos_visit < pos_local:
        favorito_tabla = "Visitante"
    else:
        favorito_tabla = "Empate"

    zona_local = calcular_zona(pos_local)
    zona_visit = calcular_zona(pos_visit)
    ventaja_zona = zona_local != zona_visit

    momentum_local = calcular_momentum(pos_local, forma_lw)
    momentum_visit = calcular_momentum(pos_visit, forma_vw)

    prob_local, prob_empate, prob_visit = calcular_probs_tabla(
        pos_local, pos_visit, zona_local, zona_visit, momentum_local, momentum_visit
    )

    probs = {"Local": prob_local, "Empate": prob_empate, "Visitante": prob_visit}
    pick = max(probs, key=probs.get)
    prob_ganador = probs[pick]

    confianza_score, penalizaciones, bonificaciones = calcular_score_tabla(
        pos_local, pos_visit, zona_local, zona_visit, momentum_local, momentum_visit, brecha, prob_ganador
    )

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    score_para_claude = (
        f"Tabla: {d.get('local','Local')} pos{pos_local} ({zona_local}) vs "
        f"{d.get('visitante','Visitante')} pos{pos_visit} ({zona_visit}) | Brecha: {brecha:+d} | "
        f"Momentum: local={momentum_local} visit={momentum_visit} | "
        f"Prob tabla: Local {round(prob_local*100,1)}% Empate {round(prob_empate*100,1)}% "
        f"Visitante {round(prob_visit*100,1)}% | Score tabla: {confianza_score}/100"
    )

    return {
        "ok": True,
        "fuente": "tabla_pos",
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
        "pos_local": pos_local,
        "pos_visit": pos_visit,
        "brecha_pos": brecha,
        "favorito_tabla": favorito_tabla,
        "zona_local": zona_local,
        "zona_visit": zona_visit,
        "momentum_local": momentum_local,
        "momentum_visit": momentum_visit,
        "ventaja_zona": ventaja_zona,
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
    }
