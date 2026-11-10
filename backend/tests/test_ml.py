"""test_ml.py — métricas, cuotas sin margen y Dixon-Coles (`backend/api/ml/`).

El ajuste necesita numpy/scipy (opcionales, ver `backend/requirements-ml.txt`): esos tests se
saltan si no están instalados. La predicción y las métricas son Python puro y siempre corren.
"""
from __future__ import annotations

import math
import random
import statistics

import pytest

from backend.api.ml import dixon_coles as dc
from backend.api.ml import mercado, metricas


def test_rps_perfecto_y_peor_caso():
    assert metricas.rps((1.0, 0.0, 0.0), "H") == 0.0
    assert metricas.rps((0.0, 0.0, 1.0), "H") == pytest.approx(1.0)


def test_rps_penaliza_menos_fallar_por_categoria_vecina():
    # Predecir Empate cuando ganó el visitante duele menos que predecir Local.
    assert metricas.rps((0.0, 1.0, 0.0), "A") < metricas.rps((1.0, 0.0, 0.0), "A")


def test_log_loss_no_explota_con_probabilidad_cero():
    assert math.isfinite(metricas.log_loss((0.0, 0.5, 0.5), "H"))


def test_resumen_vacio_y_con_datos():
    assert metricas.resumen([])["n"] == 0
    r = metricas.resumen([((0.6, 0.2, 0.2), "H"), ((0.2, 0.2, 0.6), "H")])
    assert r["n"] == 2 and r["accuracy"] == 0.5


@pytest.mark.parametrize("metodo", [mercado.quitar_margen_proporcional, mercado.quitar_margen_shin])
def test_quitar_margen_suma_uno_y_conserva_orden(metodo):
    p = metodo(1.90, 3.60, 4.20)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1] > p[2]


def test_shin_reparte_mas_margen_sobre_el_menos_probable():
    prop = mercado.quitar_margen_proporcional(1.5, 4.5, 7.0)
    shin = mercado.quitar_margen_shin(1.5, 4.5, 7.0)
    assert shin[2] < prop[2]  # sesgo favorito-longshot: el longshot vale menos que en proporcional


def test_cuotas_validas():
    assert mercado.cuotas_validas(1.5, 3.0, 5.0)
    assert not mercado.cuotas_validas(1.5, None, 5.0)
    assert not mercado.cuotas_validas(1.0, 3.0, 5.0)
    assert not mercado.cuotas_validas(1.5, float("nan"), 5.0)


def test_probabilidades_suman_uno_y_local_fuerte_favorece_al_local():
    p = dc.probabilidades_desde_lambdas(2.2, 0.8, dc.RHO_POR_DEFECTO)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1] > p[2]


def test_equipo_desconocido_cuenta_como_promedio():
    modelo = dc.ModeloLiga(mu=0.1, gamma=0.25, ataque={"A": 0.3}, defensa={"A": 0.1})
    lam_h, lam_a, conocidos = dc.lambdas(modelo, "A", "Desconocido")
    assert conocidos is False and lam_h > lam_a


def test_serializacion_ida_y_vuelta():
    modelo = dc.ModeloLiga(mu=0.1, gamma=0.25, ataque={"A": 0.3}, defensa={"A": -0.1}, n_partidos=50)
    assert dc.ModeloLiga.de_dict(modelo.a_dict()).ataque == {"A": 0.3}


def _poisson(lam: float, rng: random.Random) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def test_ajuste_recupera_fuerzas_conocidas_y_no_usa_el_futuro():
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    rng = random.Random(1)
    equipos = [f"E{i}" for i in range(12)]
    ataque = {e: rng.gauss(0, 0.25) for e in equipos}
    defensa = {e: rng.gauss(0, 0.25) for e in equipos}
    mu, gamma = 0.15, 0.28
    partidos = []
    for dia in range(700):
        for _ in range(6):
            h, a = rng.sample(equipos, 2)
            partidos.append((
                dia, h, a,
                _poisson(math.exp(mu + gamma + ataque[h] - defensa[a]), rng),
                _poisson(math.exp(mu + ataque[a] - defensa[h]), rng),
            ))

    modelo = dc.ajustar(partidos, 701, xi=0.0, ridge=0.5)

    assert modelo is not None
    assert modelo.gamma == pytest.approx(gamma, abs=0.08)
    assert statistics.correlation([ataque[e] for e in equipos], [modelo.ataque[e] for e in equipos]) > 0.9
    assert statistics.correlation([defensa[e] for e in equipos], [modelo.defensa[e] for e in equipos]) > 0.9
    # Nunca mira el futuro: con fecha de corte 10 hay muy pocos partidos previos y no ajusta.
    assert dc.ajustar(partidos, 3) is None
    assert dc.ajustar(partidos, 400).fecha_corte < 400
