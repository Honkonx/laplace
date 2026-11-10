"""test_consenso_ia.py — extracción del pick de Claude y consenso estadístico-vs-IA."""
from __future__ import annotations

from backend.api.services.consenso_ia import combinar_con_claude, extraer_pick_claude


def test_extraer_pick_claude_linea_exacta():
    texto = "🏆 River Plate vs Boca\n\n⚖️ Balance y PICK: River Plate"
    assert extraer_pick_claude(texto, "River Plate", "Boca") == "River Plate"


def test_extraer_pick_claude_empate():
    texto = "⚖️ Balance y PICK: Empate"
    assert extraer_pick_claude(texto, "River Plate", "Boca") == "Empate"


def test_extraer_pick_claude_sin_linea_usa_fallback_por_mencion():
    texto = "Análisis reñido, favorito Boca por la última mención"
    assert extraer_pick_claude(texto, "River Plate", "Boca") == "Boca"


def test_combinar_con_claude_coinciden_sube_score():
    resultado_motor = {"local": "River Plate", "visitante": "Boca",
                        "consenso": {"pick_final": "River Plate", "score_consenso": 60}}
    combinado = combinar_con_claude(resultado_motor, "⚖️ Balance y PICK: River Plate")
    assert combinado["nivel_ia"] == "COINCIDEN"
    assert combinado["pick_unificado"] == "River Plate"
    assert combinado["score_consolidado"] == 60


def test_combinar_con_claude_divergen_baja_score():
    resultado_motor = {"local": "River Plate", "visitante": "Boca",
                        "consenso": {"pick_final": "River Plate", "score_consenso": 60}}
    combinado = combinar_con_claude(resultado_motor, "⚖️ Balance y PICK: Boca")
    assert combinado["nivel_ia"] == "DIVERGEN"
    assert combinado["score_consolidado"] == 52


def test_ia_no_puede_elevar_score_por_encima_de_confianza_estadistica():
    resultado_motor = {"local": "River Plate", "visitante": "Boca", "consenso": {
        "pick_final": "River Plate", "score_consenso": 92, "confianza_final": "MEDIA",
    }}
    combinado = combinar_con_claude(resultado_motor, "PICK: River Plate")
    assert combinado["nivel_ia"] == "COINCIDEN"
    assert combinado["score_consolidado"] == 64
    assert combinado["confianza_final"] == "MEDIA"
