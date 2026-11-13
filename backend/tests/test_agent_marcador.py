"""Marcador de piezas por liga y pesos (MA-20…24): previa histórica + vivo con contracción, límites, líder solo con diferencia suficiente y frase honesta."""
import json

import pytest

from backend.api.services import agent_marcador as m

PREVIA = {"E0": {"modelo": {"n": 1000, "log_loss": 1.000, "rps": 0.2}, "bot": {"n": 1000, "log_loss": 1.010, "rps": 0.2}},
          "SP1": {"modelo": {"n": 800, "log_loss": 1.0100, "rps": 0.2}, "bot": {"n": 800, "log_loss": 1.0105, "rps": 0.2}},
          "F1": {"modelo": {"n": 700, "log_loss": 1.000, "rps": 0.2}}}


def test_sin_vivo_manda_la_previa_y_el_lider_es_el_mejor_historico():
    r = m.ponderar(PREVIA["E0"])
    assert r["lider"] == "modelo" and r["fuente"] == "previa histórica" and r["n_vivo"] == 0 and r["lambda"] == 0.0
    assert r["pesos"]["modelo"] > r["pesos"]["bot"] and r["pesos"]["modelo"] + r["pesos"]["bot"] == pytest.approx(1.0)


def test_los_pesos_estan_acotados_aunque_la_diferencia_sea_enorme():
    r = m.ponderar({"modelo": {"n": 500, "log_loss": 0.9}, "bot": {"n": 500, "log_loss": 1.2}})
    assert r["pesos"]["modelo"] == m.PESO_MAX and r["pesos"]["bot"] == pytest.approx(m.PESO_MIN)


def test_con_diferencia_menor_a_la_minima_no_se_nombra_lider():
    r = m.ponderar(PREVIA["SP1"])
    assert r["lider"] is None and abs(r["pesos"]["modelo"] - 0.5) < 0.05
    assert "no hay evidencia para preferir uno" in m.linea_para_usuario({"liga": "SP1", **r})


def test_pocos_partidos_en_vivo_no_mueven_nada_y_muchos_si_con_contraccion():
    pocos = m.ponderar(PREVIA["E0"], {"modelo": {"n": 10, "log_loss": 1.5}, "bot": {"n": 10, "log_loss": 0.9}})
    assert pocos["lider"] == "modelo" and pocos["lambda"] == 0.0  # menos de 30 en vivo: se ignora
    muchos = m.ponderar(PREVIA["E0"], {"modelo": {"n": 600, "log_loss": 1.05}, "bot": {"n": 600, "log_loss": 1.00}})
    assert muchos["lambda"] == pytest.approx(600 / 750, abs=1e-3) and muchos["lider"] == "bot" and muchos["fuente"] == "previa histórica + vivo"
    medio = m.ponderar(PREVIA["E0"], {"modelo": {"n": 150, "log_loss": 1.05}, "bot": {"n": 150, "log_loss": 1.00}})
    assert medio["lambda"] == 0.5 and medio["perdida"]["modelo"] == pytest.approx(0.5 * 1.05 + 0.5 * 1.0)  # mitad previa, mitad vivo


def test_si_falta_una_pieza_en_la_previa_no_hay_pesos_ni_frase():
    r = m.ponderar(PREVIA["F1"])
    assert r["pesos"] == {} and r["lider"] is None and m.linea_para_usuario({"liga": "F1", **r}) is None


def test_la_frase_con_lider_cita_cifras_y_n_sin_prometer_acierto():
    r = m.resumen_liga("E0", previa=PREVIA)
    frase = m.linea_para_usuario(r)
    assert "modelo Laplace" in frase and "1.0000" in frase and "1.0100" in frase and "1000 partidos" in frase and "no una garantía" in frase and "%" not in frase


def test_cargar_previa_lee_el_json_y_si_no_existe_devuelve_vacio(tmp_path):
    ruta = tmp_path / "previa.json"
    assert m.cargar_previa(ruta) == {}
    ruta.write_text(json.dumps({"corte": "2023-07-01", "ligas": PREVIA}), encoding="utf-8")
    assert m.cargar_previa(ruta)["E0"]["modelo"]["n"] == 1000
    ruta.write_text("no es json", encoding="utf-8")
    assert m.cargar_previa(ruta) == {}


def test_la_tabla_de_admin_ordena_por_partidos_y_omite_ligas_sin_las_dos_piezas():
    filas = m.tabla_admin(PREVIA)
    assert [f["liga"] for f in filas] == ["E0", "SP1"]


def test_el_vivo_sale_del_laboratorio_por_variante_y_liga(db_session):
    from backend.api.models.predicciones import PronosticoExperimental as Obs

    def fila(i, variante, ll, liga="Premier League"):
        return Obs(partido_id=f"p{i}", experimento_codigo="e", fecha_partido="2026-11-01", local="A", visitante="B", liga=liga, fuente="laplace", variante=variante, modelo_version="v",
                   corte_datos_en="2026-11-01T00:00:00Z", creado_en="2026-11-01T00:00:00Z", log_loss=ll, resultado_real="H")

    db_session.add_all([fila(1, "laplace_modelo", 1.0), fila(2, "laplace_modelo", 1.2), fila(3, "dc_mas_mercado_historico", 0.9), fila(4, "laplace_modelo", 5.0, "Otra liga")])
    db_session.commit()
    vivo = m.vivo_desde_laboratorio(db_session, "Premier League")
    assert vivo["modelo"]["n"] == 2 and vivo["modelo"]["log_loss"] == pytest.approx(1.1) and vivo["bot"] == {"n": 1, "log_loss": pytest.approx(0.9)}


def test_la_frase_del_partido_resuelve_la_liga_con_los_alias_y_no_rompe_si_falla(monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(m, "cargar_previa", lambda ruta=None: PREVIA)
    monkeypatch.setattr(servicio, "_resolver_real", lambda datos, modelo_id=None: ("E0", "Arsenal", "Chelsea"))
    assert "modelo Laplace" in m.linea_de_partido(None, "Premier League", "Arsenal", "Chelsea")
    monkeypatch.setattr(servicio, "_resolver_real", lambda datos, modelo_id=None: None)
    assert m.linea_de_partido(None, "Liga X", "A", "B") is None
    monkeypatch.setattr(servicio, "_resolver_real", lambda datos, modelo_id=None: (_ for _ in ()).throw(RuntimeError("falla")))
    assert m.linea_de_partido(None, "Liga X", "A", "B") is None
