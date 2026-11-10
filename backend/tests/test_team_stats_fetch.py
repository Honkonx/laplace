"""test_team_stats_fetch.py — extracción de goles promedio + caso sin datos suficientes."""
from __future__ import annotations

from backend.api.services import team_stats_fetch


def test_extraer_goles_promedio_sin_datos():
    assert team_stats_fetch.extraer_goles_promedio(None) == (None, None)


def test_extraer_goles_promedio_con_datos():
    stats = {"goals": {"for": {"average": {"total": "2.1"}}, "against": {"average": {"total": "0.8"}}}}
    a_favor, en_contra = team_stats_fetch.extraer_goles_promedio(stats)
    assert a_favor == 2.1
    assert en_contra == 0.8
