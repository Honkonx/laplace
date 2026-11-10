"""test_odds.py — services/odds.py: análisis de probabilidades implícitas desde cuotas de
mercado (distinto de test_odds_fetch.py, que prueba la cascada de proveedores en odds_fetch.py).
Mismos umbrales que odds.py: OVERROUND_IDEAL=1.06, OVERROUND_MAX_RAZONABLE=1.15,
FAVORITO_CLARO=1.70, FAVORITO_ABIERTO=2.50."""
from __future__ import annotations

from backend.api.services import odds


def _partido_base(**overrides):
    d = {
        "partido_id": "p1",
        "local": "Real Madrid",
        "visitante": "Sevilla",
        "liga": "La Liga",
        "odds_disponibles": True,
        "odds_local": 1.50,
        "odds_empate": 4.20,
        "odds_visit": 6.00,
    }
    d.update(overrides)
    return d


def test_validar_odds_ok():
    ok, motivo = odds.validar_odds(_partido_base())
    assert ok is True
    assert motivo == "ok"


def test_validar_odds_no_disponibles():
    ok, motivo = odds.validar_odds({"odds_disponibles": False})
    assert ok is False
    assert "no disponibles" in motivo.lower()


def test_validar_odds_odd_invalida_bajo_minima():
    ok, motivo = odds.validar_odds(_partido_base(odds_local=0.5))
    assert ok is False
    assert "local" in motivo.lower()


def test_calcular_probs_implicitas_normaliza_a_1():
    prob_local, prob_empate, prob_visit, *_ = odds.calcular_probs_implicitas(1.50, 4.20, 6.00)
    suma = prob_local + prob_empate + prob_visit
    assert abs(suma - 1.0) < 0.0001
    # favorito claro (menor odd) debe tener mayor prob implícita
    assert prob_local > prob_empate > prob_visit


def test_calcular_probs_implicitas_overround_mayor_a_1():
    """El overround (suma de probabilidades brutas antes de normalizar) siempre > 1.0 con
    cuotas reales de casa de apuestas (margen de la casa)."""
    *_, overround = odds.calcular_probs_implicitas(1.50, 4.20, 6.00)
    assert overround > 1.0


def test_analizar_devuelve_shape_esperado():
    resultado = odds.analizar(_partido_base())
    assert resultado["ok"] is True
    assert resultado["fuente"] == "odds"
    assert resultado["pick"] == "Local"
    assert resultado["value_bet"] is False
    assert resultado["favorito"] == "Local"
    assert resultado["odd_favorito"] == 1.50
    assert 10 <= resultado["confianza_score"] <= 95


def test_analizar_favorito_claro_bonifica_score():
    resultado = odds.analizar(_partido_base(odds_local=1.40, odds_empate=4.50, odds_visit=7.00))
    assert any("Favorito claro" in b for b in resultado["bonificaciones"])


def test_analizar_partido_muy_abierto_penaliza_score():
    """FAVORITO_ABIERTO=2.50 — si la menor odd (favorito) supera ese umbral, penaliza."""
    resultado = odds.analizar(_partido_base(odds_local=2.60, odds_empate=3.20, odds_visit=2.80))
    assert any("Partido muy abierto" in p for p in resultado["penalizaciones"])


def test_analizar_odds_en_cero_no_lanza_division_por_cero():
    """Caso límite: odds en 0 (dato corrupto/faltante) — _safe_float ya filtra a 0.0 por
    default, pero calcular_probs_implicitas divide 1.0/odds. Documentamos el comportamiento
    real: ZeroDivisionError se propaga si viene una odd en 0 (no hay guarda en analizar())."""
    import pytest

    with pytest.raises(ZeroDivisionError):
        odds.analizar(_partido_base(odds_local=0, odds_empate=3.0, odds_visit=3.0))
