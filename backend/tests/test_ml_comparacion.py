"""Arnés de comparación con significancia (MM-00): detecta una diferencia real, no inventa una inexistente, y el bootstrap en bloques ensancha el intervalo cuando hay correlación."""
import random

import pytest

from backend.api.ml import comparacion


def _perdidas(n, media_b, sd=0.08, semilla=1):
    rng = random.Random(semilla)
    a = [1.0 + rng.gauss(0, sd) for _ in range(n)]
    b = [x - media_b + rng.gauss(0, sd * 0.5) for x in a]
    return a, b


def test_detecta_una_mejora_real_y_la_puerta_la_acepta():
    a, b = _perdidas(5000, 0.003)
    r = comparacion.comparar_perdidas(a, b, bloques=[i // 50 for i in range(5000)])
    assert 0.002 < r["diferencia_media"] < 0.004 and r["z"] > 3 and r["ic95"][0] > 0 and r["p_dm_hln"] < 0.01


def test_sin_diferencia_real_no_da_falsos_positivos_en_200_repeticiones():
    falsos = 0
    for semilla in range(200):
        a, b = _perdidas(1500, 0.0, semilla=semilla)
        r = comparacion.comparar_perdidas(a, b, n_boot=10, semilla=semilla)
        falsos += abs(r["z"]) > 3
    assert falsos / 200 < 0.05


def test_la_diferencia_negativa_se_reporta_como_empeora():
    a, b = _perdidas(3000, -0.004)
    r = comparacion.comparar_perdidas(a, b)
    assert r["diferencia_media"] < 0 and r["z"] < -3
    assert "empeora" in comparacion.veredicto({**r, "acepta": False}) and "NO cumple" in comparacion.veredicto({**r, "acepta": False})


def test_el_bootstrap_en_bloques_da_un_intervalo_mas_ancho_si_hay_correlacion_dentro_del_bloque():
    rng = random.Random(3)
    bloques, a, b = [], [], []
    for k in range(60):
        efecto = rng.gauss(0, 0.02)  # todos los partidos de la semana comparten un efecto
        for _ in range(25):
            bloques.append(k)
            a.append(1.0)
            b.append(1.0 - efecto + rng.gauss(0, 0.01))
    con = comparacion.comparar_perdidas(a, b, bloques=bloques, n_boot=500)
    sin = comparacion.comparar_perdidas(a, b, bloques=None, n_boot=500)
    assert (con["ic95"][1] - con["ic95"][0]) > 2 * (sin["ic95"][1] - sin["ic95"][0])


def test_es_reproducible_con_la_misma_semilla():
    a, b = _perdidas(800, 0.002)
    assert comparacion.comparar_perdidas(a, b, semilla=5) == comparacion.comparar_perdidas(a, b, semilla=5)


def test_comparar_predicciones_exige_el_mismo_conjunto_y_aplica_la_puerta():
    mejor = [((0.6, 0.2, 0.2), "H")] * 40 + [((0.2, 0.2, 0.6), "A")] * 40
    peor = [((0.4, 0.3, 0.3), "H")] * 40 + [((0.3, 0.3, 0.4), "A")] * 40
    r = comparacion.comparar_predicciones(peor, mejor, bloques=[i % 8 for i in range(80)], n_boot=200)
    assert r["diferencia_media"] > 0 and "perdida_a" in r
    with pytest.raises(ValueError):
        comparacion.comparar_predicciones(peor, mejor[:-1])
    with pytest.raises(ValueError):
        comparacion.comparar_predicciones(peor, [(p, "D") for p, _ in mejor])
    with pytest.raises(ValueError):
        comparacion.comparar_perdidas([1.0, 2.0], [1.0, 2.0])


def test_comparaciones_pareadas_del_arnes_cubren_base_dixon_coles_y_mercado():
    from backend.api.ml.laplace import entrenamiento

    rng = random.Random(4)
    pareados = []
    for i in range(400):
        r = rng.choice("HDA")
        buena = (0.6, 0.2, 0.2) if r == "H" else (0.2, 0.2, 0.6) if r == "A" else (0.3, 0.4, 0.3)
        pareados.append((i // 20, buena, buena, (0.4, 0.3, 0.3), (0.45, 0.3, 0.25) if i % 2 else None, (0.5, 0.25, 0.25) if i % 3 == 0 else None, r))
    c = entrenamiento.comparaciones_pareadas(pareados)
    assert set(c) == {"modelo_vs_tasa_base", "modelo_vs_dixon_coles", "modelo_vs_mercado", "modelo_vs_universal"}
    assert c["modelo_vs_tasa_base"]["n"] == 400 and c["modelo_vs_dixon_coles"]["n"] == 200 and c["modelo_vs_mercado"]["n"] == 134
    assert c["modelo_vs_tasa_base"]["diferencia_media"] > 0 and c["modelo_vs_universal"]["diferencia_media"] == 0
    assert entrenamiento.comparaciones_pareadas(pareados[:10]) == {}
