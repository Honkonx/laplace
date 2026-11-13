"""Apilado del 1X2 del modelo con las cuotas: validación de entrada, aplicación y que nunca sustituya al 1X2 propio."""
import pytest

from backend.api.ml.laplace import apilado, pronostico, servicio

APILADOR = {"pesos": [[0.0, 0.1, 0.0, 0.0, 0.6, 0.0, 0.0], [0.0, 0.0, 0.1, 0.0, 0.0, 0.6, 0.0], [0.0, 0.0, 0.0, 0.1, 0.0, 0.0, 0.6]], "util": True,
            "evaluacion": {"log_loss_modelo": 1.01, "log_loss_mercado": 0.995, "log_loss_apilado": 0.994}}


@pytest.mark.parametrize("malas", [None, [1.5, 3.0], ["a", "b", "c"], [1.0, 3.0, 4.0], [1.5, 3.0, 99999.0], [1.5, float("nan"), 4.0], "texto"])
def test_cuotas_invalidas_se_rechazan(malas):
    assert apilado.cuotas_validas(malas) is None


def test_cuotas_validas_se_aceptan():
    assert apilado.cuotas_validas([1.8, 3.4, 4.5]) == (1.8, 3.4, 4.5)


def test_aplicar_devuelve_una_distribucion_y_sigue_al_mercado():
    p = apilado.aplicar(APILADOR, (0.4, 0.3, 0.3), [1.5, 4.0, 7.0])
    assert p is not None and abs(sum(p) - 1) < 1e-9 and p[0] > p[1] > p[2]


def test_sin_apilador_util_o_sin_cuotas_no_aplica():
    assert apilado.aplicar({**APILADOR, "util": False}, (0.4, 0.3, 0.3), [1.5, 4.0, 7.0]) is None
    assert apilado.aplicar(None, (0.4, 0.3, 0.3), [1.5, 4.0, 7.0]) is None
    assert apilado.aplicar(APILADOR, (0.4, 0.3, 0.3), None) is None


def test_el_resumen_expone_la_lectura_con_mercado_aparte_del_1x2_propio():
    base = {"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": [], **pronostico.pronosticar(1.6, 1.1)}
    sin = servicio.resumen_para_consumidores(base)
    con = servicio.resumen_para_consumidores({**base, "p1x2_con_mercado": {"local": 0.5, "empate": 0.3, "visitante": 0.2}})
    assert sin["p1x2_con_mercado"] is None
    assert con["p1x2_con_mercado"] == {"local": 0.5, "empate": 0.3, "visitante": 0.2} and con["p1x2"] == sin["p1x2"]
