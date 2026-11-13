"""test_modelo_historico.py — módulo `historico` del motor (`services/modelo_historico.py`).

Usa un artefacto sintético en un directorio temporal: no depende de los artefactos reales
(que se regeneran) ni de numpy/scipy — la predicción es Python puro.
"""
from __future__ import annotations

import json

import pytest

from backend.api.ml import dixon_coles
from backend.api.services import modelo_historico as mh
from backend.api.services import motor


def _modelo() -> dict:
    return dixon_coles.ModeloLiga(
        mu=0.15, gamma=0.28, rho=-0.1, n_partidos=900,
        ataque={"Manchester City": 0.5, "Sheffield Utd": -0.4, "Tottenham": 0.1},
        defensa={"Manchester City": 0.4, "Sheffield Utd": -0.3, "Tottenham": 0.0},
    ).a_dict()


@pytest.fixture()
def artefactos(tmp_path, monkeypatch):
    (tmp_path / "dixon_coles_ligas.json").write_text(
        json.dumps({"version": "test", "ligas": {"E0": _modelo()}}), encoding="utf-8")
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", tmp_path)
    mh._artefactos.cache_clear()
    yield tmp_path
    mh._artefactos.cache_clear()


def _d(**extra) -> dict:
    return {"liga": "Premier League", "local": "Man City", "visitante": "Sheffield United", **extra}


def test_sin_artefactos_el_modulo_no_participa(tmp_path, monkeypatch):
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", tmp_path)
    mh._artefactos.cache_clear()
    ok, razon = mh.validar_historico(_d())
    assert ok is False and "artefactos" in razon.lower()
    mh._artefactos.cache_clear()


def test_recarga_artefactos_actualizados_sin_reiniciar_proceso(artefactos):
    archivo = artefactos / "dixon_coles_ligas.json"
    assert mh._artefactos()["version"] == "test"
    archivo.write_text(json.dumps({"version": "test-actualizado", "ligas": {"E0": _modelo()}}), encoding="utf-8")
    assert mh._artefactos()["version"] == "test-actualizado"


def test_liga_fuera_de_cobertura_se_omite_con_razon(artefactos):
    ok, razon = mh.validar_historico({"liga": "Liga Profesional", "local": "River Plate", "visitante": "Boca Juniors"})
    assert ok is False and "cobertura" in razon.lower()


def test_equipos_con_alias_se_resuelven_y_favorito_local_gana(artefactos):
    ok, _ = mh.validar_historico(_d(local="Manchester City FC"))
    assert ok is True
    r = mh.analizar(_d())
    assert r["ok"] is True and r["pick"] == "Local" and r["metodo"] == "dixon_coles"
    assert r["prob_local"] + r["prob_empate"] + r["prob_visitante"] == pytest.approx(1.0, abs=1e-3)
    assert r["liga_codigo"] == "E0" and r["muestra_ajuste"] == 900


def test_dos_equipos_desconocidos_no_inventan_probabilidad(artefactos):
    """Medido en `evaluar_equipo_nuevo.py`: con ambos desconocidos no se mejora la tasa base."""
    ok, _ = mh.validar_historico(_d(local="Club Inventado", visitante="Equipo Inventado FC"))
    assert ok is False


def test_un_equipo_sin_historial_usa_el_prior_de_equipo_nuevo_y_lo_declara(artefactos):
    d = _d(visitante="Equipo Inventado FC")
    assert mh.validar_historico(d) == (True, "equipo_sin_historial")
    r = mh.analizar(d)
    assert r["ok"] and r["equipo_sin_historial"] is True and r["metodo"] == "dixon_coles_equipo_nuevo"
    assert r["confianza_score"] <= 35
    assert abs(r["prob_local"] + r["prob_empate"] + r["prob_visitante"] - 1) < 1e-3
    conocido = mh.analizar(_d(visitante="Tottenham"))
    assert conocido["equipo_sin_historial"] is False and conocido["confianza_score"] > r["confianza_score"]


def test_equipo_sin_historial_deja_pasar_al_mercado_cuando_hay_cuotas(artefactos):
    d = _d(visitante="Equipo Inventado FC", odds_disponibles=True, odds_local=1.4, odds_empate=5.0, odds_visit=8.0)
    assert mh.validar_historico(d)[0] is False  # con cuotas reales manda el mercado, medido como mejor


def test_nombre_demasiado_corto_no_se_toma_por_equipo_nuevo(artefactos):
    # Un nombre de 2 letras no identifica a ningún equipo: no se le asigna un rating de equipo nuevo.
    assert mh.validar_historico(_d(visitante="Xy")) == (False, "Liga o equipos fuera de la cobertura del histórico")


def test_referencia_sin_pronostico_siempre_devuelve_tasas(artefactos):
    ref = mh.referencia_sin_pronostico({"liga": "Liga Que No Existe", "local": "A", "visitante": "B"})
    assert ref["nivel"] == "general" and ref["pct_local"] > ref["pct_visitante"] > 0


def test_serie_b_ambigua_se_desambigua_por_equipos_y_no_por_nombre(artefactos):
    # "Serie B" apunta a I2 (no cargada en el artefacto): ningún equipo del test existe allí.
    ok, _ = mh.validar_historico({"liga": "Serie B", "local": "Man City", "visitante": "Tottenham"})
    assert ok is False


def test_con_cuotas_y_apilador_usa_dc_mas_mercado(artefactos):
    (artefactos / "apilador_dc_mercado.json").write_text(json.dumps({
        "coef": [[0.5, 0.1, 1.0, 0.0], [0.0, 0.0, 0.0, 0.0], [0.1, 0.5, 0.0, 1.0]],
        "intercepto": [0.0, 0.0, 0.0]}), encoding="utf-8")
    mh._artefactos.cache_clear()
    r = mh.analizar(_d(odds_disponibles=True, odds_local=1.4, odds_empate=5.0, odds_visit=8.0))
    assert r["metodo"] == "dc_mas_mercado" and r["pick"] == "Local"
    assert r["prob_local"] + r["prob_empate"] + r["prob_visitante"] == pytest.approx(1.0, abs=1e-3)


def test_motor_registra_historico_en_resultados_o_en_skip(artefactos):
    resultados, skip = motor.ejecutar_modulos(_d(
        goles_local_avg=2.0, goles_visit_avg=1.0, goles_contra_local_avg=1.0, goles_contra_visit_avg=1.8,
        fuente_goles="stats_equipo_real"))
    assert "historico" in resultados and "historico" not in skip
    _, skip2 = motor.ejecutar_modulos({"liga": "Liga Profesional", "local": "A", "visitante": "B"})
    assert "historico" in skip2


def test_tasas_base_solo_si_los_equipos_se_reconocen_en_la_liga(artefactos, tmp_path, monkeypatch):
    tasas = tmp_path / "ligas-estadisticas.json"
    tasas.write_text(json.dumps([{"metadata": {
        "liga_codigo": "E0", "partidos": 1140, "pct_local": 44.1, "pct_empate": 23.0,
        "pct_visitante": 32.9, "goles_por_partido": 2.85}}]), encoding="utf-8")
    monkeypatch.setattr(mh, "RUTA_TASAS", tasas)
    mh._tasas_por_liga.cache_clear()
    assert mh.tasas_base_liga(_d())["partidos"] == 1140
    assert mh.tasas_base_liga(_d(visitante="Equipo Inventado")) is None
    mh._tasas_por_liga.cache_clear()


def test_prompt_de_analisis_incluye_tasas_base_cuando_existen(artefactos, tmp_path, monkeypatch):
    from backend.api.services import ai_prompts

    tasas = tmp_path / "ligas-estadisticas.json"
    tasas.write_text(json.dumps([{"metadata": {
        "liga_codigo": "E0", "partidos": 1140, "pct_local": 44.1, "pct_empate": 23.0,
        "pct_visitante": 32.9, "goles_por_partido": 2.85}}]), encoding="utf-8")
    monkeypatch.setattr(mh, "RUTA_TASAS", tasas)
    mh._tasas_por_liga.cache_clear()
    assert "TASAS BASE HISTÓRICAS" in ai_prompts.construir_prompt_analisis(_d())
    assert "TASAS BASE HISTÓRICAS" not in ai_prompts.construir_prompt_analisis(
        {"liga": "Liga Profesional", "local": "A", "visitante": "B"})
    mh._tasas_por_liga.cache_clear()


def test_normalizacion_de_nombres_conserva_identidad_y_unifica_variantes():
    assert mh._normalizar("Manchester City") == "manchester city"  # "st" no se toca dentro de palabras
    assert mh._normalizar("Sheffield Utd") == mh._normalizar("Sheffield United")
    assert mh._normalizar("LA Galaxy") == mh._normalizar("Los Angeles Galaxy")
    assert mh._normalizar("Los Angeles FC") != ""  # nombre hecho solo de palabras de ruido


def test_resumen_tasa_base_es_none_sin_cobertura_y_completo_con_ella(artefactos, tmp_path, monkeypatch):
    tasas = tmp_path / "ligas-estadisticas.json"
    tasas.write_text(json.dumps([{"metadata": {
        "liga_codigo": "E0", "partidos": 1140, "temporadas": ["2024/2025"], "pct_local": 44.1,
        "pct_empate": 23.0, "pct_visitante": 32.9, "goles_por_partido": 2.85}}]), encoding="utf-8")
    monkeypatch.setattr(mh, "RUTA_TASAS", tasas)
    mh._tasas_por_liga.cache_clear()
    resumen = mh.resumen_tasa_base(_d())
    assert resumen["partidos"] == 1140 and resumen["pct_empate"] == 23.0 and "football-data" in resumen["fuente"]
    assert mh.resumen_tasa_base({"liga": "Liga Profesional", "local": "A", "visitante": "B"}) is None
    mh._tasas_por_liga.cache_clear()


# ---------- MB-12: sin cuotas, Dixon-Coles se mezcla con el modelo Laplace ----------
def _propio(local, empate, visitante):
    return {"p1x2": {"local": local, "empate": empate, "visitante": visitante}, "modelo": {"version": "v-test"}}


def test_sin_cuotas_el_historico_mezcla_dixon_coles_con_laplace_55_45(artefactos, monkeypatch):
    from backend.api.ml.laplace import servicio

    base = mh.analizar(_d())
    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: _propio(0.30, 0.40, 0.30))
    mezcla = mh.analizar(_d())
    esperado_local = 0.55 * 0.30 + 0.45 * base["prob_local"]
    assert mezcla["metodo"] == "dixon_coles_mas_laplace" and mezcla["laplace_en_mezcla"] == {"peso": 0.55, "version": "v-test"}
    assert abs(mezcla["prob_local"] - esperado_local) < 1e-3 and abs(mezcla["prob_local"] + mezcla["prob_empate"] + mezcla["prob_visitante"] - 1) < 2e-4
    assert base["metodo"] == "dixon_coles" and base["laplace_en_mezcla"] is None


def test_con_cuotas_el_historico_no_se_toca_y_si_el_modelo_no_cubre_el_partido_queda_dixon_coles(artefactos, monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: _propio(0.30, 0.40, 0.30))
    con_cuotas = mh.analizar(_d(odds_disponibles=True, odds_local=1.4, odds_empate=4.5, odds_visit=8.0))
    assert con_cuotas["laplace_en_mezcla"] is None
    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: None)
    assert mh.analizar(_d())["metodo"] == "dixon_coles"


def test_el_ajuste_apaga_la_mezcla(artefactos, monkeypatch):
    from backend.api.core.config import settings
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: _propio(0.30, 0.40, 0.30))
    monkeypatch.setattr(settings, "CONSENSO_HISTORICO_CON_LAPLACE", False)
    assert mh.analizar(_d())["metodo"] == "dixon_coles"


def test_pronostico_propio_no_usa_el_respaldo_ni_registra_y_devuelve_none_sin_modelo(monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: (None, None, "no hay un modelo Laplace activo"))
    assert servicio.pronostico_propio({"local": "A", "visitante": "B", "liga": "X"}) is None
    assert servicio.pronostico_propio({"local": "A", "visitante": "A"}) is None
