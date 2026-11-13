"""Mercados de goles calibrados del modelo Laplace: encogimiento, calibración logística, validación contra la tasa base y ocultamiento de lo no validado."""
import math
import random

from backend.api.ml.laplace import goles, servicio


def _poisson(rng: random.Random, lam: float) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def _filas_sobredispersas(n: int = 5000, semilla: int = 7) -> list[tuple]:
    """λ estimadas con ruido que las vuelve demasiado extremas (justo el defecto medido en los datos reales): la verdad es más cercana a la media."""
    rng = random.Random(semilla)
    filas = []
    for _ in range(n):
        v_h, v_a = rng.gauss(0, 0.45), rng.gauss(0, 0.45)
        verdad_h, verdad_a = 1.45 * math.exp(0.35 * v_h), 1.1 * math.exp(0.35 * v_a)
        estimada_h, estimada_a = 1.45 * math.exp(v_h), 1.1 * math.exp(v_a)
        filas.append((min(5.0, estimada_h), min(5.0, estimada_a), 1.45, 1.1, _poisson(rng, verdad_h), _poisson(rng, verdad_a)))
    return filas


def test_encoger_extremos_y_neutro():
    assert goles.encoger(2.0, 1.4, 1.0) == 2.0
    assert abs(goles.encoger(2.0, 1.4, 0.0) - 1.4) < 1e-9
    assert goles.TOPE_LAMBDA[0] <= goles.encoger(100.0, 1.4, 1.0) <= goles.TOPE_LAMBDA[1]


def test_platt_recupera_una_probabilidad_ya_calibrada():
    rng = random.Random(3)
    X, y = [], []
    for _ in range(4000):
        p = rng.uniform(0.25, 0.75)
        X.append([1.0, goles.logit(p), goles.logit(0.5)])
        y.append(int(rng.random() < p))
    w = goles.ajustar_platt(X, y)
    assert abs(w[1] - 1.0) < 0.2 and abs(w[0]) < 0.2


def test_calibrar_encoge_las_lambdas_y_valida_contra_la_tasa_base():
    cal = goles.calibrar({"L1": _filas_sobredispersas()})
    assert cal is not None and cal["s"] < 0.8
    assert set(cal["platt"]) == set(goles.MERCADOS) and "L1" in cal["tasas_liga"]
    assert cal["util"]["total"] is True
    res = cal["reserva"]["btts"]
    assert res["log_loss"] < res["log_loss_tasa_base"] or cal["util"]["btts"] is False
    assert cal["util"]["btts"] == (res["log_loss"] < res["log_loss_tasa_base"])


def test_pocas_filas_no_calibra():
    assert goles.calibrar({"L1": _filas_sobredispersas(300)}) is None


def test_sin_calibracion_ningun_mercado_de_goles_queda_validado():
    r = goles.pronosticar(1.6, 1.1, (1.45, 1.1), None, None, p1x2=(0.5, 0.3, 0.2))
    assert r["validados"] == [] and r["p1x2"]["local"] == 0.5


def test_con_calibracion_los_mercados_son_probabilidades_y_se_listan_los_validados():
    cal = goles.calibrar({"L1": _filas_sobredispersas()})
    r = goles.pronosticar(2.4, 0.7, (1.45, 1.1), {k: v for k, v in cal.items() if k != "tasas_liga"}, cal["tasas_liga"]["L1"], p1x2=(0.6, 0.25, 0.15))
    assert 0 < r["btts"]["si"] < 1 and abs(r["btts"]["si"] + r["btts"]["no"] - 1) < 1e-9
    assert r["over_under"]["2.5"]["mas"] > r["over_under"]["3.5"]["mas"]
    assert "total" in r["validados"]
    # λ muy extremas quedan encogidas hacia la media: los goles esperados no pueden superar los crudos
    assert r["goles_esperados"]["total"] < 3.1
    pub = servicio.publico({"ok": True, **r})
    assert "goles_esperados" in pub


def test_la_salida_publica_conserva_el_1x2_aunque_no_haya_goles_validados():
    r = goles.pronosticar(1.6, 1.1, (1.45, 1.1), None, None, p1x2=(0.5, 0.3, 0.2))
    pub = servicio.publico({"ok": True, **r})
    assert pub["p1x2"] and "btts" not in pub and "marcadores" not in pub and "goles_esperados" not in pub


def _matriz_de_referencia(lam_h, lam_a, rho):
    """La versión por celda (lenta) que había antes de MM-04: es la definición de lo que debe dar la rápida."""
    from backend.api.ml import dixon_coles
    from backend.api.ml.laplace import pronostico

    m = [[dixon_coles._pmf(i, lam_h) * dixon_coles._pmf(j, lam_a) * max(dixon_coles._tau(i, j, lam_h, lam_a, rho), 0.0)
          for j in range(pronostico.MAX_GOLES)] for i in range(pronostico.MAX_GOLES)]
    total = sum(sum(f) for f in m) or 1.0
    return [[p / total for p in f] for f in m]


def test_la_matriz_de_goles_rapida_da_lo_mismo_que_la_definicion_por_celda():
    from backend.api.ml.laplace import pronostico

    rng = random.Random(11)
    for _ in range(300):
        lh, la, rho = rng.uniform(0.15, 5), rng.uniform(0.15, 5), rng.uniform(-0.2, 0.05)
        rapida, lenta = pronostico.matriz_goles(lh, la, rho), _matriz_de_referencia(lh, la, rho)
        assert max(abs(a - b) for fa, fb in zip(rapida, lenta) for a, b in zip(fa, fb)) < 1e-15
