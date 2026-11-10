"""test_tabla_pos.py — análisis por posición en tabla y momentum. Mismas zonas relativas
(Champions/Europa/Mid-top/Mid-bottom/Descenso) y umbrales de brecha (3/6/10) que
tabla_pos.py."""
from __future__ import annotations

from backend.api.services import tabla_pos


def _partido_base(**overrides):
    d = {
        "partido_id": "p1",
        "local": "Manchester City",
        "visitante": "Luton Town",
        "liga": "Premier League",
        "pos_local": 2,
        "pos_visit": 18,
        "forma_local_wins": 4,
        "forma_visit_wins": 1,
    }
    d.update(overrides)
    return d


def test_validar_tabla_ambas_posiciones_default_es_invalido():
    ok, motivo = tabla_pos.validar_tabla({})
    assert ok is False
    assert "default" in motivo.lower()


def test_validar_tabla_posicion_negativa_es_invalida():
    ok, motivo = tabla_pos.validar_tabla({"pos_local": 0, "pos_visit": 5})
    assert ok is False


def test_validar_tabla_ok_con_posiciones_reales():
    ok, motivo = tabla_pos.validar_tabla({"pos_local": 3, "pos_visit": 15})
    assert ok is True
    assert motivo == "ok"


def test_calcular_zona_limites_de_20_equipos():
    assert tabla_pos.calcular_zona(1) == "Champions"
    assert tabla_pos.calcular_zona(4) == "Champions"  # 4/20 = 0.20
    assert tabla_pos.calcular_zona(8) == "Europa"      # 8/20 = 0.40
    assert tabla_pos.calcular_zona(12) == "Mid-top"    # 12/20 = 0.60
    assert tabla_pos.calcular_zona(16) == "Mid-bottom"  # 16/20 = 0.80
    assert tabla_pos.calcular_zona(20) == "Descenso"


def test_calcular_momentum_combinaciones():
    assert tabla_pos.calcular_momentum(pos=3, forma_wins=0) == "bajando"       # pos_alta + sin_forma
    assert tabla_pos.calcular_momentum(pos=15, forma_wins=5) == "subiendo"     # pos_baja + en_forma
    assert tabla_pos.calcular_momentum(pos=3, forma_wins=5) == "estable_positivo"
    assert tabla_pos.calcular_momentum(pos=15, forma_wins=0) == "estable_negativo"
    assert tabla_pos.calcular_momentum(pos=8, forma_wins=2) == "estable"


def test_analizar_devuelve_shape_esperado():
    resultado = tabla_pos.analizar(_partido_base())
    assert resultado["ok"] is True
    assert resultado["fuente"] == "tabla_pos"
    assert resultado["favorito_tabla"] == "Local"
    assert resultado["zona_local"] == "Champions"
    assert resultado["zona_visit"] == "Descenso"
    assert resultado["brecha_pos"] == 16
    suma = resultado["prob_local"] + resultado["prob_empate"] + resultado["prob_visitante"]
    assert abs(suma - 1.0) < 0.001
    assert 10 <= resultado["confianza_score"] <= 95


def test_analizar_brecha_clara_bonifica_score():
    resultado = tabla_pos.analizar(_partido_base(pos_local=1, pos_visit=20))
    assert any("Brecha de tabla clara" in b for b in resultado["bonificaciones"])


def test_analizar_posiciones_iguales_da_empate_como_favorito_tabla():
    """Caso límite: misma posición (pos_local == pos_visit) -> favorito_tabla 'Empate',
    brecha 0, penaliza 'Posiciones muy similares' y 'Misma zona'."""
    resultado = tabla_pos.analizar(_partido_base(pos_local=10, pos_visit=10))
    assert resultado["favorito_tabla"] == "Empate"
    assert resultado["brecha_pos"] == 0
    assert any("Posiciones muy similares" in p for p in resultado["penalizaciones"])
    assert any("Misma zona" in p for p in resultado["penalizaciones"])


def test_analizar_posicion_cero_o_negativa_se_clampa_a_1():
    """pos_local/pos_visit se fuerzan a max(1, pos) — no debería quedar una posición <1."""
    resultado = tabla_pos.analizar(_partido_base(pos_local=-5, pos_visit=0))
    assert resultado["pos_local"] == 1
    assert resultado["pos_visit"] == 1


def test_analizar_ambos_en_descenso_cap_score_50():
    resultado = tabla_pos.analizar(
        _partido_base(pos_local=19, pos_visit=20, forma_local_wins=2, forma_visit_wins=2)
    )
    assert resultado["zona_local"] == "Descenso"
    assert resultado["zona_visit"] == "Descenso"
    assert resultado["confianza_score"] <= 50


def test_base_de_tabla_con_posiciones_iguales_es_la_frecuencia_historica_medida():
    """137.401 partidos reales: local 44.1%, empate 26.3%, visitante 29.6% (2026-10-06). Antes el
    punto de partida era 40/28/32, que sobrestimaba el empate."""
    from backend.api.services import tabla_pos
    pl, pe, pv = tabla_pos.calcular_probs_tabla(10, 10, "mitad", "mitad", "estable", "estable")
    assert abs(pl - 0.441) < 0.005 and abs(pe - 0.263) < 0.005 and abs(pv - 0.296) < 0.005
