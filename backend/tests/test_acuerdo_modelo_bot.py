"""El informe de acuerdo entre el modelo Laplace y el bot: la comparación es simétrica, vale 0 consigo misma y detecta desacuerdo de pick."""
from backend.scripts.acuerdo_modelo_bot import PESO_LAPLACE_SIN_CUOTAS, _mezcla, comparar


def test_comparar_una_lista_consigo_misma_da_acuerdo_total():
    ps = [(0.5, 0.3, 0.2), (0.2, 0.3, 0.5), (0.4, 0.4, 0.2), (0.1, 0.2, 0.7)]
    r = comparar(ps, ps)
    assert r["dif_abs_local"] == 0 and r["mismo_pick"] == 1.0 and r["correlacion_p_local"] == 1.0


def test_comparar_detecta_picks_distintos_y_diferencias_de_probabilidad():
    a = [(0.6, 0.2, 0.2), (0.2, 0.2, 0.6)]
    b = [(0.2, 0.2, 0.6), (0.2, 0.2, 0.6)]
    r = comparar(a, b)
    assert r["mismo_pick"] == 0.5 and r["dif_abs_local"] == 0.2 and r["dif_abs_visitante"] == 0.2
    assert comparar(a, b) == comparar(a, b)


def test_la_mezcla_del_bot_sin_cuotas_suma_uno_y_queda_entre_los_dos_modelos():
    laplace, dc = (0.50, 0.30, 0.20), (0.40, 0.30, 0.30)
    m = _mezcla([laplace, dc], [PESO_LAPLACE_SIN_CUOTAS, 1 - PESO_LAPLACE_SIN_CUOTAS])
    assert abs(sum(m) - 1.0) < 1e-9 and dc[0] < m[0] < laplace[0]
