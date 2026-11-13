"""`backend/scripts/medir_modelo_segmentos_y_cierre.py` (MP-6, MP-15): las piezas puras sobre filas sintéticas. La corrida real necesita los datos históricos, que no se publican."""
from __future__ import annotations

import random

from backend.scripts import medir_modelo_segmentos_y_cierre as m


def _fila(liga="A", r="H", p=(0.5, 0.3, 0.2), tb=(0.45, 0.27, 0.28), ap=(0.5, 0.3, 0.2), ci=(0.5, 0.3, 0.2), dia=1, temporada="2324"):
    return {"liga": liga, "temporada": temporada, "dia": dia, "r": r, "p": p, "tb": tb, "ap": ap, "ci": ci}


def test_el_resumen_calcula_n_perdidas_y_acierto_del_favorito():
    r = m._resumen([_fila(r="H"), _fila(r="D")])
    assert r["n"] == 2 and r["acierto_del_favorito"] == 0.5 and r["prob_media_del_favorito"] == 0.5 and r["log_loss"] > 0


def test_un_segmento_pequeno_se_informa_pero_no_se_compara():
    chico = m._segmento([_fila() for _ in range(10)], minimo=200)
    assert chico["suficiente"] is False and "vs_tasa_base" not in chico
    grande = m._segmento([_fila(dia=i) for i in range(250)], minimo=200)
    assert grande["suficiente"] is True and grande["vs_tasa_base"]["n"] == 250 and "ic95" in grande["vs_cierre"]


def test_el_modelo_igual_al_cierre_no_gana_ni_pierde_contra_el_cierre():
    filas = [_fila(dia=i, r="HDA"[i % 3]) for i in range(60)]
    r = m._contra(filas, "ci")
    assert r["mejora_log_loss"] == 0.0 and r["n"] == 60


def test_si_no_hay_referencia_suficiente_no_se_compara():
    assert m._contra([_fila(ci=None) for _ in range(100)], "ci") is None
    assert m._contra([_fila() for _ in range(10)], "ci") is None


def test_el_agrupar_descarta_las_claves_nulas_y_ordena():
    filas = [_fila(liga="B"), _fila(liga="A"), _fila(liga="A")]
    assert [g["clave"] for g in m._agrupar(filas, lambda f: f["liga"], 1)] == ["A", "B"]
    assert m._agrupar(filas, lambda f: None, 1) == []


def test_el_tramo_decimal_se_acota():
    assert m._tramo_decimal(0.55, 0.3, 0.8) == "0.5-0.6" and m._tramo_decimal(0.1, 0.3, 0.8) == "0.3-0.4" and m._tramo_decimal(0.99, 0.3, 0.8) == "0.8-0.9"


def test_un_modelo_que_se_mueve_con_el_mercado_tiene_correlacion_positiva_y_direccion_alta():
    rng = random.Random(3)
    filas = []
    for i in range(300):
        d = rng.uniform(0.02, 0.08)
        ap = (0.40, 0.30, 0.30)
        ci = (0.40 + d, 0.30 - d / 2, 0.30 - d / 2)              # el mercado se mueve hacia el local
        p = (0.40 + d * 0.8, 0.30 - d * 0.4, 0.30 - d * 0.4)     # el modelo ya apuntaba hacia allá
        filas.append(_fila(p=p, ap=ap, ci=ci, dia=i, r="HDA"[i % 3]))
    v = m.valor_de_cierre(filas)["anticipacion_al_movimiento"]
    assert v["correlacion_desviacion_modelo_vs_movimiento"] > 0.9 and v["acierto_de_direccion"] > 0.95


def test_un_modelo_que_se_mueve_contra_el_mercado_tiene_correlacion_negativa():
    filas = []
    for i in range(300):
        d = 0.05
        filas.append(_fila(p=(0.40 - d, 0.30 + d / 2, 0.30 + d / 2), ap=(0.40, 0.30, 0.30), ci=(0.40 + d, 0.30 - d / 2, 0.30 - d / 2), dia=i, r="HDA"[i % 3]))
    assert m.valor_de_cierre(filas)["anticipacion_al_movimiento"]["correlacion_desviacion_modelo_vs_movimiento"] < -0.9


def test_sin_cuotas_suficientes_el_valor_de_cierre_lo_dice():
    assert "sin cuotas suficientes" in m.valor_de_cierre([_fila(ci=None) for _ in range(500)])["nota"]
