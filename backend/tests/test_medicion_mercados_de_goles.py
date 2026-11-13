"""`backend/scripts/medir_mercados_de_goles.py` (MP-11) y las cuotas de más/menos 2,5 del cargador: piezas puras sobre filas sintéticas; la corrida real necesita datos que no se publican."""
from __future__ import annotations

import csv
import gzip
import math

import pytest

from backend.api.ml import datos
from backend.scripts import medir_mercados_de_goles as m


def test_la_probabilidad_sin_margen_del_mercado_suma_uno_y_respeta_el_favorito():
    assert m.sin_margen_2(2.0, 2.0) == pytest.approx(0.5)
    p = m.sin_margen_2(1.6, 2.4)
    assert p == pytest.approx((1 / 1.6) / (1 / 1.6 + 1 / 2.4)) and p > 0.5


def test_la_perdida_binaria_es_la_de_la_clase_que_ocurrio():
    assert m._ll(0.8, 1) == pytest.approx(-math.log(0.8)) and m._ll(0.8, 0) == pytest.approx(-math.log(0.2))
    assert m._ll(0.0, 1) < 25 and m._ll(1.0, 0) < 25    # nunca infinito


def _fila(p=0.5, y=1, base=0.5, ref=0.5, dia=1):
    return {"liga": "A", "dia": dia, "o25": (p, y, base), "btts": (p, y, base), "m_ap": ref, "m_ci": ref}


def test_un_modelo_mejor_que_la_referencia_sale_positivo_y_peor_negativo():
    mejor = [_fila(p=0.9 if i % 2 else 0.1, y=i % 2, ref=0.5, dia=i) for i in range(200)]
    assert m._comparar(mejor, "o25", lambda f: f["m_ci"])["mejora_log_loss"] > 0.5
    peor = [_fila(p=0.5, y=i % 2, ref=0.9 if i % 2 else 0.1, dia=i) for i in range(200)]
    assert m._comparar(peor, "o25", lambda f: f["m_ci"])["mejora_log_loss"] < -0.5


def test_con_pocas_filas_o_sin_referencia_no_se_compara():
    assert m._comparar([_fila(dia=i) for i in range(50)], "o25", lambda f: f["m_ci"]) is None
    assert m._comparar([_fila(ref=None, dia=i) for i in range(500)], "o25", lambda f: f["m_ci"]) is None


def test_la_calibracion_agrupa_por_tramos_y_acota_el_extremo():
    c = m._calibracion([_fila(p=1.0, y=1), _fila(p=0.05, y=0), _fila(p=0.55, y=1), _fila(p=0.58, y=0)], "o25")
    assert [t["tramo"] for t in c] == ["0.0-0.1", "0.5-0.6", "0.9-1.0"] and c[1]["n"] == 2 and c[1]["frecuencia"] == 0.5


# ---------------------------------------------------------------- el cargador
def _csv(tmp_path, over="1.80", under="2.05", over_c="1.70", under_c="2.20"):
    ruta = tmp_path / "p.csv.gz"
    campos = ["liga_codigo", "liga_nombre", "temporada", "fecha", "local", "visitante", "goles_local", "goles_visitante", "over25_prom", "under25_prom", "over25_prom_cierre", "under25_prom_cierre"]
    with gzip.open(ruta, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerow({"liga_codigo": "E0", "liga_nombre": "Premier", "temporada": "2324", "fecha": "2024-01-02", "local": "A", "visitante": "B", "goles_local": "2", "goles_visitante": "1",
                    "over25_prom": over, "under25_prom": under, "over25_prom_cierre": over_c, "under25_prom_cierre": under_c})
    return ruta


def test_el_cargador_expone_las_cuotas_de_mas_menos_2_5_de_apertura_y_cierre(tmp_path):
    p = datos.cargar_partidos(_csv(tmp_path))[0]
    assert p["o25"] == (1.80, 2.05) and p["o25_cierre"] == (1.70, 2.20)
    assert p["gl"] == 2 and p["resultado"] == "H" and p["ap_prom"] is None       # lo que ya existía no cambia


def test_las_cuotas_vacias_o_invalidas_de_mas_menos_quedan_en_none(tmp_path):
    p = datos.cargar_partidos(_csv(tmp_path, over="", under="2.0", over_c="0.9", under_c="1.5"))[0]
    assert p["o25"] is None and p["o25_cierre"] is None
