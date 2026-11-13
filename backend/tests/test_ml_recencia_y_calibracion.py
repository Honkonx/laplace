"""MP-3 (peso por recencia al entrenar) y MD-6 (temperatura por liga): el entrenamiento sin recencia no cambia y con ella da más peso a lo reciente; las piezas de la calibración recuperan una temperatura conocida."""
from __future__ import annotations

import random

import pytest

from backend.api.ml.laplace import entrenamiento, simulacion
from backend.scripts import medir_calibracion_por_liga as cal


def _prob(pesos, x):
    return entrenamiento.probs_lineal(pesos, x)


def test_sin_pesos_el_ajuste_es_el_de_siempre_y_con_pesos_iguales_tambien():
    X = [[1.0, i / 10] for i in range(40)]
    y = ["HDA"[i % 3] for i in range(40)]
    base = entrenamiento.ajustar_logistica(X, y)
    assert entrenamiento.ajustar_logistica(X, y, pesos_muestra=[1.0] * 40) == base
    escalados = entrenamiento.ajustar_logistica(X, y, pesos_muestra=[5.0] * 40)
    assert max(abs(a - b) for fa, fb in zip(escalados, base, strict=True) for a, b in zip(fa, fb, strict=True)) < 1e-9      # pesos iguales, de cualquier escala, no cambian nada


def test_los_pesos_por_muestra_inclinan_el_ajuste_hacia_lo_reciente():
    X = [[1.0, 1.0]] * 100
    y = ["H"] * 50 + ["A"] * 50                                  # lo antiguo gana el local; lo reciente, el visitante
    parejo = entrenamiento.ajustar_logistica(X, y)
    reciente = entrenamiento.ajustar_logistica(X, y, pesos_muestra=[0.5 ** ((99 - i) / 15) for i in range(100)])
    assert abs(_prob(parejo, [1.0, 1.0])[0] - _prob(parejo, [1.0, 1.0])[2]) < 0.05
    p = _prob(reciente, [1.0, 1.0])
    assert p[2] > p[0] + 0.3


def _por_liga():
    a = simulacion.simular(11, n_equipos=10, temporadas=3)["partidos"]
    for p in a:
        p["liga"] = "AAA"
    return {"AAA": a}


def test_entrenar_con_recencia_cambia_los_pesos_y_sin_ella_es_reproducible():
    por = _por_liga()
    corte = max(p["dia"] for p in por["AAA"]) + 1
    g3 = entrenamiento.entrenar_jerarquico(por, corte, con_goles=False)
    assert entrenamiento.entrenar_jerarquico(por, corte, con_goles=False)["universal"] == g3["universal"]
    con = entrenamiento.entrenar_jerarquico(por, corte, hiper={**entrenamiento.HIPER_DEFECTO, "recencia_dias": 180}, con_goles=False)
    assert con["universal"] != g3["universal"] and con["hiper"]["recencia_dias"] == 180
    assert "recencia_dias" not in g3["hiper"]                                          # el modelo servido no la usa


def test_los_dias_de_las_filas_entrenables_van_en_el_mismo_orden_que_las_filas():
    ps = _por_liga()["AAA"]
    dias: list[int] = []
    filas, _ = entrenamiento._filas_entrenables(ps, None, None, dias)
    assert len(dias) == len(filas) and dias == sorted(dias)


# ---------------------------------------------------------------- MD-6
def test_la_temperatura_uno_no_cambia_nada_y_las_demas_aplanan_o_afilan():
    p = (0.5, 0.3, 0.2)
    assert cal.aplicar_temperatura(p, 1.0) == pytest.approx(p)
    plano, afilado = cal.aplicar_temperatura(p, 2.0), cal.aplicar_temperatura(p, 0.5)
    assert max(plano) < 0.5 < max(afilado) and sum(plano) == pytest.approx(1.0) and sum(afilado) == pytest.approx(1.0)


def test_la_temperatura_se_recupera_de_pronosticos_demasiado_seguros():
    rng = random.Random(5)
    verdad = (0.40, 0.30, 0.30)
    filas = []
    for _ in range(4000):
        resultado = rng.choices("HDA", weights=verdad)[0]
        filas.append((cal.aplicar_temperatura(verdad, 0.5), resultado))                  # el modelo afila de más (T = 0,5): hay que aplanar con T ≈ 2
    t = cal.ajustar_temperatura(filas)
    assert 1.7 < t < 2.3
    bien = [(verdad, rng.choices("HDA", weights=verdad)[0]) for _ in range(4000)]
    assert 0.85 < cal.ajustar_temperatura(bien) < 1.15                                   # ya calibrado: T ≈ 1


def test_comparar_devuelve_none_con_pocas_filas():
    assert cal._comparar([{"p": (0.4, 0.3, 0.3), "x": (0.4, 0.3, 0.3), "r": "H", "dia": 1}] * 5, "p", "x") is None
