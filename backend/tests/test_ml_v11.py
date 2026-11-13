"""Versión 1.1 del modelo (tiros), linaje y reproducibilidad, catálogo de variables y model card (MM-01, MM-02, MM-03, MM-10)."""
import random

import pytest

from backend.api.ml.laplace import entrenamiento, servicio, simulacion, tarjeta, variables

HIPER = entrenamiento.HIPER_V11


def _liga(semilla, cod, con_tiros):
    ps = simulacion.simular(semilla, n_equipos=10, temporadas=3)["partidos"]
    rng = random.Random(semilla)
    for p in ps:
        p["liga"] = cod
        if con_tiros:  # tiros ligados a los goles con ruido: la liga «trae tiros»
            p["tl"], p["tv"] = 8 + 2.2 * p["gl"] + rng.random() * 3, 7 + 2.2 * p["gv"] + rng.random() * 3
            p["al"], p["av"] = 2.5 + 1.2 * p["gl"] + rng.random(), 2 + 1.2 * p["gv"] + rng.random()
        else:
            p["tl"] = p["tv"] = p["al"] = p["av"] = None
    return ps


def _mundo():
    return {"AAA": _liga(21, "AAA", True), "BBB": _liga(22, "BBB", False)}


def test_las_variables_de_tiros_son_cuatro_y_valen_cero_si_la_liga_no_trae_tiros():
    sin = entrenamiento.EstadoLiga(extras=("abs_elo", "forma", "tiros"))
    assert len(sin.features("a", "b")) == 5 + 2 + 4 and sin.features("a", "b")[-4:] == [0.0] * 4
    sin.actualizar("a", "b", 1, 0)  # sin tiros en el partido: el estado de tiros no se mueve
    assert sin.n_tiros == 0 and sin.features("a", "b")[-4:] == [0.0] * 4
    con = entrenamiento.EstadoLiga(extras=("abs_elo", "forma", "tiros"))
    for _ in range(10):
        con.actualizar("a", "b", 2, 0, (18.0, 6.0, 7.0, 2.0))
        con.actualizar("c", "d", 1, 1, (10.0, 10.0, 3.0, 3.0))
    x = con.features("a", "b")[-4:]
    assert x[0] > 0 and x[1] < 0 and x[2] > 0 and x[3] < 0  # a domina en tiros: el local sube y el visitante baja


def test_el_estado_de_tiros_sobrevive_al_artefacto():
    e = entrenamiento.EstadoLiga(extras=("tiros",))
    for _ in range(6):
        e.actualizar("a", "b", 1, 0, (12.0, 9.0, 4.0, 3.0))
    r = entrenamiento.EstadoLiga.de_dict(e.a_dict())
    assert r.n_tiros == 6 and r.features("a", "b") == e.features("a", "b") and r.t_for == e.t_for


def test_v11_usa_pesos_de_respaldo_en_las_ligas_sin_tiros_y_predice_en_ambas():
    mundo = _mundo()
    art = entrenamiento.entrenar_jerarquico(mundo, 10**9, hiper=HIPER, con_goles=False)
    assert art["ligas"]["AAA"]["pesos"] is None and art["ligas"]["BBB"].get("pesos_de_respaldo") is True
    assert len(art["universal"][0]) == 11 and len(art["ligas"]["BBB"]["pesos"][0]) == 11 and art["ligas"]["BBB"]["pesos"][0][-4:] == [0.0] * 4
    for liga in ("AAA", "BBB"):
        p = mundo[liga][-1]
        r = entrenamiento.predecir_liga(art, liga, p["local"], p["visitante"])
        assert sum(r["p1x2"]) == pytest.approx(1.0) and r["especializado"] is False


def test_las_ligas_sin_tiros_dan_en_v11_lo_mismo_que_en_g3():
    """Router por liga: lo que no trae tiros se pronostica con la versión sin tiros (mismos pesos que g3 entrenados con las mismas filas)."""
    mundo = _mundo()
    g3 = entrenamiento.entrenar_jerarquico(mundo, 10**9, hiper=entrenamiento.HIPER_DEFECTO, con_goles=False)
    v11 = entrenamiento.entrenar_jerarquico(mundo, 10**9, hiper=HIPER, con_goles=False)
    p = mundo["BBB"][-1]
    a, b = entrenamiento.predecir_liga(g3, "BBB", p["local"], p["visitante"]), entrenamiento.predecir_liga(v11, "BBB", p["local"], p["visitante"])
    assert a["p1x2"] == pytest.approx(b["p1x2"], abs=1e-6)


# ---------- reproducibilidad y linaje (MM-01) ----------
def test_dos_entrenamientos_con_los_mismos_datos_dan_el_mismo_artefacto_byte_a_byte():
    a = entrenamiento.entrenar_jerarquico(_mundo(), 10**9, hiper=HIPER, con_goles=False)
    b = entrenamiento.entrenar_jerarquico(_mundo(), 10**9, hiper=HIPER, con_goles=False)
    assert tarjeta.huella_artefacto(a) == tarjeta.huella_artefacto(b)
    assert a["linaje"]["hash_datos"] == b["linaje"]["hash_datos"] and a["linaje"]["semilla"] == 0


def test_el_linaje_cambia_si_cambian_los_datos_o_las_variables():
    mundo = _mundo()
    base = entrenamiento.entrenar_jerarquico(mundo, 10**9, hiper=HIPER, con_goles=False)["linaje"]
    menos = {"AAA": mundo["AAA"][:-1], "BBB": mundo["BBB"]}
    assert entrenamiento.entrenar_jerarquico(menos, 10**9, hiper=HIPER, con_goles=False)["linaje"]["hash_datos"] != base["hash_datos"]
    g3 = entrenamiento.entrenar_jerarquico(mundo, 10**9, hiper=entrenamiento.HIPER_DEFECTO, con_goles=False)["linaje"]
    assert g3["version_variables"] != base["version_variables"] and g3["hash_datos"] == base["hash_datos"]


# ---------- catálogo de variables (MM-02) ----------
def test_el_catalogo_describe_las_variables_y_la_version_depende_del_conjunto():
    assert variables.variables_usadas(("abs_elo", "forma", "tiros"))[-3:] == ["abs_elo", "forma", "tiros"]
    assert variables.version_variables(("abs_elo", "forma")) == variables.version_variables(["abs_elo", "forma"]) != variables.version_variables(("abs_elo", "forma", "tiros"))
    assert all({"definicion", "columnas", "ventana"} <= set(v) for v in variables.CATALOGO.values())


def test_la_cobertura_de_tiros_se_mide_por_liga():
    mundo = _mundo()
    cob = variables.cobertura_por_liga(mundo)
    assert cob["AAA"] == 1.0 and cob["BBB"] == 0.0 and variables.ligas_con(mundo) == ["AAA"]


# ---------- ficha y model card (MM-03) ----------
def test_la_ficha_y_la_tarjeta_salen_del_artefacto_sin_rutas_ni_secretos():
    art = entrenamiento.entrenar_jerarquico(_mundo(), 10**9, hiper=HIPER, con_goles=False)
    f = tarjeta.ficha(art)
    assert f["ligas_con_tiros"] == ["AAA"] and f["pesos_de_respaldo_en"] == ["BBB"] and f["n_ligas"] == 2 and f["version_variables"].startswith("vars-")
    md = tarjeta.markdown(f, {"resumen": {"universal": {"log_loss": 1.0, "rps": 0.2, "n": 10}}, "comparaciones": {"modelo_vs_tasa_base": {"diferencia_media": 0.05, "z": 9.0, "ic95": (0.04, 0.06), "n": 10}}}, "v1.1")
    assert "Model card" in md and "no es una recomendación de apuesta" in md and "Tiros y tiros a puerta" in md and "modelo_vs_tasa_base" in md and "## Límites" in md
    assert "C:\\" not in md and "/Users/" not in md and "token" not in md.lower()


def test_la_ficha_del_servicio_dice_cuando_no_hay_modelo(monkeypatch):
    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: (None, None, "no hay un modelo Laplace activo"))
    assert servicio.ficha_modelo(None) == {"ok": False, "motivo": "no hay un modelo Laplace activo"}
    art = entrenamiento.entrenar_jerarquico(_mundo(), 10**9, hiper=HIPER, con_goles=False)
    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: ({"id": 1, "nombre": "x", "version": "v", "estado": "activo"}, art, ""))
    r = servicio.ficha_modelo(None)
    assert r["ok"] and r["modelo"]["version"] == "v" and r["ligas_con_tiros"] == ["AAA"]
