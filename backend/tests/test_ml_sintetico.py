"""Pruebas de ml/sintetico.py: determinismo, rangos, calendario, cuotas y tabla sin fuga. No usa red ni BD."""
from __future__ import annotations

import math
import random
from datetime import date

import pytest

from backend.api.ml import sintetico
from backend.api.ml.sintetico import (
    NOMBRES,
    LigaSintetica,
    _poisson,
    calendario,
    cuotas_mercado,
    generar_liga,
    simular_temporada,
    tabla_hasta,
)

INICIO = date(2025, 8, 1)


def test_generar_liga_es_determinista_y_distinta_por_semilla():
    a, b, c = generar_liga(1), generar_liga(1), generar_liga(2)
    assert a == b
    assert a.ataque != c.ataque and a.defensa != c.defensa


def test_generar_liga_parametros_y_nombres():
    liga = generar_liga(3, n_equipos=4, codigo="XX", nombre="N", mu=0.1, gamma=0.2)
    assert (liga.codigo, liga.nombre, liga.mu, liga.gamma) == ("XX", "N", 0.1, 0.2)
    assert len(liga.equipos) == 4 == len(liga.ataque) == len(liga.defensa)
    assert set(liga.ataque) == set(liga.equipos) == set(liga.defensa)


def test_generar_liga_mas_equipos_que_nombres_no_repite():
    n = len(NOMBRES) + 3
    liga = generar_liga(1, n_equipos=n)
    assert len(set(liga.equipos)) == n
    assert liga.equipos[len(NOMBRES)].endswith(" B")
    assert not liga.equipos[0].endswith(" B")


def test_lambdas_formula_y_ventaja_local():
    liga = LigaSintetica("Z", "Z", mu=0.1, gamma=0.3, ataque={"a": 0.2, "b": -0.1}, defensa={"a": 0.05, "b": 0.15},
                         equipos=["a", "b"])
    lam_h, lam_a = liga.lambdas("a", "b")
    assert lam_h == pytest.approx(math.exp(0.1 + 0.3 + 0.2 - 0.15))
    assert lam_a == pytest.approx(math.exp(0.1 + -0.1 - 0.05))


def test_probs_verdaderas_suman_uno_y_en_rango():
    liga = generar_liga(5)
    for local, visitante in calendario(liga, INICIO)[0]:
        probs = liga.probs_verdaderas(local, visitante)
        assert len(probs) == 3
        assert all(0.0 <= p <= 1.0 for p in probs)
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)


def test_probs_verdaderas_ventaja_local_con_equipos_iguales():
    liga = LigaSintetica("Z", "Z", mu=0.15, gamma=0.28, ataque={"a": 0.0, "b": 0.0}, defensa={"a": 0.0, "b": 0.0},
                         equipos=["a", "b"])
    h, _, a = liga.probs_verdaderas("a", "b")
    assert h > a


def test_poisson_determinista_y_media_razonable():
    r1, r2 = random.Random(9), random.Random(9)
    assert [_poisson(1.5, r1) for _ in range(20)] == [_poisson(1.5, r2) for _ in range(20)]
    rng = random.Random(1)
    muestra = [_poisson(2.0, rng) for _ in range(4000)]
    assert all(isinstance(x, int) and x >= 0 for x in muestra)
    assert sum(muestra) / len(muestra) == pytest.approx(2.0, abs=0.15)


@pytest.mark.parametrize("n", [4, 5, 16])
def test_calendario_todos_contra_todos_ida_y_vuelta(n):
    liga = generar_liga(1, n_equipos=n)
    rondas = calendario(liga, INICIO)
    pares_por_ronda = n // 2
    n_ronda = n if n % 2 else n - 1
    assert len(rondas) == 2 * n_ronda
    partidos = [p for r in rondas for p in r]
    assert len(partidos) == n * (n - 1)
    assert len(set(partidos)) == len(partidos)  # cada (local, visitante) una sola vez
    assert all(local != visitante for local, visitante in partidos)
    for ronda in rondas:
        jugando = [e for p in ronda for e in p]
        assert len(jugando) == len(set(jugando))  # nadie juega dos veces en una ronda
        assert len(ronda) == pares_por_ronda


def test_calendario_solo_ida():
    liga = generar_liga(1, n_equipos=6)
    rondas = calendario(liga, INICIO, ida_y_vuelta=False)
    assert len(rondas) == 5
    assert len([p for r in rondas for p in r]) == 15


def test_calendario_vuelta_invierte_localia():
    liga = generar_liga(1, n_equipos=6)
    rondas = calendario(liga, INICIO)
    mitad = len(rondas) // 2
    for ida, vuelta in zip(rondas[:mitad], rondas[mitad:]):
        assert vuelta == [(v, loc) for loc, v in ida]


def test_cuotas_mercado_deterministas_y_con_overround():
    probs = (0.5, 0.3, 0.2)
    c1 = cuotas_mercado(probs, random.Random(4))
    c2 = cuotas_mercado(probs, random.Random(4))
    assert c1 == c2
    assert all(c > 1.0 for c in c1)
    assert sum(1 / c for c in c1) == pytest.approx(1.06, abs=0.03)


def test_cuotas_mercado_sin_ruido_ni_margen_reproduce_la_verdad():
    probs = (0.5, 0.3, 0.2)
    cuotas = cuotas_mercado(probs, random.Random(1), margen=0.0, ruido=0.0)
    assert cuotas == pytest.approx(tuple(round(1 / p, 2) for p in probs))


def test_cuotas_mercado_probabilidad_cero_no_revienta():
    cuotas = cuotas_mercado((1.0, 0.0, 0.0), random.Random(1), ruido=0.0)
    assert all(math.isfinite(c) and c > 0 for c in cuotas)


def test_simular_temporada_determinista_y_semillas_distintas_difieren():
    liga = generar_liga(1, n_equipos=6)
    a = simular_temporada(liga, INICIO, 10)
    assert a == simular_temporada(liga, INICIO, 10)
    b = simular_temporada(liga, INICIO, 11)
    assert [(p["gl"], p["gv"]) for p in a] != [(p["gl"], p["gv"]) for p in b]


def test_simular_temporada_esquema_y_consistencia():
    liga = generar_liga(1, n_equipos=6, codigo="QQ", nombre="Liga Q")
    partidos = simular_temporada(liga, INICIO, 3, temporada="2030/2031")
    assert len(partidos) == 6 * 5
    claves_none = ("ap_b365", "ap_pinnacle", "ap_max", "ci_b365", "ci_pinnacle", "ci_max", "ci_prom")
    for p in partidos:
        assert (p["liga"], p["liga_nombre"], p["temporada"]) == ("QQ", "Liga Q", "2030/2031")
        assert p["dia"] == p["fecha"].toordinal()
        assert p["gl"] >= 0 and p["gv"] >= 0
        esperado = "H" if p["gl"] > p["gv"] else "A" if p["gv"] > p["gl"] else "D"
        assert p["resultado"] == esperado
        assert sum(p["verdad"]) == pytest.approx(1.0, abs=1e-6)
        assert len(p["ap_prom"]) == 3 and all(c > 1.0 for c in p["ap_prom"])
        assert all(p[k] is None for k in claves_none)
    # una ronda por semana desde el inicio
    assert partidos[0]["fecha"] == INICIO and partidos[0]["ronda"] == 1
    por_ronda = {p["ronda"]: p["fecha"] for p in partidos}
    assert por_ronda[2] == date(2025, 8, 8)


def test_tabla_hasta_sin_fuga_y_calculos():
    partidos = [
        {"dia": 1, "local": "A", "visitante": "B", "gl": 2, "gv": 0},
        {"dia": 2, "local": "B", "visitante": "C", "gl": 1, "gv": 1},
        {"dia": 3, "local": "C", "visitante": "A", "gl": 0, "gv": 5},
    ]
    tabla = tabla_hasta(partidos, 3)  # el partido del dia 3 no cuenta
    assert set(tabla) == {"A", "B", "C"}
    assert tabla["A"] == {"pj": 1, "pts": 3, "gf": 2, "gc": 0, "forma": [3], "pos": 1}
    assert tabla["B"]["pts"] == 1 and tabla["B"]["forma"] == [0, 1]
    assert tabla["C"]["pts"] == 1 and tabla["C"]["pj"] == 1
    assert [tabla[e]["pos"] for e in ("A", "B", "C")] == [1, 3, 2]  # B pierde el desempate por diferencia de goles
    assert tabla_hasta(partidos, 1) == {}


def test_tabla_hasta_posiciones_unicas_en_temporada_simulada():
    liga = generar_liga(2, n_equipos=8)
    partidos = simular_temporada(liga, INICIO, 7)
    tabla = tabla_hasta(partidos, partidos[-1]["dia"] + 1)
    assert sorted(f["pos"] for f in tabla.values()) == list(range(1, 9))
    assert all(f["pj"] == 14 for f in tabla.values())
    assert sum(f["gf"] for f in tabla.values()) == sum(f["gc"] for f in tabla.values())


def test_el_modulo_no_importa_acceso_a_base_de_datos():
    fuente = open(sintetico.__file__, encoding="utf-8").read()
    assert "sqlite" not in fuente.lower() and "requests" not in fuente
