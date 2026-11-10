"""test_ai_prompts.py — construir_prompt_analisis: mismo prompt que vivía en el nodo n8n
wfb-016, ahora en Python. Verifica presencia de secciones/reglas de formato y fallbacks
cuando faltan campos en el dict de entrada."""
from __future__ import annotations

from backend.api.services.ai_prompts import construir_prompt_analisis


def _partido_base(**overrides):
    d = {
        "partido": "River Plate vs Boca Juniors",
        "local": "River Plate",
        "visitante": "Boca Juniors",
        "liga": "Liga Profesional",
        "standings_info": "River 3ro, Boca 5to",
        "h2h_resumen": "River 4V 3E 3D en los últimos 10",
        "total_h2h": 10,
        "odds_info": "River @1.90 | Empate @3.30 | Boca @4.00",
        "forma_local_wins": 4,
        "goles_local_avg": 1.8,
        "forma_visit_wins": 2,
        "goles_visit_avg": 1.1,
        "resumen_estadistico": "Poisson: River 48% Empate 27% Boca 25%",
    }
    d.update(overrides)
    return d


def test_prompt_incluye_partido_liga_y_datos_reales():
    prompt = construir_prompt_analisis(_partido_base())
    assert "River Plate vs Boca Juniors" in prompt
    assert "Liga Profesional" in prompt
    assert "River 3ro, Boca 5to" in prompt
    assert "River 4V 3E 3D en los últimos 10" in prompt
    assert "River @1.90" in prompt


def test_prompt_contiene_las_10_reglas_estrictas():
    prompt = construir_prompt_analisis(_partido_base())
    assert "REGLAS ESTRICTAS" in prompt
    for i in range(1, 11):
        assert f"{i}." in prompt
    # Regla 4: formato exacto del pick, sin frases
    assert "⚖️ Balance y PICK: [SOLO nombre del equipo o la palabra Empate]" in prompt


def test_prompt_arma_partido_desde_local_visitante_si_falta_partido():
    d = _partido_base()
    del d["partido"]
    prompt = construir_prompt_analisis(d)
    assert "River Plate vs Boca Juniors" in prompt


def test_prompt_usa_defaults_cuando_dict_vacio():
    """Caso límite: dict vacío no debe lanzar — usa los defaults documentados en el f-string
    (Local/Visitante, 2/5 victorias, mensajes de 'no disponible')."""
    prompt = construir_prompt_analisis({})
    assert "Local vs Visitante" in prompt
    assert "Datos de tabla no disponibles para esta liga." in prompt
    assert "Sin historial directo disponible." in prompt
    assert "Sin odds disponibles — análisis estadístico puro." in prompt
    assert "Motor estadístico no disponible." in prompt
    assert "2/5 victorias recientes" in prompt


def test_prompt_termina_en_la_linea_de_pick():
    prompt = construir_prompt_analisis(_partido_base())
    assert prompt.rstrip().endswith("⚖️ Balance y PICK: [SOLO nombre del equipo o Empate]")


def test_prompt_da_rol_claro_de_analista_experto():
    """2026-09-10: el rol débil ('Eres un analista deportivo.') se reforzó con contexto real de
    la tarea (datos provistos, independencia del Poisson) — confirma que sigue ahí."""
    prompt = construir_prompt_analisis(_partido_base())
    assert "analista deportivo profesional" in prompt
    assert "modelo estadístico Poisson" in prompt


def test_prompt_pide_responder_solo_el_formato_exacto():
    """Instrucción agregada 2026-09-10 para reducir preámbulo/relleno antes del bloque que
    parsea `consenso_ia.py::extraer_pick_claude` — no debe mover la línea final del pick."""
    prompt = construir_prompt_analisis(_partido_base())
    assert "Responde ÚNICAMENTE con el bloque de abajo" in prompt
