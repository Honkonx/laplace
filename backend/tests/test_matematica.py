"""test_matematica.py — services/_matematica.py: helpers matemáticos compartidos extraídos de
la duplicación real en pronostico.py/consenso.py/h2h.py/form_recent.py/tabla_pos.py/odds.py
(auditoría 2026-09-09). Cubre los casos de borde que motivaron el diseño de cada función —
en particular el guard finito=True que preserva el comportamiento propio que tenía odds.py."""
from __future__ import annotations

import math

from backend.api.services import _matematica as m


def test_safe_float_default_si_none():
    assert m.safe_float(None, 1.5) == 1.5


def test_safe_float_default_si_no_convertible():
    assert m.safe_float("no-es-numero", 2.0) == 2.0


def test_safe_float_convierte_valor_valido():
    assert m.safe_float("3.5") == 3.5


def test_safe_float_permite_nan_por_default():
    """Comportamiento histórico de pronostico.py/consenso.py: sin finito=True, NaN pasa tal
    cual (no hay guard) — solo odds.py necesitaba descartarlo."""
    resultado = m.safe_float(float("nan"))
    assert math.isnan(resultado)


def test_safe_float_finito_descarta_nan_e_inf():
    assert m.safe_float(float("nan"), 0.0, finito=True) == 0.0
    assert m.safe_float(float("inf"), 0.0, finito=True) == 0.0
    assert m.safe_float(float("-inf"), 0.0, finito=True) == 0.0


def test_safe_int_default_si_no_convertible():
    assert m.safe_int("abc", 7) == 7
    assert m.safe_int(None, 3) == 3
    assert m.safe_int("5") == 5


def test_safe_bool_variantes():
    assert m.safe_bool(True) is True
    assert m.safe_bool("true") is True
    assert m.safe_bool("1") is True
    assert m.safe_bool("no") is False
    assert m.safe_bool(0) is False
    assert m.safe_bool(2) is True
    assert m.safe_bool(None, default=True) is True


def test_clamp():
    assert m.clamp(5, 0, 10) == 5
    assert m.clamp(-5, 0, 10) == 0
    assert m.clamp(15, 0, 10) == 10


def test_clamp_prob_minima_no_toca_valores_por_encima_del_minimo():
    assert m.clamp_prob_minima(0.5, 0.3, 0.2) == (0.5, 0.3, 0.2)


def test_clamp_prob_minima_sube_valores_bajo_el_minimo():
    assert m.clamp_prob_minima(-0.1, 0.5, 0.6, min_prob=0.05) == (0.05, 0.5, 0.6)


def test_corregir_redondeo_suma_uno_exacto():
    prob_local, prob_empate, prob_visit = m.corregir_redondeo(0.33333, 0.33333, 0.33334)
    assert prob_local + prob_empate + prob_visit == 1.0


def test_corregir_redondeo_corrige_remanente_sobre_local():
    """El remanente de redondeo siempre se suma a la componente local (primer argumento) —
    documentado y verificado con un caso donde el redondeo deja un remanente no nulo."""
    prob_local, prob_empate, prob_visit = m.corregir_redondeo(0.1, 0.2, 0.71234)
    assert round(prob_empate, 4) == 0.2
    assert round(prob_visit, 4) == 0.7123
    assert prob_local + prob_empate + prob_visit == 1.0


def test_normalizar_probabilidades_divide_por_total_y_corrige():
    """1/3 no es exacto en 4 decimales (0.3333) — el remanente de redondeo (0.0001) se suma a
    la componente local, que queda en 0.3334 mientras empate/visitante quedan en 0.3333."""
    prob_local, prob_empate, prob_visit = m.normalizar_probabilidades(1.0, 1.0, 1.0, 3.0)
    assert prob_local + prob_empate + prob_visit == 1.0
    assert prob_local == 0.3334
    assert prob_empate == prob_visit == 0.3333


def test_normalizar_probabilidades_con_total_distinto_de_la_suma():
    """Caso real de consenso.py: `total` es un acumulador de peso distinto de a+b+c."""
    prob_local, prob_empate, prob_visit = m.normalizar_probabilidades(0.4, 0.2, 0.2, 0.8)
    assert prob_local + prob_empate + prob_visit == 1.0
