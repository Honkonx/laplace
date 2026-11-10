"""test_h2h.py — services/h2h.py: análisis exclusivo de historial Head to Head (suavizado de
Laplace, HOME_ADVANTAGE_H2H=0.05). No existía test dedicado para este módulo — se agrega como
parte de la auditoría de deuda técnica 2026-09-09 (extracción de helpers matemáticos a
_matematica.py), que tocó calcular_probs_h2h como red de seguridad del refactor."""
from __future__ import annotations

from backend.api.services import h2h


def _partido_base(**overrides):
    d = {
        "partido_id": "p1",
        "local": "River Plate",
        "visitante": "Boca Juniors",
        "liga": "Liga Profesional",
        "h2h_disponible": True,
        "h2h_local_wins": 5,
        "h2h_visit_wins": 3,
        "h2h_empates": 2,
        "h2h_total": 10,
    }
    d.update(overrides)
    return d


def test_validar_h2h_no_disponible():
    ok, motivo = h2h.validar_h2h({"h2h_disponible": False})
    assert ok is False
    assert "no disponible" in motivo.lower()


def test_validar_h2h_muestra_insuficiente():
    ok, motivo = h2h.validar_h2h({"h2h_disponible": True, "h2h_total": 2})
    assert ok is False
    assert "insuficiente" in motivo.lower()


def test_validar_h2h_ok():
    ok, motivo = h2h.validar_h2h({"h2h_disponible": True, "h2h_total": 5})
    assert ok is True
    assert motivo == "ok"


def test_calcular_probs_h2h_suma_uno():
    prob_local, prob_empate, prob_visit = h2h.calcular_probs_h2h(5, 3, 2, 10)
    assert abs((prob_local + prob_empate + prob_visit) - 1.0) < 0.0001


def test_calcular_probs_h2h_home_advantage_favorece_local_con_empate_de_victorias():
    """Con victorias empatadas (3-3), el suavizado de Laplace da probs base iguales para
    local/visitante — HOME_ADVANTAGE_H2H=0.05 debe inclinar la balanza a favor del local."""
    prob_local, _, prob_visit = h2h.calcular_probs_h2h(3, 3, 4, 10)
    assert prob_local > prob_visit


def test_calcular_probs_h2h_sin_historial_no_lanza():
    """h2h_total=0 -> suavizado de Laplace evita división por cero (pseudo_total=3)."""
    prob_local, prob_empate, prob_visit = h2h.calcular_probs_h2h(0, 0, 0, 0)
    assert abs((prob_local + prob_empate + prob_visit) - 1.0) < 0.0001
    assert prob_local > 0 and prob_empate > 0 and prob_visit > 0


def test_detectar_tendencia_requiere_minimo_6_partidos():
    assert h2h.detectar_tendencia(3, 1, 1, 5) == "sin_datos"
    assert h2h.detectar_tendencia(5, 1, 0, 6) == "local_domina"
    assert h2h.detectar_tendencia(1, 5, 0, 6) == "visit_domina"
    assert h2h.detectar_tendencia(3, 3, 2, 8) == "equilibrado"


def test_analizar_devuelve_shape_esperado():
    resultado = h2h.analizar(_partido_base())
    assert resultado["ok"] is True
    assert resultado["fuente"] == "h2h"
    assert resultado["pick"] in ("Local", "Empate", "Visitante")
    suma = resultado["prob_local"] + resultado["prob_empate"] + resultado["prob_visitante"]
    assert abs(suma - 1.0) < 0.001
    assert 10 <= resultado["confianza_score"] <= 95
    assert resultado["confianza"] in ("ALTA", "MEDIA", "BAJA")


def test_analizar_dominancia_clara_bonifica_score():
    resultado = h2h.analizar(_partido_base(h2h_local_wins=8, h2h_visit_wins=0, h2h_empates=0, h2h_total=8))
    assert resultado["dominador"] == "Local"
    assert any("domina H2H" in b or "ventaja H2H" in b for b in resultado["bonificaciones"])


def test_analizar_empates_frecuentes_penaliza_score():
    resultado = h2h.analizar(_partido_base(h2h_local_wins=1, h2h_visit_wins=1, h2h_empates=8, h2h_total=10))
    assert any("Empates frecuentes" in p for p in resultado["penalizaciones"])


def test_analizar_muestra_real_mayor_a_declarada_se_corrige():
    """Si local+visit+empates > h2h_total declarado, h2h_total se corrige a la suma real
    (bug guard existente en analizar(), no introducido por este refactor)."""
    resultado = h2h.analizar(_partido_base(h2h_local_wins=5, h2h_visit_wins=3, h2h_empates=2, h2h_total=1))
    assert resultado["h2h_total"] == 10
