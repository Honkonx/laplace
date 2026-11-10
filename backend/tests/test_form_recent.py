"""test_form_recent.py — análisis por forma reciente (últimos 5 partidos). Mismas constantes
que form_recent.py: HOME_ADVANTAGE_PCT=0.10, PROB_EMPATE_BASE=0.26."""
from __future__ import annotations

from backend.api.services import form_recent


def _partido_base(**overrides):
    d = {
        "partido_id": "p1",
        "local": "Liverpool",
        "visitante": "Everton",
        "liga": "Premier League",
        "forma_local_wins": 4,
        "forma_visit_wins": 1,
    }
    d.update(overrides)
    return d


def test_analizar_devuelve_shape_esperado():
    resultado = form_recent.analizar(_partido_base())
    assert resultado["ok"] is True
    assert resultado["fuente"] == "form_recent"
    assert resultado["pick"] in ("Local", "Empate", "Visitante")
    suma = resultado["prob_local"] + resultado["prob_empate"] + resultado["prob_visitante"]
    assert abs(suma - 1.0) < 0.001
    assert 10 <= resultado["confianza_score"] <= 95
    assert resultado["confianza"] in ("ALTA", "MEDIA", "BAJA")


def test_forma_local_dominante_favorece_al_local():
    resultado = form_recent.analizar(_partido_base(forma_local_wins=5, forma_visit_wins=0))
    assert resultado["pick"] == "Local"
    assert resultado["prob_local"] > resultado["prob_visitante"]


def test_probs_no_lanza_cuando_ambos_en_cero_victorias():
    """calcular_probs_forma: total_ratios == 0 -> ratio_local=ratio_visit=0.5 (caso especial
    documentado en el código para evitar división por cero). El ratio queda parejo, pero
    HOME_ADVANTAGE_PCT sigue aplicando después -> el local termina levemente por delante."""
    prob_local, prob_empate, prob_visit = form_recent.calcular_probs_forma(0, 0)
    assert prob_local > prob_visit
    assert abs((prob_local + prob_empate + prob_visit) - 1.0) < 0.0001


def test_home_advantage_pct_ajusta_a_favor_del_local():
    """Con forma idéntica (2 y 2), el ajuste HOME_ADVANTAGE_PCT debe inclinar la balanza
    levemente a favor del local respecto del visitante."""
    prob_local, _, prob_visit = form_recent.calcular_probs_forma(2, 2)
    assert prob_local > prob_visit


def test_calcular_score_bonifica_racha_positiva_local():
    score, _, bonificaciones = form_recent.calcular_score(4, 2, 0.5)
    assert any("+12" in b for b in bonificaciones)
    assert score > 50


def test_calcular_score_cap_55_con_formas_equilibradas():
    """Formas equilibradas (diff<=1, ambos en 2-3) -> cap explícito en 55."""
    score, penalizaciones, _ = form_recent.calcular_score(2, 3, 0.4)
    assert score <= 55
    assert any("cap 55" in p for p in penalizaciones)


def test_analizar_clampa_valores_fuera_de_rango_0_5():
    """Caso límite: forma_local_wins/forma_visit_wins fuera de [0,5] se clampan, no lanzan."""
    resultado = form_recent.analizar(_partido_base(forma_local_wins=99, forma_visit_wins=-3))
    assert resultado["forma_local_wins"] == 5
    assert resultado["forma_visit_wins"] == 0


def test_analizar_usa_default_2_si_falta_forma():
    """Sin datos de forma en el dict (no hay validar_* en el original, siempre corre) usa
    default de 2 victorias para ambos equipos."""
    resultado = form_recent.analizar({"partido_id": "p2", "local": "A", "visitante": "B"})
    assert resultado["forma_local_wins"] == 2
    assert resultado["forma_visit_wins"] == 2
    assert resultado["ok"] is True
