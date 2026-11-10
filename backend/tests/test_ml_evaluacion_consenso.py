"""test_ml_evaluacion_consenso.py — `ml/evaluacion_consenso.py` (piezas puras) y el script de evaluación.

El script usa numpy/scikit-learn: sus pruebas se saltan si no están instalados (venv del backend).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from backend.api.ml import evaluacion_consenso as ec
from backend.api.ml import metricas
from backend.api.services import consenso

MODS = {
    "odds": (0.55, 0.25, 0.20, 70),
    "historico": (0.50, 0.28, 0.22, 60),
    "forma": (0.40, 0.26, 0.34, 55),
}


def test_evaluar_consenso_equivale_a_calcular_consenso_y_restaura_pesos():
    antes = dict(consenso.PESOS_BASE)
    r = ec.evaluar_consenso(MODS)
    directo = consenso.calcular_consenso(ec.a_resultados(MODS))
    assert r["probs"] == (directo["prob_ponderada"]["local"], directo["prob_ponderada"]["empate"], directo["prob_ponderada"]["visitante"])
    assert r["pick"] == directo["pick_final"] and r["score"] == directo["score_consenso"]
    assert consenso.PESOS_BASE == antes


def test_pesos_candidatos_se_aplican_y_se_restauran_aun_con_error():
    antes = dict(consenso.PESOS_BASE)
    solo_odds = ec.evaluar_consenso(MODS, {"odds": 1.0})
    assert solo_odds["modulos_ok"] == ["odds"]
    assert solo_odds["probs"][0] == pytest.approx(0.55)
    with pytest.raises(RuntimeError):
        with ec.pesos_consenso({"odds": 1.0}):
            assert consenso.PESOS_BASE["forma"] == 0.0
            raise RuntimeError("falla dentro del bloque")
    assert consenso.PESOS_BASE == antes


def test_sin_modulos_devuelve_none():
    assert ec.evaluar_consenso({}) is None
    assert ec.evaluar_consenso(MODS, {"poisson": 1.0}) is None


def test_wilson_acota_la_proporcion():
    lo, hi = ec.wilson(50, 100)
    assert lo < 0.5 < hi and 0.39 < lo and hi < 0.61
    assert ec.wilson(0, 0) == (0.0, 0.0)


def test_tabla_por_grupos_y_distribucion():
    filas = [{"probs": (0.6, 0.2, 0.2), "res": "H", "g": "alto"}, {"probs": (0.6, 0.2, 0.2), "res": "A", "g": "alto"},
             {"probs": (0.2, 0.6, 0.2), "res": "D", "g": "bajo"}]
    tabla = {t["grupo"]: t for t in ec.tabla_por_grupos(filas, lambda f: f["g"])}
    assert tabla["alto"]["n"] == 2 and tabla["alto"]["accuracy"] == 0.5
    assert tabla["bajo"]["accuracy"] == 1.0
    assert ec.distribucion_picks(filas)["picks"]["D"] == pytest.approx(1 / 3, abs=1e-4)


def _cargar_script():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "evaluar_consenso_historico.py"
    spec = importlib.util.spec_from_file_location("evaluar_consenso_historico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_metricas_vectorizadas_coinciden_con_ml_metricas():
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    script = _cargar_script()
    pares = [((0.5, 0.3, 0.2), "H"), ((0.2, 0.3, 0.5), "H"), ((0.3, 0.4, 0.3), "D"), ((0.1, 0.2, 0.7), "A")]
    P = np.array([p for p, _ in pares])
    y = np.array([metricas.INDICE[r] for _, r in pares])
    esperado = metricas.resumen(pares)
    obtenido = script.resumen_np(script.metricas_np(P, y))
    for k in ("rps", "brier", "log_loss", "accuracy"):
        assert obtenido[k] == pytest.approx(esperado[k], abs=1e-5)


def test_el_recorrido_walk_forward_no_filtra_resultados_futuros():
    """Alterar los resultados posteriores a un partido no cambia sus señales ni su consenso."""
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from datetime import date

    script = _cargar_script()
    base = date(2022, 8, 1).toordinal()
    equipos = [f"E{i}" for i in range(6)]
    partidos, dia = [], base
    for ronda in range(30):
        for i in range(3):
            h, a = equipos[(i + ronda) % 6], equipos[(i + 3 + 2 * ronda) % 6]
            if h == a:
                continue
            gl, gv = (ronda + i) % 4, (ronda * 3 + i) % 3
            partidos.append({
                "liga": "E0", "liga_nombre": "Premier League", "temporada": "2223", "dia": dia, "fecha": date.fromordinal(dia),
                "local": h, "visitante": a, "gl": gl, "gv": gv, "resultado": "H" if gl > gv else "A" if gv > gl else "D",
                "ap_prom": (2.0 + 0.1 * i, 3.4, 3.8), "ci_pinnacle": (2.0, 3.4, 3.8), "ci_prom": (2.0, 3.4, 3.8),
                "ap_b365": None, "ap_pinnacle": None, "ap_max": None, "ci_b365": None, "ci_max": None,
            })
        dia += 7
    hp = {"xi": 0.0019, "ridge": 2.0, "rho": -0.05}
    corte = len(partidos) - 6
    original = script.recorrer({"E0": partidos}, hp, base)
    import copy
    alterados = copy.deepcopy(partidos)
    for p in alterados[corte:]:
        p["gl"], p["gv"], p["resultado"] = 7, 0, "H"
    nuevos = script.recorrer({"E0": alterados}, hp, base)
    ya_vistos = [(a, b) for a, b in zip(original, nuevos) if a["dia"] < alterados[corte]["dia"]]
    assert ya_vistos, "el arnés debió producir registros antes del corte"
    for a, b in ya_vistos:
        assert a == b
