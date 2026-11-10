"""test_pronostico.py — verifica que el port preserva la lógica exacta de
pronostico.py (mismas constantes: HOME_ADVANTAGE=0.35, DC_RHO=-0.13, umbral
value bet 8%, cap de score por datos escasos)."""
from __future__ import annotations

from backend.api.services import pronostico


def _partido_base(**overrides):
    d = {
        "local": "Real Madrid",
        "visitante": "Barcelona",
        "liga": "La Liga",
        "partido_id": "abc123",
        "goles_local_avg": 1.8,
        "goles_visit_avg": 1.2,
        "goles_contra_local_avg": 0.9,
        "goles_contra_visit_avg": 1.4,
        "liga_goles_avg": 2.6,
        "pos_local": 2,
        "pos_visit": 1,
        "forma_local_wins": 3,
        "forma_visit_wins": 4,
        "h2h_local_wins": 4,
        "h2h_visit_wins": 3,
        "h2h_empates": 3,
        "h2h_total": 10,
        "h2h_disponible": True,
        "odds_local": 2.10,
        "odds_empate": 3.20,
        "odds_visit": 3.50,
        "odds_disponibles": True,
    }
    d.update(overrides)
    return d


def test_analizar_devuelve_shape_esperado():
    resultado = pronostico.analizar(_partido_base())
    assert resultado["ok"] is True
    assert resultado["pick"] in ("Local", "Empate", "Visitante")
    assert 0.0 <= resultado["prob_local"] <= 1.0
    assert 0.0 <= resultado["prob_empate"] <= 1.0
    assert 0.0 <= resultado["prob_visitante"] <= 1.0
    # Las 3 probabilidades deben sumar ~1.0 (Dixon-Coles renormaliza)
    suma = resultado["prob_local"] + resultado["prob_empate"] + resultado["prob_visitante"]
    assert abs(suma - 1.0) < 0.01
    assert 10 <= resultado["confianza_score"] <= 95
    assert resultado["dixon_coles"]["rho"] == -0.13
    assert resultado["rango_goles_local"]
    assert resultado["rango_goles_visitante"]
    assert resultado["rango_goles_total"]
    assert resultado["prorroga"]["estimable"] is False
    assert resultado["prorroga"]["probabilidad"] is None


def test_home_advantage_favorece_al_local():
    """Con estadísticas idénticas para ambos equipos, el local debe tener lambda mayor
    (HOME_ADVANTAGE=0.35 en calcular_lambdas)."""
    d = _partido_base(
        goles_local_avg=1.5, goles_visit_avg=1.5,
        goles_contra_local_avg=1.0, goles_contra_visit_avg=1.0,
        h2h_disponible=False, h2h_total=0,
    )
    resultado = pronostico.analizar(d)
    assert resultado["lambda_local"] > resultado["lambda_visit"]


def test_value_bet_umbral_8_porciento():
    """calcular_value_bet: value = (prob*odds - 1)*100, solo True si > 8.0 (M4e)."""
    # prob 0.50 * odds 2.20 = 1.10 -> value 10.0% -> True
    assert pronostico.calcular_value_bet(0.50, 2.20) == (True, 10.0)
    # prob 0.50 * odds 2.10 = 1.05 -> value 5.0% -> False (bajo el umbral de 8%)
    ok, pct = pronostico.calcular_value_bet(0.50, 2.10)
    assert ok is False
    assert pct == 5.0


def test_value_bet_sin_odds():
    assert pronostico.calcular_value_bet(0.5, 0) == (False, 0.0)


def test_confianza_cap_por_datos_escasos():
    """M4f: 0 fuentes reales (sin H2H, sin odds, tabla default 10/10) -> cap score 35."""
    d = {
        "odds_disponibles": False,
        "h2h_disponible": False,
        "h2h_total": 0,
        "pos_local": 10,
        "pos_visit": 10,
        "forma_local_wins": 2,
        "forma_visit_wins": 2,
    }
    score, penalizaciones, _ = pronostico.calcular_confianza(d, 0.45, 0.5, 0.0, "Local", 2.6)
    assert score <= 35
    assert any("0 fuentes reales" in p for p in penalizaciones)


def test_get_liga_avg_conocida_vs_default():
    from backend.api.services.ligas import DEFAULT_LIGA_AVG, get_liga_avg

    # "Premier League" NO se usa acá a propósito — desde 2026-09-09 es una clave ambigua en el
    # origen de datos (misma etiqueta cubre Inglaterra, Kazajistán, Bosnia, Egipto y Tanzania,
    # ver test_services_ligas.py::test_premier_league_queda_como_ambigua_no_como_inglaterra).
    assert get_liga_avg("Bundesliga", 2.6) == 3.03
    assert get_liga_avg("Liga Desconocida XYZ", 2.6) == 2.6  # input razonable, se usa
    assert get_liga_avg("Liga Desconocida XYZ", 10.0) == DEFAULT_LIGA_AVG  # input fuera de rango


def test_dixon_coles_tau_valores_conocidos():
    """tau_dc con rho=-0.13 en (0,0) con lambdas=1.0,1.0: 1 - 1*1*(-0.13) = 1.13"""
    assert pronostico.tau_dc(0, 0, 1.0, 1.0) == 1.13
    assert pronostico.tau_dc(1, 1, 1.0, 1.0) == 1.13  # 1 - rho = 1 - (-0.13)
    assert pronostico.tau_dc(2, 2, 1.0, 1.0) == 1.0  # fuera de los 4 marcadores ajustados


# ── Sesgo a Empate (2026-10-06) ──────────────────────────────────────────────────────────────
# Causa raíz: `calcular_lambdas` dividía los goles POR EQUIPO (~1.3) entre el promedio de la liga
# en goles TOTALES por partido (2.6) y multiplicaba por esa misma media total, así que los λ
# salían a la mitad. Con λ ~0.7/0.4 el 0-0 y el 1-1 dominan y el empate sube a 0.45-0.60.
# Medido walk-forward con 32.637 partidos reales (>= 2023-07-01): antes el pick era Empate en
# 55.1% de los partidos con P(empate) media 0.403; la frecuencia real de empate es 26.5%.

# Instantáneas reales de `pronosticos_experimentales.datos_json` (BD real, 2026-09/10) cuyos
# picks salieron Empate con prob_empate 0.44-0.61 antes del arreglo.
INSTANTANEAS_REALES = [
    dict(liga="Liga Profesional Argentina", goles_local_avg=1.1, goles_visit_avg=1.1,
         goles_contra_local_avg=0.7, goles_contra_visit_avg=1.2, liga_goles_avg=2.43,
         odds_local=1.67, odds_empate=3.4, odds_visit=5.0),
    dict(liga="Liga Profesional Argentina", goles_local_avg=1.2, goles_visit_avg=0.7,
         goles_contra_local_avg=0.8, goles_contra_visit_avg=1.2, liga_goles_avg=2.43,
         odds_local=1.85, odds_empate=3.0, odds_visit=4.5),
    dict(liga="Liga Profesional Argentina", goles_local_avg=0.5, goles_visit_avg=0.7,
         goles_contra_local_avg=0.8, goles_contra_visit_avg=1.3, liga_goles_avg=2.43,
         odds_local=1.85, odds_empate=2.9, odds_visit=4.6),
    dict(liga="Primera C", goles_local_avg=1.5, goles_visit_avg=0.8,
         goles_contra_local_avg=0.7, goles_contra_visit_avg=0.9, liga_goles_avg=2.6),
    dict(liga="Primera C", goles_local_avg=0.7, goles_visit_avg=1.0,
         goles_contra_local_avg=1.3, goles_contra_visit_avg=0.8, liga_goles_avg=2.6),
]


def _entrada_real(instantanea):
    d = dict(instantanea, local="L", visitante="V", partido_id="x", h2h_disponible=False, h2h_total=0,
             pos_local=10, pos_visit=10)
    d["odds_disponibles"] = d.get("odds_local") is not None
    return d


def test_instantanea_real_ya_no_produce_empate_espurio():
    """Reproduce la entrada real que daba λ 0.62/0.30 y Empate 0.495 (clamp mínimo 0.3 incluido)."""
    r = pronostico.analizar(_entrada_real(INSTANTANEAS_REALES[0]))
    assert r["pick"] == "Local"
    assert r["prob_empate"] < 0.36
    # el equipo local marca ~1.1 y el visitante recibe ~1.2: λ_local debe rondar 1.0-1.5
    assert 1.0 <= r["lambda_local"] <= 1.6
    assert r["lambda_visit"] > 0.3  # ya no queda clavado en el mínimo del clamp
    assert 1.5 <= r["lambda_local"] + r["lambda_visit"] <= 3.2


def test_equipos_promedio_dan_empate_tipico_de_la_liga():
    """Dos equipos de promedio de liga: P(empate) debe estar cerca de la frecuencia real
    (~0.22-0.31), no en 0.45+."""
    d = _partido_base(
        goles_local_avg=1.3, goles_visit_avg=1.3, goles_contra_local_avg=1.3, goles_contra_visit_avg=1.3,
        liga_goles_avg=2.6, liga="Liga Desconocida", h2h_disponible=False, h2h_total=0,
    )
    r = pronostico.analizar(d)
    assert 0.22 <= r["prob_empate"] <= 0.31
    assert r["pick"] == "Local"  # ventaja de local sin otra información


def test_lote_variado_no_se_inclina_a_empate():
    """Falla si más del 40% de los picks de un conjunto variado de partidos son Empate."""
    picks = []
    for gf_l in (0.8, 1.1, 1.4, 1.8, 2.2):
        for gc_l in (0.8, 1.2, 1.6):
            for gf_v in (0.8, 1.1, 1.5, 1.9):
                for liga_avg in (2.3, 2.7, 3.0):
                    d = _partido_base(
                        goles_local_avg=gf_l, goles_contra_local_avg=gc_l,
                        goles_visit_avg=gf_v, goles_contra_visit_avg=1.2,
                        liga_goles_avg=liga_avg, liga="Liga Desconocida", h2h_disponible=False, h2h_total=0,
                    )
                    picks.append(pronostico.analizar(d)["pick"])
    proporcion_empate = picks.count("Empate") / len(picks)
    assert proporcion_empate <= 0.40, f"{proporcion_empate:.0%} de picks Empate sobre {len(picks)} partidos"
    # tampoco puede colapsar a un solo resultado
    assert len(set(picks)) >= 2


def test_lote_de_instantaneas_reales_no_se_inclina_a_empate():
    picks = [pronostico.analizar(_entrada_real(i))["pick"] for i in INSTANTANEAS_REALES]
    assert picks.count("Empate") / len(picks) <= 0.40


def test_lambdas_usan_la_media_por_equipo_no_la_total():
    """Unidad: con equipos de promedio de liga, λ_local + λ_visit ≈ goles totales de la liga
    (antes daban la mitad)."""
    for liga_avg in (2.2, 2.6, 3.1):
        por_equipo = liga_avg / 2
        d = dict(goles_local_avg=por_equipo, goles_visit_avg=por_equipo,
                 goles_contra_local_avg=por_equipo, goles_contra_visit_avg=por_equipo)
        lam_l, lam_v = pronostico.calcular_lambdas(d, liga_avg)
        assert abs((lam_l + lam_v) - liga_avg) <= 0.08 * liga_avg, (liga_avg, lam_l, lam_v)
        assert lam_l > lam_v  # ventaja de local


def test_lambdas_escalan_con_el_ataque_del_equipo():
    liga_avg = 2.6
    base = dict(goles_local_avg=1.3, goles_visit_avg=1.3, goles_contra_local_avg=1.3, goles_contra_visit_avg=1.3)
    fuerte = dict(base, goles_local_avg=2.0)
    assert pronostico.calcular_lambdas(fuerte, liga_avg)[0] > pronostico.calcular_lambdas(base, liga_avg)[0] * 1.4


def test_value_bet_no_suma_al_score_ni_entra_al_texto_para_ia():
    """El value se calcula con el Poisson (sin evidencia de ventaja sobre el mercado): queda como
    dato interno rotulado como no validado y no influye en score ni en el prompt."""
    d = _partido_base(odds_local=6.0, odds_empate=6.0, odds_visit=6.0)
    r = pronostico.analizar(d)
    assert r["value_bet_validado"] is False
    assert "Value" not in r["score_para_claude"]
    assert not any("Value bet" in b for b in r["bonificaciones"])
