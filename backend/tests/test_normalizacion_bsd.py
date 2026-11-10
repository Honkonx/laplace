"""test_normalizacion_bsd.py — regresión del bug real encontrado en producción (2026-09-05):
BSD API (bzzoiro.com) no es consistente devolviendo `home_team`/`away_team` en `/events/` —
normalmente `{"name": "..."}`, pero en vivo devolvió un string plano y tumbó CUALQUIER análisis
que cayera al fallback BSD de H2H (`AttributeError: 'str' object has no attribute 'get'`,
confirmado en el log real del servidor). `nombre_equipo_bsd()` es el fix — debe soportar ambos
shapes sin reventar.
"""
from __future__ import annotations

from backend.api.services.normalizacion import nombre_equipo_bsd


def test_shape_dict_normal():
    assert nombre_equipo_bsd({"name": "River Plate"}) == "River Plate"


def test_shape_string_plano_no_revienta():
    assert nombre_equipo_bsd("River Plate") == "River Plate"


def test_shape_none():
    assert nombre_equipo_bsd(None) == ""


def test_shape_dict_sin_name():
    assert nombre_equipo_bsd({}) == ""


def test_shape_inesperado_no_revienta():
    assert nombre_equipo_bsd(12345) == ""
