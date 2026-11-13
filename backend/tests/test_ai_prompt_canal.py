"""test_ai_prompt_canal.py — prompt del canal (WF-D) y parseo de la respuesta de Claude."""
from __future__ import annotations

from backend.api.services.ai_prompt_canal import (
    construir_prompt_canal,
    parsear_bloque,
    parsear_respuesta_canal,
)


def _candidato(**overrides) -> dict:
    base = {
        "local": "River", "visitante": "Boca", "liga": "Liga Profesional", "hora_chile": "20:00",
        "stats_local_str": "Goles/P: 1.8", "stats_visit_str": "Goles/P: 1.2",
        "h2h_resumen": "River 2-1 Boca (jun-2025)",
        "estadistico": {"pick": "Local", "confianza_score": 70},
        "estadistico_form": {"pick": "Local", "confianza_score": 60},
        "odds_local": 1.8, "odds_empate": 3.2, "odds_visit": 4.0,
        "pick_externo": "River Plate",
    }
    base.update(overrides)
    return base


def test_construir_prompt_canal_con_3_partidos_incluye_datos_reales():
    prompt = construir_prompt_canal([_candidato(), _candidato(local="Colo Colo", visitante="U de Chile"),
                                      _candidato(local="Nacional", visitante="Peñarol")])
    assert "River vs Boca" in prompt
    assert "Colo Colo vs U de Chile" in prompt
    assert "Consenso del sistema: N/D" in prompt  # sin consenso en el candidato de prueba
    assert "Poisson pick" not in prompt and "Forma pick" not in prompt  # MB-03: módulos que pesan 0 o casi 0
    assert prompt.count("PARTIDO ") == 3


def test_construir_prompt_canal_rellena_partidos_faltantes():
    prompt = construir_prompt_canal([_candidato()])
    assert "PARTIDO 2:\nEquipos: Sin partido" in prompt
    assert "PARTIDO 3:\nEquipos: Sin partido" in prompt


def test_construir_prompt_canal_sin_odds():
    c = _candidato(odds_local=None)
    prompt = construir_prompt_canal([c])
    assert "Odds: Sin odds" in prompt


def test_parsear_bloque_extrae_pick_razon_confianza():
    bloque = "PICK: River Plate\nRAZÓN: Mejor forma reciente y ventaja de local\nCONFIANZA: 72"
    resultado = parsear_bloque(bloque)
    assert resultado == {"pick": "River Plate", "razon": "Mejor forma reciente y ventaja de local", "confianza": 72}


def test_parsear_bloque_sin_match_usa_defaults():
    resultado = parsear_bloque("texto sin formato")
    assert resultado["pick"] == "Sin datos"
    assert resultado["confianza"] is None


def test_parsear_respuesta_canal_divide_por_guiones():
    texto = "PICK: A\nRAZÓN: x\nCONFIANZA: 50\n---\nPICK: B\nRAZÓN: y\nCONFIANZA: 60\n---\nPICK: Empate\nRAZÓN: z\nCONFIANZA: 40"
    bloques = parsear_respuesta_canal(texto)
    assert len(bloques) == 3
    assert [b["pick"] for b in bloques] == ["A", "B", "Empate"]


def test_el_prompt_del_canal_no_pide_confianza_propia_ni_obliga_a_dar_pick():
    prompt = construir_prompt_canal([_candidato()])
    assert "CONFIANZA:" not in prompt and "certeza real" not in prompt and "SIEMPRE da un pick" not in prompt
    assert "Sin datos" in prompt and "la confianza la calcula el sistema" in prompt


def test_el_prompt_del_canal_incluye_el_consenso_del_sistema():
    c = _candidato(resultado_motor={"consenso": {"pick_final": "Local", "prob_ponderada": {"local": 0.62, "empate": 0.24, "visitante": 0.14}}})
    prompt = construir_prompt_canal([c])
    assert "Consenso del sistema: Local (62%)" in prompt
