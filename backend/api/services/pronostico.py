"""
services/pronostico.py — Motor de análisis estadístico (Poisson + Dixon-Coles).

Port de pronostico.py — misma lógica, mismas constantes y fórmulas
(HOME_ADVANTAGE=0.35, DC_RHO=-0.13, umbral value bet 8%, cap de score por datos escasos).
Cambios reales vs el original:
  - Ya no es un script CLI (JSON por argv, JSON por stdout) — es una función de servicio.
  - LIGA_AVG se importa de services/ligas.py (antes vivía duplicada acá y en n8n).
  - `paths`/rutas Termux hardcodeadas eliminadas — ya no hace falta resolver dónde está
    db_query.py, el guardado (si aplica) lo hace el caller vía SQLAlchemy.
  - `guardar_en_db` ya no dispara un subprocess acá — el router decide si persiste (más
    fácil de testear: esta función es pura, sin side-effects de I/O).
"""
from __future__ import annotations

import math

from backend.api.services._matematica import safe_float as _safe_float, safe_int as _safe_int
from backend.api.services.ligas import DEFAULT_LIGA_AVG, HOME_ADVANTAGE, get_liga_avg

try:
    import numpy as np
    from scipy.stats import poisson as sp_poisson

    MOTOR = "scipy"
except ImportError:
    MOTOR = "math_puro"

DC_RHO = -0.13  # valor calibrado para fútbol. Rango válido: -0.20 a -0.05


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def tau_dc(x: int, y: int, lam_local: float, lam_visit: float, rho: float = DC_RHO) -> float:
    """Factor de corrección Dixon-Coles para el marcador (x, y). Solo ajusta los 4
    marcadores de baja puntuación; para el resto devuelve 1.0 (sin cambio)."""
    if x == 0 and y == 0:
        return 1.0 - lam_local * lam_visit * rho
    elif x == 0 and y == 1:
        return 1.0 + lam_local * rho
    elif x == 1 and y == 0:
        return 1.0 + lam_visit * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0


def aplicar_dixon_coles(matriz, lambda_local, lambda_visit, max_goles):
    tau_vals = {}
    for x in range(min(2, max_goles)):
        for y in range(min(2, max_goles)):
            t = tau_dc(x, y, lambda_local, lambda_visit)
            if abs(t - 1.0) > 1e-9:
                matriz[x][y] *= t
                tau_vals[f"{x}-{y}"] = round(t, 4)

    total = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles))
    if total > 0:
        for i in range(max_goles):
            for j in range(max_goles):
                matriz[i][j] /= total

    return matriz, tau_vals


def calcular_poisson_math(lambda_local: float, lambda_visit: float, max_goles: int = 10):
    matriz = [
        [poisson_pmf(i, lambda_local) * poisson_pmf(j, lambda_visit) for j in range(max_goles)]
        for i in range(max_goles)
    ]
    matriz, tau_vals = aplicar_dixon_coles(matriz, lambda_local, lambda_visit, max_goles)

    prob_local = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i > j)
    prob_empate = sum(matriz[i][i] for i in range(max_goles))
    prob_visitante = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if j > i)

    over25_prob = 1.0 - sum(
        matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j <= 2
    )
    btts_prob = (1 - poisson_pmf(0, lambda_local)) * (1 - poisson_pmf(0, lambda_visit))

    max_prob = 0.0
    marcador = "1-1"
    for i in range(min(5, max_goles)):
        for j in range(min(5, max_goles)):
            if matriz[i][j] > max_prob:
                max_prob = matriz[i][j]
                marcador = f"{i}-{j}"

    return prob_local, prob_empate, prob_visitante, over25_prob, btts_prob, marcador, tau_vals


def calcular_poisson_scipy(lambda_local: float, lambda_visit: float, max_goles: int = 10):
    pmf_local = [sp_poisson.pmf(i, lambda_local) for i in range(max_goles)]
    pmf_visit = [sp_poisson.pmf(i, lambda_visit) for i in range(max_goles)]
    matriz_np = np.outer(pmf_local, pmf_visit)
    matriz = [list(fila) for fila in matriz_np.tolist()]

    matriz, tau_vals = aplicar_dixon_coles(matriz, lambda_local, lambda_visit, max_goles)
    matriz_dc = np.array(matriz)

    prob_local = float(np.sum(np.tril(matriz_dc, -1)))
    prob_empate = float(np.sum(np.diag(matriz_dc)))
    prob_visitante = float(np.sum(np.triu(matriz_dc, 1)))

    over25_prob = 1.0 - float(
        sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j <= 2)
    )
    btts_prob = float((1 - sp_poisson.pmf(0, lambda_local)) * (1 - sp_poisson.pmf(0, lambda_visit)))

    idx = np.unravel_index(np.argmax(matriz_dc[:5, :5]), (5, 5))
    marcador = f"{idx[0]}-{idx[1]}"

    return prob_local, prob_empate, prob_visitante, over25_prob, btts_prob, marcador, tau_vals


def calcular_lambdas(d: dict, liga_avg: float) -> tuple[float, float]:
    """M4b (pesos dinámicos H2H) + M4c (home advantage) + xG (si BSD lo provee)."""
    default_goles = liga_avg / 2.0

    goles_local_avg = _safe_float(d.get("goles_local_avg"), default_goles)
    goles_visit_avg = _safe_float(d.get("goles_visit_avg"), default_goles * 0.85)
    goles_contra_local = _safe_float(d.get("goles_contra_local_avg"), default_goles * 0.85)
    goles_contra_visit = _safe_float(d.get("goles_contra_visit_avg"), default_goles)

    liga_avg_safe = liga_avg if liga_avg > 0 else DEFAULT_LIGA_AVG
    # `liga_avg` es el promedio de goles TOTALES por partido (2.6), pero los `goles_*_avg` de
    # entrada son goles POR EQUIPO (~1.3). La fórmula Dixon-Coles "ataque * defensa * media" debe
    # usar la media por equipo; con la media total los lambdas salían a la mitad (reproducido con
    # la instantánea real de pronosticos_experimentales: λ 0.74/0.36 para una liga de 2.6 goles,
    # suma 1.1, empate 0.45 en 11 de 11 picks). Ver docs/backend/ (ronda 2026-10-06, agente B).
    media_equipo = liga_avg_safe / 2.0

    ataque_local = goles_local_avg / media_equipo
    defensa_visit = goles_contra_visit / media_equipo
    ataque_visit = goles_visit_avg / media_equipo
    defensa_local = goles_contra_local / media_equipo

    lambda_local_base = ataque_local * defensa_visit * media_equipo
    lambda_visit_base = ataque_visit * defensa_local * media_equipo

    h2h_disponible = d.get("h2h_disponible", False)
    h2h_total = _safe_int(d.get("h2h_total"), 0)
    h2h_local_wins = _safe_int(d.get("h2h_local_wins"), 0)
    h2h_visit_wins = _safe_int(d.get("h2h_visit_wins"), 0)

    if h2h_disponible and h2h_total >= 5:
        peso_h2h = 0.5 if h2h_total >= 8 else 0.3
        tasa_local = h2h_local_wins / h2h_total
        tasa_visit = h2h_visit_wins / h2h_total
        factor_local_h2h = 0.9 + (tasa_local - 0.33) * (0.2 / 0.34)
        factor_visit_h2h = 0.9 + (tasa_visit - 0.33) * (0.2 / 0.34)
        factor_local_h2h = max(0.85, min(1.15, factor_local_h2h))
        factor_visit_h2h = max(0.85, min(1.15, factor_visit_h2h))

        lambda_local = lambda_local_base * (1 - peso_h2h) + lambda_local_base * factor_local_h2h * peso_h2h
        lambda_visit = lambda_visit_base * (1 - peso_h2h) + lambda_visit_base * factor_visit_h2h * peso_h2h
    else:
        lambda_local = lambda_local_base
        lambda_visit = lambda_visit_base

    ha_factor = HOME_ADVANTAGE / liga_avg_safe
    lambda_local *= 1 + ha_factor
    lambda_visit *= 1 - ha_factor * 0.5

    xg_local = _safe_float(d.get("xg_local"))
    xg_visit = _safe_float(d.get("xg_visit"))
    if xg_local is not None and xg_visit is not None and xg_local > 0 and xg_visit > 0:
        peso_xg = 0.30
        lambda_local = lambda_local * (1 - peso_xg) + xg_local * peso_xg
        lambda_visit = lambda_visit * (1 - peso_xg) + xg_visit * peso_xg

    lambda_local = max(0.3, min(5.0, lambda_local))
    lambda_visit = max(0.3, min(5.0, lambda_visit))

    return round(lambda_local, 3), round(lambda_visit, 3)


def _rango_central(probabilidades: list[float], cobertura: float = 0.65) -> str:
    """Menor rango contiguo de goles que cubre al menos la cobertura indicada.

    Es una descripción del rango más probable, no una promesa de marcador. Funciona sobre una
    distribución marginal ya normalizada y evita inventar una precisión de un solo resultado.
    """
    mejor: tuple[int, int] | None = None
    for inicio in range(len(probabilidades)):
        acumulada = 0.0
        for fin in range(inicio, len(probabilidades)):
            acumulada += probabilidades[fin]
            if acumulada >= cobertura:
                candidato = (inicio, fin)
                if mejor is None or (fin - inicio, inicio) < (mejor[1] - mejor[0], mejor[0]):
                    mejor = candidato
                break
    if mejor is None:
        return f"0-{len(probabilidades) - 1}"
    return str(mejor[0]) if mejor[0] == mejor[1] else f"{mejor[0]}-{mejor[1]}"


def calcular_mercados_avanzados(lambda_local: float, lambda_visit: float, max_goles: int = 10) -> dict:
    """Mercados derivados de la misma matriz Poisson+Dixon-Coles del motor.

    La prórroga no se estima: depende del formato de competición y de si el empate persiste
    tras 90 minutos. Se entrega `prob_empate_90` para que una capa futura con metadatos de copa
    pueda decidir si corresponde hablar de ella.
    """
    matriz = [[poisson_pmf(i, lambda_local) * poisson_pmf(j, lambda_visit) for j in range(max_goles)] for i in range(max_goles)]
    matriz, _ = aplicar_dixon_coles(matriz, lambda_local, lambda_visit, max_goles)
    marginal_local = [sum(matriz[i][j] for j in range(max_goles)) for i in range(max_goles)]
    marginal_visit = [sum(matriz[i][j] for i in range(max_goles)) for j in range(max_goles)]
    total = [sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j == goles) for goles in range(2 * max_goles - 1)]
    marcador_i, marcador_j = max(
        ((i, j) for i in range(max_goles) for j in range(max_goles)), key=lambda item: matriz[item[0]][item[1]]
    )
    empate_90 = sum(matriz[i][i] for i in range(max_goles))
    return {
        "marcador_probable": f"{marcador_i}-{marcador_j}",
        "prob_marcador_probable": round(matriz[marcador_i][marcador_j], 4),
        "rango_goles_local": _rango_central(marginal_local),
        "rango_goles_visitante": _rango_central(marginal_visit),
        "rango_goles_total": _rango_central(total),
        "goles_totales_esperados": round(lambda_local + lambda_visit, 3),
        "prob_empate_90": round(empate_90, 4),
        "prorroga": {"estimable": False, "probabilidad": None, "razon": "Requiere formato eliminatorio y contexto de serie; el motor solo estima 90 minutos."},
    }


def calcular_confianza(d: dict, prob_ganador, over25_prob, value_pct, pick_poisson, liga_avg):
    """M4d (contradicción H2H vs Poisson) + M4f (cap por datos escasos). Base 50, rango 10-95."""
    score = 50
    penalizaciones: list[str] = []
    bonificaciones: list[str] = []

    odds_local = _safe_float(d.get("odds_local"))
    odds_visit = _safe_float(d.get("odds_visit"))
    odds_disponibles = d.get("odds_disponibles", True)

    if odds_disponibles and odds_local > 0:
        mejor_odds = min(odds_local, odds_visit) if odds_visit > 0 else odds_local
        if mejor_odds < 1.5:
            score += 15
            bonificaciones.append("Favorito claro (odds < 1.5): +15")
        elif mejor_odds < 1.8:
            score += 8
            bonificaciones.append("Favorito moderado (odds < 1.8): +8")
        elif mejor_odds > 2.5:
            score -= 10
            penalizaciones.append("Partido abierto (odds > 2.5): -10")
    else:
        score -= 10
        penalizaciones.append("Odds no disponibles: -10")

    if d.get("forma_datos_reales", False):
        forma_local = _safe_int(d.get("forma_local_wins"), 0)
        forma_visit = _safe_int(d.get("forma_visit_wins"), 0)

        if forma_local >= 4:
            score += 10
            bonificaciones.append("Forma local excelente (4-5W): +10")
        elif forma_local <= 1:
            score -= 8
            penalizaciones.append("Forma local pobre (0-1W): -8")

        if forma_visit >= 4:
            score -= 8
            penalizaciones.append("Forma visitante excelente (contra nosotros): -8")

    h2h_disponible = d.get("h2h_disponible", True)
    h2h_total = _safe_int(d.get("h2h_total"), 0)

    if not h2h_disponible or h2h_total == 0:
        score -= 15
        penalizaciones.append("H2H no disponible: -15")
    else:
        h2h_local_wins = _safe_int(d.get("h2h_local_wins"), 0)
        h2h_ratio = h2h_local_wins / max(h2h_total, 1)
        if h2h_ratio > 0.6:
            score += 10
            bonificaciones.append("H2H favorable (>60% victorias): +10")
        elif h2h_ratio < 0.3:
            score -= 5
            penalizaciones.append("H2H desfavorable (<30% victorias): -5")

    if h2h_disponible and h2h_total >= 5:
        h2h_visit_wins = _safe_int(d.get("h2h_visit_wins"), 0)
        h2h_local_wins_val = _safe_int(d.get("h2h_local_wins"), 0)

        if h2h_local_wins_val > h2h_visit_wins:
            h2h_pick = "Local"
        elif h2h_visit_wins > h2h_local_wins_val:
            h2h_pick = "Visitante"
        else:
            h2h_pick = "Empate"

        dominio_h2h = max(h2h_local_wins_val, h2h_visit_wins) / h2h_total

        if h2h_pick != pick_poisson and dominio_h2h >= 0.6:
            penalizacion_contradiccion = 10 + round(dominio_h2h * 10)
            score -= penalizacion_contradiccion
            penalizaciones.append(
                f"Contradicción H2H ({h2h_pick}) vs Poisson ({pick_poisson}): -{penalizacion_contradiccion}"
            )

    pos_local = _safe_int(d.get("pos_local"), 10)
    pos_visit = _safe_int(d.get("pos_visit"), 10)

    if pos_local < 5 and pos_visit > 15:
        score += 15
        bonificaciones.append("Dominio de tabla (top5 vs bottom5): +15")
    elif pos_local > 15 and pos_visit < 5:
        score -= 15
        penalizaciones.append("Desventaja de tabla (bottom5 vs top5): -15")
    elif pos_local < pos_visit:
        score += 5
        bonificaciones.append("Local mejor ubicado en tabla: +5")

    if prob_ganador > 0.55:
        score += 8
        bonificaciones.append(f"Poisson alta confianza ({round(prob_ganador*100,1)}%): +8")
    elif prob_ganador < 0.35:
        score -= 8
        penalizaciones.append(f"Poisson baja confianza ({round(prob_ganador*100,1)}%): -8")

    # `value_pct` ya no suma al score: el value se calcula con la probabilidad del Poisson, que la
    # evaluación walk-forward 2026-09-29 no probó mejor que la tasa base ni que el mercado. El
    # parámetro se conserva por compatibilidad de firma; el dato queda solo como registro interno.

    tabla_real = not (pos_local == 10 and pos_visit == 10)
    fuentes_reales = sum(
        [
            1 if (h2h_disponible and h2h_total >= 5) else 0,
            1 if odds_disponibles else 0,
            1 if tabla_real else 0,
        ]
    )

    if fuentes_reales == 0:
        score = min(score, 35)
        penalizaciones.append("Datos insuficientes (0 fuentes reales): cap 35")
    elif fuentes_reales == 1:
        score = min(score, 55)
        if score == 55:
            penalizaciones.append("Datos escasos (1 fuente real): cap 55")

    score = max(10, min(95, score))
    return score, penalizaciones, bonificaciones


def calcular_value_bet(prob_real: float, odds: float) -> tuple[bool, float]:
    """Value = (prob_real * odds - 1) * 100. Umbral 8% (3% era ruido estadístico)."""
    if not odds or odds <= 0:
        return False, 0.0
    value = (prob_real * odds - 1) * 100
    return value > 8.0, round(value, 2)


def analizar(d: dict) -> dict:
    """Punto de entrada del motor Poisson+Dixon-Coles. `d` es un dict con el contrato de
    AnalisisInput (mismos campos que recibía pronostico.py por argv)."""
    liga_avg_input = _safe_float(d.get("liga_goles_avg"), DEFAULT_LIGA_AVG)
    liga_nombre = d.get("liga", "")
    liga_avg = get_liga_avg(liga_nombre, liga_avg_input)

    lambda_local, lambda_visit = calcular_lambdas(d, liga_avg)

    if MOTOR == "scipy":
        prob_local, prob_empate, prob_visit, over25, btts, marcador, tau_vals = calcular_poisson_scipy(
            lambda_local, lambda_visit
        )
    else:
        prob_local, prob_empate, prob_visit, over25, btts, marcador, tau_vals = calcular_poisson_math(
            lambda_local, lambda_visit
        )

    mercados_avanzados = calcular_mercados_avanzados(lambda_local, lambda_visit)

    probs = {"Local": prob_local, "Empate": prob_empate, "Visitante": prob_visit}
    pick = max(probs, key=probs.get)
    prob_ganador = probs[pick]

    odds_map = {
        "Local": _safe_float(d.get("odds_local")),
        "Empate": _safe_float(d.get("odds_empate")),
        "Visitante": _safe_float(d.get("odds_visit")),
    }
    odds_pick = odds_map.get(pick, 0)
    value_bet, value_pct = calcular_value_bet(prob_ganador, odds_pick)

    confianza_score, penalizaciones, bonificaciones = calcular_confianza(
        d, prob_ganador, over25, value_pct, pick, liga_avg
    )

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    score_para_claude = (
        f"Score estadístico: {confianza_score}/100 | "
        f"Motor: {MOTOR}+DixonColes(ρ={DC_RHO}) | "
        f"Poisson: Local {round(prob_local*100,1)}% "
        f"Empate {round(prob_empate*100,1)}% "
        f"Visitante {round(prob_visit*100,1)}% | "
        f"λ local={lambda_local} visit={lambda_visit} | "
        f"Over2.5: {round(over25*100,1)}% | "
        f"BTTS: {round(btts*100,1)}%"
    )

    return {
        "ok": True,
        "fuente": "poisson",
        "motor": MOTOR,
        "pick": pick,
        "prob_local": round(prob_local, 4),
        "prob_empate": round(prob_empate, 4),
        "prob_visitante": round(prob_visit, 4),
        "lambda_local": lambda_local,
        "lambda_visit": lambda_visit,
        "over25_prob": round(over25, 4),
        "btts_prob": round(btts, 4),
        # Dato interno NO validado: se calcula con la probabilidad Poisson sin evidencia de ventaja
        # sobre el mercado. No se muestra al usuario, no suma al score y no entra al prompt de IA.
        "value_bet": value_bet,
        "value_pct": value_pct,
        "value_bet_validado": False,
        "odds_pick": odds_pick,
        "confianza_score": confianza_score,
        "confianza": confianza,
        "marcador_probable": mercados_avanzados["marcador_probable"],
        "prob_marcador_probable": mercados_avanzados["prob_marcador_probable"],
        "rango_goles_local": mercados_avanzados["rango_goles_local"],
        "rango_goles_visitante": mercados_avanzados["rango_goles_visitante"],
        "rango_goles_total": mercados_avanzados["rango_goles_total"],
        "goles_totales_esperados": mercados_avanzados["goles_totales_esperados"],
        "prob_empate_90": mercados_avanzados["prob_empate_90"],
        "prorroga": mercados_avanzados["prorroga"],
        "score_para_claude": score_para_claude,
        "penalizaciones": penalizaciones,
        "bonificaciones": bonificaciones,
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
        "liga_avg_usado": round(liga_avg, 2),
        "dixon_coles": {"rho": DC_RHO, "tau_vals": tau_vals, "aplicado": True},
        "xg_usado": _safe_float(d.get("xg_local")) is not None and _safe_float(d.get("xg_local"), 0) > 0,
        "xg_local_input": _safe_float(d.get("xg_local")),
        "xg_visit_input": _safe_float(d.get("xg_visit")),
    }
