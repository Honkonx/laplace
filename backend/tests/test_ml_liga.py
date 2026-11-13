"""Pruebas de ml/laplace/liga.py (simulación de temporadas, escenarios y caminos) con datos sintéticos."""
from __future__ import annotations

import math
import time
from datetime import date

import pytest

from backend.api.ml import sintetico
from backend.api.ml.laplace import liga
from backend.api.ml.laplace.liga import (
    ErrorEntrada,
    enumerar_caminos,
    simular_escenario,
    simular_temporada,
)


def _mundo(n=6, fuerte=None, pendientes=None):
    equipos = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in equipos]
    pend = pendientes if pendientes is not None else [
        {"local": a, "visitante": b} for a in equipos for b in equipos if a != b]

    def lambdas(local, visitante):
        lh = 1.4 * (2.0 if local == fuerte else 1.0) / (2.0 if visitante == fuerte else 1.0)
        la = 1.1 * (2.0 if visitante == fuerte else 1.0) / (2.0 if local == fuerte else 1.0)
        return lh, la
    return tabla, pend, lambdas


def _error(fn, *a, **k) -> ErrorEntrada:
    with pytest.raises(ErrorEntrada) as exc:
        fn(*a, **k)
    return exc.value


def test_reproducible_misma_semilla_y_distinta_otra():
    t, p, lam = _mundo()
    a = simular_temporada(t, p, lam, n_sim=300, semilla=7)
    b = simular_temporada(t, p, lam, n_sim=300, semilla=7)
    c = simular_temporada(t, p, lam, n_sim=300, semilla=8)
    assert a["huella_salida"] == b["huella_salida"] and a == b
    assert a["huella_salida"] != c["huella_salida"]
    assert a["validado"] is False and a["semilla"] == 7 and a["supuestos"] and a["limitaciones"]
    assert a["huella_entrada"].startswith("sha256:")


def test_identidades_de_probabilidad():
    t, p, lam = _mundo()
    r = simular_temporada(t, p, lam, n_sim=500, semilla=1, cupos=[{"etiqueta": "top2", "posiciones": [1, 2]}])["resultado"]
    n = len(t)
    for probs in r["posiciones"].values():
        assert math.isclose(sum(probs), 1.0, abs_tol=1e-9)
    for pos in range(n):
        assert math.isclose(sum(r["posiciones"][e][pos] for e in r["posiciones"]), 1.0, abs_tol=1e-9)
    assert math.isclose(sum(ev["top2"] for ev in r["eventos"].values()), 2.0, abs_tol=1e-9)
    for res in r["puntos"].values():
        assert res["p05"] <= res["p50"] <= res["p95"]


def test_equipo_superior_es_campeon_y_equipos_iguales_dan_uno_sobre_n():
    t, p, lam = _mundo(fuerte="E0")
    s = simular_temporada(t, p, lam, n_sim=600, semilla=3)
    assert s["resultado"]["posiciones"]["E0"][0] > 0.6
    t, p, lam = _mundo(n=4)
    s = simular_temporada(t, p, lam, n_sim=4000, semilla=3)
    tol = 5 * s["error_montecarlo"]["max_evento"]
    for probs in s["resultado"]["posiciones"].values():
        assert all(abs(x - 0.25) < tol for x in probs)


def test_desempate_por_diferencia_de_goles():
    # sin partidos pendientes la tabla es determinista: empate en puntos, gana el de mejor diferencia
    tabla = [{"equipo": "A", "pj": 2, "pts": 4, "gf": 3, "gc": 3},
             {"equipo": "B", "pj": 2, "pts": 4, "gf": 5, "gc": 1}]
    r = simular_temporada(tabla, [], {}, n_sim=50, semilla=1)["resultado"]["posiciones"]
    assert r["B"] == [1.0, 0.0] and r["A"] == [0.0, 1.0]
    # con goles a favor como segundo criterio cambia el orden
    tabla2 = [{"equipo": "A", "pj": 2, "pts": 4, "gf": 6, "gc": 6},
              {"equipo": "B", "pj": 2, "pts": 4, "gf": 4, "gc": 0}]
    r2 = simular_temporada(tabla2, [], {}, n_sim=20, semilla=1, desempates=("puntos", "goles_favor"))["resultado"]
    assert r2["posiciones"]["A"][0] == 1.0


def test_empate_total_se_sortea():
    tabla = [{"equipo": "A", "pj": 1, "pts": 1, "gf": 1, "gc": 1}, {"equipo": "B", "pj": 1, "pts": 1, "gf": 1, "gc": 1}]
    r = simular_temporada(tabla, [], {}, n_sim=2000, semilla=2)["resultado"]["posiciones"]["A"]
    assert 0.4 < r[0] < 0.6


@pytest.mark.parametrize("kwargs,codigo,campo", [
    ({"n_sim": 20_001}, "limite_excedido", "n_sim"),
    ({"n_sim": 0}, "entrada_invalida", "n_sim"),
    ({"semilla": 1.5}, "entrada_invalida", "semilla"),
    ({"desempates": ("puntos", "azar")}, "entrada_invalida", "desempates"),
    ({"desempates": ("goles_favor",)}, "entrada_invalida", "desempates"),
    ({"cupos": [{"etiqueta": "x", "posiciones": [1, 9]}]}, "entrada_invalida", "cupos[0].posiciones"),
])
def test_errores_cerrados_de_parametros(kwargs, codigo, campo):
    t, p, lam = _mundo(n=4)
    e = _error(simular_temporada, t, p, lam, **{"n_sim": 10, **kwargs})
    assert e.codigo == codigo and e.campo == campo and e.corregible is True
    assert (e.maximo == 20_000) == (codigo == "limite_excedido")
    assert e.como_dict()["ok"] is False


def test_errores_de_tabla_pendientes_y_lambdas():
    t, p, lam = _mundo(n=4)
    e = _error(simular_temporada, [{"equipo": f"X{i}", "pj": 0, "pts": 0, "gf": 0, "gc": 0} for i in range(25)], [], {})
    assert e.codigo == "limite_excedido" and e.maximo == 24
    e = _error(simular_temporada, [*t, dict(t[0])], [], {})
    assert e.codigo == "entrada_invalida" and "repetido" in str(e)
    e = _error(simular_temporada, [{"equipo": " ", "pj": 0, "pts": 0, "gf": 0, "gc": 0}], [], {})
    assert e.codigo == "entrada_invalida"
    e = _error(simular_temporada, t, [{"local": "E0", "visitante": "E1"}] * 501, lam)
    assert e.codigo == "limite_excedido" and e.maximo == 500
    for mala in ((0.0, 1.0), (1.0, 10.0), (-1.0, 1.0), (float("nan"), 1.0)):
        e = _error(simular_temporada, t, [{"local": "E0", "visitante": "E1"}], lambda a, b, m=mala: m)
        assert e.codigo == "entrada_invalida" and "lambdas" in e.campo
    e = _error(simular_temporada, t, [{"local": "E0", "visitante": "Z"}], lam)
    assert e.codigo == "entrada_invalida"
    e = _error(simular_temporada, t, [{"local": "E0", "visitante": "E1"}], {})
    assert e.codigo == "entrada_invalida"


def test_lambdas_como_diccionario():
    t, _, lam = _mundo(n=3)
    pend = [{"local": "E0", "visitante": "E1"}]
    por_dict = simular_temporada(t, pend, {("E0", "E1"): lam("E0", "E1")}, n_sim=100, semilla=4)
    por_func = simular_temporada(t, pend, lam, n_sim=100, semilla=4)
    assert por_dict["huella_salida"] == por_func["huella_salida"]


def test_escenario_forzar_baja_el_titulo_del_lider():
    t, p, lam = _mundo(fuerte="E0")
    perdidos = [{"local": x["local"], "visitante": x["visitante"], "gl": 0, "gv": 3}
                for x in p if x["local"] == "E0"]
    base = {"tabla": t, "pendientes": p, "lambdas": lam, "n_sim": 600, "semilla": 5,
            "cupos": [{"etiqueta": "titulo", "posiciones": [1, 1]}]}
    r = simular_escenario(base, perdidos, modo="forzar")
    assert r["resultado"]["eventos"]["E0"]["titulo"] < r["base"]["eventos"]["E0"]["titulo"]
    assert r["diferencia"]["eventos"]["E0"]["titulo"] < 0
    assert r["aprovechamiento"] == 1.0
    again = simular_escenario(base, perdidos, modo="forzar")
    assert again["huella_salida"] == r["huella_salida"]
    # la base del escenario coincide con la temporada simulada con la misma semilla
    sola = simular_temporada(t, p, lam, n_sim=600, semilla=5, cupos=base["cupos"])
    assert sola["resultado"] == r["base"]


def test_escenario_filtrar_y_datos_insuficientes():
    t, p, lam = _mundo(n=4)
    base = {"tabla": t, "pendientes": p, "lambdas": lam, "n_sim": 500, "semilla": 5}
    ok = simular_escenario(base, [{"local": "E0", "visitante": "E1", "resultado": "1"}], modo="filtrar")
    assert 0.3 < ok["aprovechamiento"] < 0.7 and ok["error_montecarlo"]["n"] < 500
    raro = [{"local": "E0", "visitante": "E1", "gl": 9, "gv": 0}]
    e = _error(simular_escenario, base, raro, modo="filtrar")
    assert e.codigo == "datos_insuficientes"
    e = _error(simular_escenario, base, [{"local": "E0", "visitante": "E1", "resultado": "1"}], modo="forzar")
    assert e.codigo == "entrada_invalida"
    e = _error(simular_escenario, base, [{"local": "E0", "visitante": "E1", "gl": 1, "gv": 0}], modo="otro")
    assert e.campo == "modo"
    e = _error(simular_escenario, base, [{"local": "E0", "visitante": "E1", "gl": 1, "gv": 0}] * 21)
    assert e.codigo == "limite_excedido" and e.maximo == 20
    e = _error(simular_escenario, base, [{"local": "E0", "visitante": "E0", "gl": 1, "gv": 0}])
    assert e.codigo == "entrada_invalida"


def test_escenario_ajustes_de_lambda():
    t, p, lam = _mundo(n=4)
    base = {"tabla": t, "pendientes": p, "lambdas": lam, "n_sim": 600, "semilla": 9,
            "cupos": [{"etiqueta": "titulo", "posiciones": [1, 1]}]}
    r = simular_escenario(base, [{"local": "E0", "visitante": "E1", "gl": 1, "gv": 1}], ajustes={"E0": 2.0})
    assert r["diferencia"]["eventos"]["E0"]["titulo"] > 0
    e = _error(simular_escenario, base, [{"local": "E0", "visitante": "E1", "gl": 1, "gv": 1}], ajustes={"E0": 50})
    assert e.codigo == "entrada_invalida"


def test_enumerar_caminos():
    t, _, lam = _mundo(n=4)
    pend = [{"local": "E0", "visitante": "E1"}, {"local": "E2", "visitante": "E3"}, {"local": "E1", "visitante": "E2"}]
    r = enumerar_caminos(t, pend, lam, {"equipo": "E0", "evento": "titulo"})
    assert r["n_caminos_total"] == 27
    assert math.isclose(r["suma_probabilidades"], 1.0, abs_tol=1e-9)
    assert math.isclose(r["cobertura_de_caminos"], 1.0, abs_tol=1e-9)
    probs = [c["probabilidad"] for c in r["caminos"]]
    assert probs == sorted(probs, reverse=True)
    assert any(c["cumple"] for c in r["caminos"]) and 0 < r["probabilidad_objetivo"] < 1
    cupo = enumerar_caminos(t, pend, lam, {"equipo": "E0", "evento": "cupo", "posiciones": [1, 4]})
    assert math.isclose(cupo["probabilidad_objetivo"], 1.0, abs_tol=1e-9)


def test_enumerar_caminos_limites():
    t, p, lam = _mundo(n=4)
    nueve = (p * 2)[:9]
    e = _error(enumerar_caminos, t, nueve, lam, {"equipo": "E0", "evento": "titulo"})
    assert e.codigo == "limite_excedido" and e.maximo == 8
    ocho = enumerar_caminos(t, p[:8], lam, {"equipo": "E0", "evento": "titulo"})
    assert ocho["n_caminos_total"] == 6561 and len(ocho["caminos"]) == 50
    assert ocho["cobertura_de_caminos"] < 1.0
    assert math.isclose(ocho["suma_probabilidades"], 1.0, abs_tol=1e-9)
    e = _error(enumerar_caminos, t, p[:2], lam, {"equipo": "Z", "evento": "titulo"})
    assert e.codigo == "entrada_invalida"
    e = _error(enumerar_caminos, t, p[:2], lam, {"equipo": "E0", "evento": "cupo", "posiciones": [0, 2]})
    assert e.campo == "objetivo.posiciones"


def test_rendimiento_mil_temporadas_de_380_partidos():
    t, p, lam = _mundo(n=20)
    assert len(p) == 380
    inicio = time.perf_counter()
    simular_temporada(t, p, lam, n_sim=1000, semilla=1)
    assert time.perf_counter() - inicio < 5.0


def test_sintetico_rho_y_deriva_opcionales_no_cambian_el_defecto():
    base = sintetico.simular_temporada(sintetico.generar_liga(3, 8), date(2025, 8, 1), 11)
    de_nuevo = sintetico.simular_temporada(sintetico.generar_liga(3, 8, rho=0.0, deriva=0.0), date(2025, 8, 1), 11)
    assert base == de_nuevo
    con_rho = sintetico.simular_temporada(sintetico.generar_liga(3, 8, rho=-0.10), date(2025, 8, 1), 11)
    assert con_rho != base and len(con_rho) == len(base)
    con_deriva = sintetico.simular_temporada(sintetico.generar_liga(3, 8, deriva=0.2), date(2025, 8, 1), 11)
    assert con_deriva != base
    assert liga.MAX_SIMULACIONES == 20_000


# ---------- MM-22/23: incertidumbre de la fuerza y validación por backtest ----------
def test_la_incertidumbre_de_fuerza_ensancha_el_intervalo_de_puntos_y_es_reproducible():
    tabla, pend, lam = _mundo(6)
    sin = simular_temporada(tabla, pend, lam, n_sim=1500, semilla=3, sigma_fuerza=0.0)["resultado"]["puntos"]["E0"]
    con = simular_temporada(tabla, pend, lam, n_sim=1500, semilla=3, sigma_fuerza=0.2)["resultado"]["puntos"]["E0"]
    assert con["p95"] - con["p05"] > sin["p95"] - sin["p05"]
    a = simular_temporada(tabla, pend, lam, n_sim=500, semilla=9)
    b = simular_temporada(tabla, pend, lam, n_sim=500, semilla=9)
    assert a["huella_salida"] == b["huella_salida"] and a["huella_entrada"] != simular_temporada(tabla, pend, lam, n_sim=500, semilla=9, sigma_fuerza=0.0)["huella_entrada"]


def test_validado_solo_con_un_backtest_local_hecho_con_el_mismo_sigma(tmp_path, monkeypatch):
    import json

    tabla, pend, lam = _mundo(5)
    assert simular_temporada(tabla, pend, lam, n_sim=200)["validado"] is False  # el conftest apunta a un backtest inexistente
    ruta = tmp_path / "bt.json"
    monkeypatch.setattr(liga, "RUTA_BACKTEST", ruta)
    datos = {"validado": True, "sigma_fuerza": liga.SIGMA_FUERZA_DEFECTO, "n_temporadas": 57, "cobertura_p05_p95": 0.9012, "mae_puntos_modelo": 4.4, "mae_puntos_extrapolacion": 4.7, "fraccion": 0.6, "generado": "2026-11-11"}
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    r = simular_temporada(tabla, pend, lam, n_sim=200)
    assert r["validado"] is True and r["backtest"]["n_temporadas"] == 57 and any("backtest en 57 temporadas" in x for x in r["limitaciones"])
    assert simular_temporada(tabla, pend, lam, n_sim=200, sigma_fuerza=0.3)["validado"] is False  # otro sigma: el backtest no vale
    ruta.write_text(json.dumps({**datos, "validado": False}), encoding="utf-8")
    assert simular_temporada(tabla, pend, lam, n_sim=200)["validado"] is False
    ruta.write_text("no es json", encoding="utf-8")
    assert simular_temporada(tabla, pend, lam, n_sim=200)["validado"] is False


def test_la_ruta_por_defecto_del_backtest_apunta_a_la_carpeta_de_resultados_del_repo():
    """H-019 (2026-11-12): `parents[3]` apuntaba a `backend/backend/data/...`, así que `validado` nunca era verdadero fuera de las pruebas (que redirigen la ruta)."""
    from pathlib import Path

    import backend.api.ml.laplace.liga as modulo

    esperada = Path(modulo.__file__).resolve().parents[4] / "backend" / "data" / "resultados" / "backtest_temporadas.json"
    assert (Path(modulo.__file__).resolve().parents[4] / "backend" / "api").is_dir() and "backend/backend" not in esperada.as_posix()
    # el valor original (sin el parche del conftest) es el de la carpeta de resultados del repo
    import importlib.util

    spec = importlib.util.spec_from_file_location("liga_sin_parche", modulo.__file__)
    limpio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(limpio)
    assert limpio.RUTA_BACKTEST == esperada
