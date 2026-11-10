"""test_analizadores.py — h2h, odds, tabla_pos, form_recent: casos límite y validaciones
(validar_* debe saltear el módulo con datos insuficientes, igual que hacía datos.py)."""
from __future__ import annotations

from backend.api.services import form_recent, h2h, odds, tabla_pos


# ─── h2h ──────────────────────────────────────────────────────────────────────

def test_h2h_muestra_insuficiente_se_saltea():
    ok, razon = h2h.validar_h2h({"h2h_disponible": True, "h2h_total": 2})
    assert ok is False
    assert "insuficiente" in razon


def test_h2h_dominancia_local_clara():
    d = {"h2h_local_wins": 8, "h2h_visit_wins": 1, "h2h_empates": 1, "h2h_total": 10,
         "local": "A", "visitante": "B"}
    r = h2h.analizar(d)
    assert r["pick"] == "Local"
    assert r["dominador"] == "Local"
    assert r["dominancia"] == 0.8


def test_h2h_sin_historial_usa_laplace_sin_prob_cero():
    """Suavizado de Laplace: 0 wins no debe dar probabilidad 0."""
    d = {"h2h_local_wins": 0, "h2h_visit_wins": 8, "h2h_empates": 2, "h2h_total": 10}
    r = h2h.analizar(d)
    assert r["prob_local"] > 0.0


# ─── odds ─────────────────────────────────────────────────────────────────────

def test_odds_invalidas_se_saltea():
    ok, razon = odds.validar_odds({"odds_disponibles": True, "odds_local": 0.5,
                                    "odds_empate": 3.0, "odds_visit": 3.0})
    assert ok is False


def test_odds_favorito_claro():
    d = {"odds_local": 1.3, "odds_empate": 5.0, "odds_visit": 8.0}
    r = odds.analizar(d)
    assert r["favorito"] == "Local"
    assert r["pick"] == "Local"
    assert r["value_bet"] is False  # odds.py nunca calcula value bet


def test_odds_overround_se_calcula_correctamente():
    # 1/2 + 1/3 + 1/6 = 0.5 + 0.3333 + 0.1667 = 1.0 exacto (overround=1.0, caso ideal)
    d = {"odds_local": 2.0, "odds_empate": 3.0, "odds_visit": 6.0}
    r = odds.analizar(d)
    assert abs(r["overround"] - 1.0) < 0.001


# ─── tabla_pos ────────────────────────────────────────────────────────────────

def test_tabla_sin_datos_reales_se_saltea():
    ok, razon = tabla_pos.validar_tabla({"pos_local": 10, "pos_visit": 10})
    assert ok is False
    assert "default" in razon


def test_tabla_brecha_clara_favorece_mejor_posicionado():
    d = {"pos_local": 1, "pos_visit": 18, "forma_local_wins": 3, "forma_visit_wins": 3}
    r = tabla_pos.analizar(d)
    assert r["favorito_tabla"] == "Local"
    assert r["zona_local"] == "Champions"
    assert r["zona_visit"] == "Descenso"
    assert r["pick"] == "Local"


# ─── form_recent ──────────────────────────────────────────────────────────────

def test_form_recent_sin_datos_usa_default_50_50():
    r = form_recent.analizar({})  # defaults: 2 wins cada uno
    assert r["forma_local_wins"] == 2
    assert r["forma_visit_wins"] == 2


def test_form_recent_racha_negativa_visitante_favorece_local():
    d = {"forma_local_wins": 3, "forma_visit_wins": 0}
    r = form_recent.analizar(d)
    assert r["pick"] == "Local"
    assert any("racha negativa" in b for b in r["bonificaciones"])
