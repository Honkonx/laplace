"""test_consenso_ia_pick.py — regresión del pick de la IA con equipos de primer nombre común
(Real Madrid/Real Sociedad, Manchester United/City, Atlético Madrid/Mineiro, Al Nassr/Al Hilal)."""
from __future__ import annotations

import pytest

from backend.api.services.consenso_ia import _normalizar_pick, combinar_con_claude, extraer_pick_claude

PARES = [
    ("Real Madrid", "Real Sociedad"),
    ("Manchester United", "Manchester City"),
    ("Atlético Madrid", "Atlético Mineiro"),
    ("Al Nassr", "Al Hilal"),
]


@pytest.mark.parametrize("local,visitante", PARES)
def test_normalizar_pick_distingue_primer_nombre_comun(local, visitante):
    assert _normalizar_pick(local, local, visitante) == "local"
    assert _normalizar_pick(visitante, local, visitante) == "visitante"
    assert _normalizar_pick(local.upper(), local, visitante) == "local"
    assert _normalizar_pick(f"{visitante} FC", local, visitante) == "visitante"


@pytest.mark.parametrize("local,visitante", PARES)
def test_combinar_no_marca_divergen_sin_motivo(local, visitante):
    motor = {"local": local, "visitante": visitante, "consenso": {"pick_final": visitante, "score_consenso": 60}}
    combinado = combinar_con_claude(motor, f"⚖️ Balance y PICK: {visitante}")
    assert combinado["nivel_ia"] == "COINCIDEN"
    assert combinado["pick_claude"] == visitante


def test_pick_ambiguo_o_sin_equipo_es_indeterminado():
    assert _normalizar_pick("Real", "Real Madrid", "Real Sociedad") == "indeterminado"
    assert _normalizar_pick("Manchester", "Manchester United", "Manchester City") == "indeterminado"
    assert _normalizar_pick("Barcelona", "Real Madrid", "Real Sociedad") == "indeterminado"
    assert _normalizar_pick("Real Madrid o Real Sociedad", "Real Madrid", "Real Sociedad") == "indeterminado"
    motor = {"local": "Real Madrid", "visitante": "Real Sociedad",
             "consenso": {"pick_final": "Real Madrid", "score_consenso": 60}}
    assert combinar_con_claude(motor, "⚖️ Balance y PICK: Real")["nivel_ia"] == "SOLO_ESTADISTICO"


def test_fragmento_unico_identifica_equipo():
    assert _normalizar_pick("Sociedad", "Real Madrid", "Real Sociedad") == "visitante"
    assert _normalizar_pick("Mineiro", "Atlético Madrid", "Atlético Mineiro") == "visitante"


def test_acentos_ruido_y_categorias():
    assert _normalizar_pick("atletico madrid", "Atlético Madrid", "Atlético Mineiro") == "local"
    assert _normalizar_pick("ATLÉTICO MINEIRO", "Atlético Madrid", "Atlético Mineiro") == "visitante"
    assert _normalizar_pick("Barcelona FC", "FC Barcelona", "Girona") == "local"
    assert _normalizar_pick("Empate", "A", "B") == "empate"
    assert _normalizar_pick("Local", "A", "B") == "local"
    assert _normalizar_pick("Visitante", "A", "B") == "visitante"
    assert _normalizar_pick("", "A", "B") == "indeterminado"
    assert _normalizar_pick(None, "A", "B") == "indeterminado"


def test_nombre_contenido_en_otro_gana_el_mas_especifico():
    assert _normalizar_pick("Real Madrid Castilla", "Real Madrid", "Real Madrid Castilla") == "visitante"
    assert _normalizar_pick("Real Madrid", "Real Madrid", "Real Madrid Castilla") == "local"


def test_extraer_usa_la_ultima_linea_de_balance():
    texto = "⚖️ Balance y PICK: Real Madrid\nmás texto\n⚖️ Balance y PICK: Real Sociedad"
    assert extraer_pick_claude(texto, "Real Madrid", "Real Sociedad") == "Real Sociedad"


def test_fallback_por_mencion_exige_nombre_completo():
    texto = "Se impone Real Sociedad aunque Real Madrid llega mejor de forma"
    assert extraer_pick_claude(texto, "Real Madrid", "Real Sociedad") == "Real Madrid"
    assert extraer_pick_claude("Gana Real", "Real Madrid", "Real Sociedad") == "Indeterminado"
    assert extraer_pick_claude("Mejor el atletico mineiro", "Atlético Madrid", "Atlético Mineiro") == "Atlético Mineiro"


def test_texto_ia_antiguo_con_linea_value_sigue_parseando():
    texto = "🥅 BTTS: Sí\n💎 Value: River @1.9\n\n⚖️ Balance y PICK: River Plate"
    assert extraer_pick_claude(texto, "River Plate", "Boca Juniors") == "River Plate"
