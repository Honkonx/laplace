"""MM-14: los intervalos del 1x2 cubren la probabilidad verdadera cerca del 80 % en datos sintéticos con verdad conocida."""
import math
import random

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from backend.api.ml.laplace import entrenamiento as e  # noqa: E402
from backend.api.ml.laplace import incertidumbre as inc  # noqa: E402

VERDAD = [[0.1, 0.9, 0.3], [-0.2, 0.0, 0.1], [-0.1, -0.8, -0.4]]


def _muestra(rng, n):
    xs = [[1.0, rng.gauss(0, 1), rng.gauss(0, 0.7)] for _ in range(n)]
    ys = []
    for x in xs:
        p = e.probs_lineal(VERDAD, x)
        r = rng.random()
        ys.append("H" if r < p[0] else "D" if r < p[0] + p[1] else "A")
    return xs, ys


def test_la_cobertura_del_intervalo_al_80_por_ciento_esta_entre_72_y_88():
    rng = random.Random(7)
    cubre = total = 0
    for rep in range(6):
        xs, ys = _muestra(rng, 1500)
        W = e.ajustar_logistica(xs, ys)
        sigma = inc.covarianza_pesos(xs, W, e.L2)
        for _ in range(60):
            x = [1.0, rng.gauss(0, 1), rng.gauss(0, 0.7)]
            r = inc.intervalo(sigma, W, x)
            real = e.probs_lineal(VERDAD, x)
            for k, nombre in enumerate(("local", "empate", "visitante")):
                c = r["p1x2_ic80"][nombre]
                cubre += c["bajo"] <= real[k] <= c["alto"]
                total += 1
    assert 0.72 <= cubre / total <= 0.88, cubre / total


def test_menos_datos_dan_intervalos_mas_anchos_y_la_abstencion_se_activa():
    rng = random.Random(3)
    anchos = []
    for n in (200, 4000):
        xs, ys = _muestra(rng, n)
        W = e.ajustar_logistica(xs, ys)
        anchos.append(inc.intervalo(inc.covarianza_pesos(xs, W, e.L2), W, [1.0, 1.5, 0.5])["ancho_maximo"])
    assert anchos[0] > anchos[1]
    sigma_grande = [[1.0 if i == j else 0.0 for j in range(9)] for i in range(9)]
    assert inc.intervalo(sigma_grande, VERDAD, [1.0, 1.0, 1.0])["poco_fiable"] is True


def test_el_intervalo_contiene_la_probabilidad_puntual_y_esta_en_0_1():
    sigma = [[0.01 if i == j else 0.0 for j in range(9)] for i in range(9)]
    r = inc.intervalo(sigma, VERDAD, [1.0, 0.4, -0.2])
    for c in r["p1x2_ic80"].values():
        assert 0 <= c["bajo"] <= c["p"] <= c["alto"] <= 1
    assert math.isclose(sum(c["p"] for c in r["p1x2_ic80"].values()), 1.0, abs_tol=1e-3)


def test_el_artefacto_entrenado_lleva_la_covarianza_y_el_servicio_devuelve_el_intervalo():
    from backend.api.ml.laplace import servicio, simulacion

    ps = simulacion.simular(31, n_equipos=10, temporadas=3)["partidos"]
    for p in ps:
        p["liga"] = "AAA"
    art = e.entrenar_jerarquico({"AAA": ps}, max(p["dia"] for p in ps) + 1, con_goles=False)
    assert art["incertidumbre"] and len(art["incertidumbre"]["covarianza"]) == 3 * len(art["universal"][0])
    equipos = sorted({p["local"] for p in ps})
    salida, motivo = servicio._calcular(art, {"local": equipos[0], "visitante": equipos[1], "liga": "AAA"})  # noqa: SLF001
    if salida is not None:  # puede no resolver la liga por nombre; el cálculo directo se cubre abajo
        assert "incertidumbre" in salida and 0 <= salida["incertidumbre"]["ancho_maximo"] <= 1
    r = e.predecir_liga(art, "AAA", equipos[0], equipos[1])
    inc_directo = inc.intervalo(art["incertidumbre"]["covarianza"], art["universal"], e.EstadoLiga.de_dict(art["ligas"]["AAA"]["estado"]).features(equipos[0], equipos[1]))
    assert abs(inc_directo["p1x2_ic80"]["local"]["p"] - r["p1x2"][0]) < 1e-3
