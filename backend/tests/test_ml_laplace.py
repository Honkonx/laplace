"""Modelo propio de Laplace: pronóstico, simulaciones, importador, entrenamiento walk-forward, registro, servicio con degradación, router y herramienta del agente."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base, get_db
from backend.api.ml.laplace import entrenamiento, pronostico, registro, servicio, simulacion
from backend.api.models.ml_modelo import MlConjuntoDatos, MlMuestra, MlPrediccion


@pytest.fixture(scope="module")
def mundo():
    sim = simulacion.simular(7, n_equipos=16, temporadas=4)
    for p in sim["partidos"]:
        p["ap_prom"] = tuple(p["ap_prom"])
    return sim


@pytest.fixture()
def artefactos_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path / "artefactos")


# ---------- pronóstico ----------
def test_el_pronostico_suma_uno_y_trae_todos_los_mercados():
    r = pronostico.pronosticar(1.6, 1.1)
    assert sum(r["p1x2"].values()) == pytest.approx(1.0)
    assert r["btts"]["si"] + r["btts"]["no"] == pytest.approx(1.0)
    ou = r["over_under"]
    assert ou["1.5"]["mas"] > ou["2.5"]["mas"] > ou["3.5"]["mas"]
    assert r["goles_esperados"]["total"] == pytest.approx(2.7)
    assert len(r["marcadores"]) == 5 and r["marcadores"][0]["prob"] >= r["marcadores"][1]["prob"]
    assert 0.0 <= r["confianza"] <= 1.0


def test_un_p1x2_externo_sustituye_solo_el_1x2():
    r = pronostico.pronosticar(1.6, 1.1, p1x2=(0.5, 0.3, 0.2))
    assert r["p1x2"]["local"] == 0.5
    assert r["goles_esperados"]["local"] == 1.6


def test_confianza_es_cero_sin_informacion_y_alta_con_un_favorito_claro():
    assert pronostico.confianza_desde_probs((1 / 3, 1 / 3, 1 / 3)) == pytest.approx(0.0, abs=1e-9)
    assert pronostico.confianza_desde_probs((0.9, 0.07, 0.03)) > 0.5


# ---------- simulaciones ----------
def test_una_simulacion_es_reproducible_por_semilla():
    a = simulacion.simular(1, n_equipos=8, temporadas=2)
    b = simulacion.simular(1, n_equipos=8, temporadas=2)
    c = simulacion.simular(2, n_equipos=8, temporadas=2)
    assert simulacion.huella(a["partidos"]) == simulacion.huella(b["partidos"]) != simulacion.huella(c["partidos"])
    assert all(p["procedencia"] == "sintetico" for p in a["partidos"])


def test_el_modo_masivo_hace_el_producto_de_semillas_y_rejilla():
    sims = simulacion.simular_masivo([1, 2], {"n_equipos": [6, 8], "temporadas": [1]})
    assert len(sims) == 4
    assert {s["parametros"]["n_equipos"] for s in sims} == {6, 8}


def test_simular_rechaza_parametros_absurdos():
    with pytest.raises(ValueError):
        simulacion.simular(1, n_equipos=2)


def test_exportar_e_importar_csv_conserva_los_partidos(tmp_path):
    sim = simulacion.simular(3, n_equipos=6, temporadas=1)
    ruta = simulacion.exportar_csv(sim["partidos"], tmp_path / "s.csv")
    de_vuelta = simulacion.importar(ruta, "sintetico")
    assert simulacion.huella(de_vuelta) == simulacion.huella(sim["partidos"])


def test_exportar_json_e_importarlo(tmp_path):
    sim = simulacion.simular(3, n_equipos=6, temporadas=1)
    ruta = simulacion.exportar_json(sim, tmp_path / "s.json")
    assert len(simulacion.importar(ruta, "real")) == len(sim["partidos"])


@pytest.mark.parametrize("fila,texto", [
    ({"fecha": "2024-01-01", "liga": "X", "local": "A", "visitante": "B", "gl": "x", "gv": "1"}, "inválido"),
    ({"fecha": "2024-01-01", "liga": "X", "local": "A", "visitante": "A", "gl": "1", "gv": "1"}, "sí mismo"),
    ({"fecha": "2024-01-01", "liga": "X", "local": "A", "visitante": "B", "gl": "99", "gv": "1"}, "fuera de rango"),
    ({"fecha": "2024-01-01", "liga": "X", "local": "A", "visitante": "B", "gv": "1"}, "faltan"),
    ({"fecha": "2024-01-01", "liga": "X", "local": "A", "visitante": "B", "gl": "1", "gv": "1", "cuota_local": "0.9", "cuota_empate": "3", "cuota_visitante": "3"}, "mayores que 1"),
])
def test_el_importador_rechaza_filas_invalidas(tmp_path, fila, texto):
    ruta = tmp_path / "m.json"
    ruta.write_text(json.dumps([fila]), encoding="utf-8")
    with pytest.raises(simulacion.ErrorImportacion, match=texto):
        simulacion.importar(ruta, "real")


def test_el_importador_rechaza_procedencia_y_formato_desconocidos(tmp_path):
    ruta = tmp_path / "m.txt"
    ruta.write_text("x", encoding="utf-8")
    with pytest.raises(simulacion.ErrorImportacion):
        simulacion.importar(ruta, "real")
    ruta2 = tmp_path / "m.csv"
    ruta2.write_text("fecha\n", encoding="utf-8")
    with pytest.raises(simulacion.ErrorImportacion, match="procedencia"):
        simulacion.importar(ruta2, "inventada")


# ---------- entrenamiento ----------
def test_las_caracteristicas_de_un_partido_no_usan_su_propio_resultado():
    estado = entrenamiento.EstadoLiga()
    antes = estado.features("A", "B")
    assert estado.features("A", "B") == antes
    estado.actualizar("A", "B", 5, 0)
    assert estado.features("A", "B") != antes


def test_recorrer_calcula_las_caracteristicas_antes_de_conocer_el_resultado(mundo):
    filas, _ = entrenamiento.recorrer(mundo["partidos"][:20])
    assert filas[0][0] == entrenamiento.EstadoLiga().features(mundo["partidos"][0]["local"], mundo["partidos"][0]["visitante"])


def test_el_modelo_propio_supera_a_la_tasa_base_en_el_periodo_de_prueba(mundo):
    ps = mundo["partidos"]
    corte = sorted(p["dia"] for p in ps)[int(len(ps) * 0.6)]
    res = entrenamiento.evaluar_comparando(ps, corte)
    inf = res["informe"]
    assert inf["mejora_log_loss_sobre_tasa_base"] > 0.02
    assert {"tasa_base", "dixon_coles", "mercado", "oraculo"} <= set(inf["referencias"])
    assert inf["referencias"]["oraculo"]["log_loss"] <= inf["propio"]["log_loss"] + 0.05
    assert inf["n_entrenamiento"] + inf["n_prueba"] <= len(ps)


def test_entrenar_con_pocos_partidos_falla_con_motivo(mundo):
    with pytest.raises(ValueError, match="pocos partidos"):
        entrenamiento.entrenar(mundo["partidos"][:10], 10**9)
    with pytest.raises(ValueError, match="prueba"):
        entrenamiento.evaluar_comparando(mundo["partidos"], 10**9)


def test_el_artefacto_predice_y_distingue_equipos_desconocidos(mundo):
    art = entrenamiento.entrenar(mundo["partidos"], 10**9)
    ok = entrenamiento.predecir_1x2(art, mundo["partidos"][0]["local"], mundo["partidos"][0]["visitante"])
    assert ok["conoce_local"] and sum(ok["p1x2"]) == pytest.approx(1.0)
    assert not entrenamiento.predecir_1x2(art, "Nadie FC", mundo["partidos"][0]["visitante"])["conoce_local"]
    json.dumps(art)  # serializable tal cual


def test_ece_vale_cero_si_esta_perfectamente_calibrado_y_none_sin_datos():
    assert entrenamiento.ece([]) is None
    assert entrenamiento.ece([((1.0, 0.0, 0.0), "H")] * 5) == pytest.approx(0.0)


# ---------- registro y servicio ----------
@pytest.fixture()
def db(artefactos_tmp):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _modelo(db, mundo, nombre="lap", version="v1"):
    art = entrenamiento.entrenar(mundo["partidos"], 10**9)
    return registro.registrar_modelo(db, nombre, version, art, None, {"log_loss": 1.0}), art


def test_guardar_conjunto_conserva_procedencia_y_huella(db, mundo):
    cid = registro.guardar_conjunto(db, "sim7", "v1", mundo["partidos"], "sintetico", mundo)
    c = db.get(MlConjuntoDatos, cid)
    assert c.filas == len(mundo["partidos"]) and c.procedencia == "sintetico" and c.hash_datos
    muestras = db.scalars(select(MlMuestra).where(MlMuestra.conjunto_id == cid)).all()
    assert len(muestras) == c.filas and {m.procedencia for m in muestras} == {"sintetico"}
    with pytest.raises(ValueError):
        registro.guardar_conjunto(db, "x", "v1", mundo["partidos"], "inventada")


def test_registrar_modelo_escribe_artefacto_con_huella_y_detecta_manipulacion(db, mundo):
    mid, _ = _modelo(db, mundo)
    m = db.get(registro.MlModelo, mid)
    assert m.estado == "sombra" and registro.cargar_artefacto(m) is not None
    with open(m.artefacto_ruta, "a", encoding="utf-8") as f:
        f.write(" ")
    assert registro.cargar_artefacto(m) is None


def test_la_promocion_exige_casos_aprobador_y_mejorar_a_la_tasa_base(db, mundo):
    mid, _ = _modelo(db, mundo)
    with pytest.raises(registro.ErrorPromocion, match="nombre"):
        registro.promover(db, mid, " ")
    with pytest.raises(registro.ErrorPromocion, match="faltan casos"):
        registro.promover(db, mid, "admin")
    informe = {"propio": {"n": 250, "log_loss": 1.10, "brier": 0.6, "rps": 0.2, "ece": 0.03}, "referencias": {"tasa_base": {"log_loss": 1.08}}}
    registro.registrar_evaluacion(db, mid, informe, "sombra")
    with pytest.raises(registro.ErrorPromocion, match="tasa base"):
        registro.promover(db, mid, "admin")
    informe["propio"]["log_loss"] = 1.0
    registro.registrar_evaluacion(db, mid, informe, "sombra")
    registro.promover(db, mid, "admin")
    assert registro.modelo_vigente(db).id == mid and registro.modelo_vigente(db).promovido_por == "admin"


def test_promover_retira_al_activo_anterior_del_mismo_nombre(db, mundo):
    informe = {"propio": {"n": 300, "log_loss": 1.0, "brier": 0.6, "rps": 0.2, "ece": 0.03}, "referencias": {"tasa_base": {"log_loss": 1.08}}}
    ids = []
    for v in ("v1", "v2"):
        mid, _ = _modelo(db, mundo, version=v)
        registro.registrar_evaluacion(db, mid, informe, "vivo")
        registro.promover(db, mid, "admin")
        ids.append(mid)
    assert db.get(registro.MlModelo, ids[0]).estado == "retirado" and registro.modelo_vigente(db).id == ids[1]


def test_sin_modelo_activo_el_servicio_cae_al_historico_y_lo_dice(db, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": True, "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "lambda_local": 1.5, "lambda_visit": 1.0})
    r = servicio.pronosticar_partido(db, {"local": "A", "visitante": "B"})
    assert r["ok"] and r["degradado"] and r["fuente"] == "dixon_coles_historico" and "activo" in r["motivo_degradado"]


def test_sin_modelo_ni_historico_responde_ok_falso_con_motivo(db, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False, "razon": "x"})
    r = servicio.pronosticar_partido(db, {"local": "A", "visitante": "B"})
    assert r["ok"] is False and r["motivo"]
    assert servicio.pronosticar_partido(db, {"local": "A", "visitante": "A"})["ok"] is False


def test_con_modelo_activo_el_servicio_lo_usa_y_registra_la_prediccion(db, mundo):
    mid, _ = _modelo(db, mundo)
    db.get(registro.MlModelo, mid).estado = "activo"
    db.commit()
    p = mundo["partidos"][0]
    r = servicio.pronosticar_partido(db, {"local": p["local"], "visitante": p["visitante"], "partido_id": "fx1"}, canal="agente")
    assert r["ok"] and not r["degradado"] and r["fuente"] == "modelo_laplace" and r["modelo"]["id"] == mid
    fila = db.scalars(select(MlPrediccion)).one()
    assert fila.canal == "agente" and fila.partido_id == "fx1"
    assert "publicar" not in json.dumps(r).lower()  # el modelo no opina sobre publicar


def test_un_artefacto_manipulado_degrada_en_vez_de_servirse(db, mundo, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False})
    mid, _ = _modelo(db, mundo)
    m = db.get(registro.MlModelo, mid)
    m.estado = "activo"
    db.commit()
    open(m.artefacto_ruta, "a", encoding="utf-8").write(" ")
    p = mundo["partidos"][0]
    r = servicio.pronosticar_partido(db, {"local": p["local"], "visitante": p["visitante"]})
    assert r["ok"] is False and "huella" in r["motivo"]


def test_el_modelo_en_sombra_se_registra_pero_no_responde(db, mundo, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False})
    mid, _ = _modelo(db, mundo)
    p = mundo["partidos"][0]
    r = servicio.pronosticar_partido(db, {"local": p["local"], "visitante": p["visitante"]}, canal="agente")
    assert r["ok"] is False  # no hay activo
    fila = db.scalars(select(MlPrediccion)).one()
    assert fila.modelo_id == mid and fila.canal == "sombra"


def test_un_equipo_desconocido_para_el_modelo_degrada(db, mundo, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False})
    mid, _ = _modelo(db, mundo)
    db.get(registro.MlModelo, mid).estado = "activo"
    db.commit()
    r = servicio.pronosticar_partido(db, {"local": "Nadie FC", "visitante": mundo["partidos"][0]["visitante"]})
    assert r["ok"] is False and "no conoce" in r["motivo"]


def test_sin_base_de_datos_el_servicio_sigue_respondiendo(monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": True, "prob_local": 0.4, "prob_empate": 0.3, "prob_visitante": 0.3, "lambda_local": 1.2, "lambda_visit": 1.1})
    assert servicio.pronosticar_partido(None, {"local": "A", "visitante": "B"})["degradado"] is True


# ---------- router ----------
@pytest.fixture()
def cliente(db):
    from backend.api.main import app

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.state.http_client = httpx.AsyncClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_el_endpoint_predict_valida_y_devuelve_el_contrato(cliente, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": True, "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "lambda_local": 1.5, "lambda_visit": 1.0})
    r = cliente.post("/api/v1/ml/predict", json={"local": "A", "visitante": "B"})
    assert r.status_code == 200 and r.json()["contrato"] == "ml-1" and r.json()["degradado"] is True
    assert cliente.post("/api/v1/ml/predict", json={"local": "", "visitante": "B"}).status_code == 422


def test_health_es_publico_y_models_exige_admin(cliente):
    assert cliente.get("/api/v1/ml/health").json() == {"contrato": "ml-1", "modelo_activo": False, "version": None}
    assert cliente.get("/api/v1/ml/models").status_code in (401, 422)


# ---------- herramienta del agente ----------
def test_la_herramienta_del_agente_degrada_si_el_modelo_no_responde(monkeypatch):
    from backend.api.services import agent_tools

    async def _cae(*a, **k):
        raise httpx.ConnectError("caído")

    monkeypatch.setattr(agent_tools, "_post", _cae)
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))
    assert r["ok"] is False and r["degradado"] and r["alternativa"] == "sports.predict"


def test_la_herramienta_del_agente_devuelve_el_pronostico_del_modelo(monkeypatch):
    from backend.api.services import agent_tools

    async def _ok(path, payload, **k):
        assert path == "/api/v1/ml/predict" and payload["local"] == "A"
        return {"ok": True, "p1x2": {"local": 0.5}}

    monkeypatch.setattr(agent_tools, "_post", _ok)
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))
    assert r["ok"] and r["tool"] == "modelo.pronosticar"
    assert any(t["name"] == "modelo.pronosticar" and t["read_only"] for t in agent_tools.listar_herramientas_deportivas(es_admin=False))


# ---------- modelo jerárquico, puntero, sombra y fase 2 de la integración ----------
def _por_liga():
    a = simulacion.simular(11, n_equipos=10, temporadas=3)["partidos"]
    b = simulacion.simular(12, n_equipos=10, temporadas=3)["partidos"]
    for ps, cod in ((a, "AAA"), (b, "BBB")):
        for p in ps:
            p["liga"] = cod
    return {"AAA": a, "BBB": b}


def test_el_jerarquico_entrena_universal_y_estado_por_liga_sin_especializar_por_defecto():
    por = _por_liga()
    art = entrenamiento.entrenar_jerarquico(por, 10**9)
    assert art["familia"] == entrenamiento.FAMILIA_JERARQUICA and set(art["ligas"]) == {"AAA", "BBB"}
    assert all(i["pesos"] is None for i in art["ligas"].values())
    e = por["AAA"][0]
    r = entrenamiento.predecir_liga(art, "AAA", e["local"], e["visitante"])
    assert r["conoce_local"] and sum(r["p1x2"]) == pytest.approx(1.0) and r["especializado"] is False
    assert entrenamiento.predecir_liga(art, "ZZZ", "a", "b") is None


def test_la_especializacion_por_liga_usa_pesos_propios_solo_si_hay_partidos_suficientes(monkeypatch):
    monkeypatch.setattr(entrenamiento, "MIN_PARTIDOS_LIGA", 100)
    art = entrenamiento.entrenar_jerarquico(_por_liga(), 10**9, especializar=True)
    assert all(i["pesos"] is not None for i in art["ligas"].values())
    assert entrenamiento.pesos_de(art, "AAA") != art["universal"]


def test_evaluar_jerarquico_compara_universal_jerarquico_y_referencias():
    por = _por_liga()
    corte = sorted(p["dia"] for p in por["AAA"])[int(len(por["AAA"]) * 0.6)]
    inf = entrenamiento.evaluar_jerarquico(por, corte, con_dixon_coles=False)["informe"]
    assert {"universal", "jerarquico", "tasa_base"} <= set(inf["resumen"]) and inf["ligas"] == 2
    assert inf["resumen"]["universal"]["log_loss"] < inf["resumen"]["tasa_base"]["log_loss"]


def test_servicio_con_artefacto_jerarquico_resuelve_liga_y_equipos_con_los_alias(db, monkeypatch):
    por = _por_liga()
    art = entrenamiento.entrenar_jerarquico(por, 10**9)
    e = por["AAA"][0]
    monkeypatch.setattr(servicio, "_resolver_real", lambda d, modelo_id=None: ("AAA", e["local"], e["visitante"]))
    mid = registro.registrar_modelo(db, "jer", "v1", art, None, None)
    db.get(registro.MlModelo, mid).estado = "activo"
    db.commit()
    r = servicio.pronosticar_partido(db, {"local": "Alias Local", "visitante": "Alias Visita", "liga": "Liga A"})
    assert r["ok"] and r["fuente"] == "modelo_laplace" and r["liga_modelo"] == "AAA"
    monkeypatch.setattr(servicio, "_resolver_real", lambda d, modelo_id=None: None)
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False})
    assert servicio.pronosticar_partido(db, {"local": "x", "visitante": "y"})["ok"] is False


def test_el_puntero_permite_servir_sin_base_y_detecta_manipulacion(db, mundo):
    mid, _ = _modelo(db, mundo)
    m = db.get(registro.MlModelo, mid)
    m.estado = "activo"
    db.commit()
    registro.escribir_puntero(m)
    registro._cache_puntero.clear()
    info, art = registro.cargar_vigente_archivo()
    assert info["id"] == mid and art["familia"] == "logistica-elo-goles"
    p = mundo["partidos"][0]
    r = servicio.pronosticar_partido(None, {"local": p["local"], "visitante": p["visitante"]})
    assert r["ok"] and r["fuente"] == "modelo_laplace"
    assert set(r["modelo"]) == {"id", "nombre", "version", "estado"} and "ruta" not in json.dumps(r) and "sha256" not in json.dumps(r)
    with open(m.artefacto_ruta, "a", encoding="utf-8") as f:
        f.write(" ")
    registro._cache_puntero.clear()
    assert registro.cargar_vigente_archivo() == (None, None)
    registro._cache_puntero.clear()


def test_sin_puntero_no_hay_modelo_vigente_en_disco(artefactos_tmp):
    registro._cache_puntero.clear()
    assert registro.cargar_vigente_archivo() == (None, None)


def test_la_promocion_acepta_evidencia_historica_real_suficiente(db, mundo):
    mid, _ = _modelo(db, mundo)
    mala = {"propio": {"n": 5000, "log_loss": 1.07, "brier": 0.6, "rps": 0.2, "ece": 0.02}, "referencias": {"tasa_base": {"log_loss": 1.08}}}
    registro.registrar_evaluacion(db, mid, mala, "historica")
    with pytest.raises(registro.ErrorPromocion, match="margen"):
        registro.promover(db, mid, "admin")
    buena = {**mala, "propio": {**mala["propio"], "log_loss": 1.03}}
    registro.registrar_evaluacion(db, mid, buena, "historica")
    registro.promover(db, mid, "admin")
    assert registro.modelo_vigente(db).id == mid
    registro._cache_puntero.clear()


def test_evaluar_sombra_cruza_predicciones_con_resultados_reales(db, mundo):
    from backend.api.models.partidos import ResultadoPartido

    mid, _ = _modelo(db, mundo)
    assert registro.evaluar_sombra(db, mid) is None
    for i, p in enumerate(mundo["partidos"][:30]):
        registro.registrar_prediccion(db, mid, {"local": p["local"], "visitante": p["visitante"]}, {"p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}, "sombra", 0.0, f"fx{i}")
        db.add(ResultadoPartido(fixture_id=f"fx{i}", local=p["local"], visitante=p["visitante"], goles_local=p["gl"], goles_visitante=p["gv"], fecha_partido="2999-01-01", actualizado_en="2026-01-01"))
    db.commit()
    assert registro.evaluar_sombra(db, mid)["propio"]["n"] == 30
    assert registro.evaluar_sombra(db, mid)["propio"]["n"] == 30  # idempotente: reemplaza la evaluación acumulada
    assert len(db.scalars(select(registro.MlEvaluacion).where(registro.MlEvaluacion.modelo_id == mid)).all()) == 1


def test_resumen_para_consumidores_no_contiene_politica_de_publicacion():
    r = servicio.resumen_para_consumidores({"ok": True, "fuente": "modelo_laplace", "degradado": False, **pronostico.pronosticar(1.5, 1.0), "modelo": None})
    assert set(r) >= {"p1x2", "goles_esperados", "btts_si", "mas_2_5", "marcador_mas_probable"}
    assert "publicar" not in json.dumps(r).lower()
    assert servicio.resumen_para_consumidores({"ok": False}) is None


def test_el_endpoint_tools_define_la_herramienta_para_cualquier_ia(cliente):
    r = cliente.get("/api/v1/ml/tools").json()
    assert r["anthropic"]["name"] == "laplace_pronosticar" and r["openai"]["function"]["parameters"]["required"] == ["local", "visitante"]


def test_el_motor_agrega_el_bloque_informativo_y_no_se_rompe_si_el_modelo_falla(monkeypatch):
    from backend.api.services import motor

    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, e, canal="x": {"ok": False})
    assert motor._pronostico_modelo_laplace({"local": "A", "visitante": "B"}) is None

    def _rompe(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(servicio, "pronosticar_partido", _rompe)
    assert motor._pronostico_modelo_laplace({"local": "A", "visitante": "B"}) is None


def test_el_agente_agrega_el_modelo_al_resumen_de_sports_predict(monkeypatch):
    from backend.api.services import agent_tools

    async def _post(path, payload, **k):
        if path == "/api/v1/ml/predict":
            return {"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": ["total", "btts", "o25"], **pronostico.pronosticar(1.5, 1.0)}
        return {"consenso": {"pick_final": "Local", "prob_ponderada": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}}

    monkeypatch.setattr(agent_tools, "_post", _post)
    args = {"match_id": "1", "local": "A", "visitante": "B", "league": "L"}
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("sports.predict", args, authorization="Bearer x"))
    assert r["resumen"]["modelo_laplace"]["marcador_mas_probable"]


def test_la_evaluacion_descarta_pronosticos_posteriores_al_partido_o_de_otros_equipos(db, mundo):
    from backend.api.models.partidos import ResultadoPartido

    mid, _ = _modelo(db, mundo)
    p = mundo["partidos"][0]
    resp = {"p1x2": {"local": 0.9, "empate": 0.05, "visitante": 0.05}}
    # a) pronóstico hecho DESPUÉS del partido (fecha_partido pasada)
    registro.registrar_prediccion(db, mid, {"local": p["local"], "visitante": p["visitante"]}, resp, "sombra", 0.0, "tarde")
    db.add(ResultadoPartido(fixture_id="tarde", local=p["local"], visitante=p["visitante"], goles_local=2, goles_visitante=0, fecha_partido="2000-01-01", actualizado_en="x"))
    # b) equipos que no coinciden con el resultado del id elegido
    registro.registrar_prediccion(db, mid, {"local": "Otro FC", "visitante": "Nadie FC"}, resp, "sombra", 0.0, "ajeno")
    db.add(ResultadoPartido(fixture_id="ajeno", local=p["local"], visitante=p["visitante"], goles_local=2, goles_visitante=0, fecha_partido="2999-01-01", actualizado_en="x"))
    # c) un caso legítimo
    registro.registrar_prediccion(db, mid, {"local": p["local"], "visitante": p["visitante"]}, resp, "sombra", 0.0, "bueno")
    db.add(ResultadoPartido(fixture_id="bueno", local=p["local"], visitante=p["visitante"], goles_local=2, goles_visitante=0, fecha_partido="2999-01-01", actualizado_en="x"))
    db.commit()
    assert registro.evaluar_sombra(db, mid)["propio"]["n"] == 1


def test_el_endpoint_publico_ignora_el_partido_id_enviado(cliente, db, mundo, monkeypatch):
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": False})
    mid, _ = _modelo(db, mundo)
    m = db.get(registro.MlModelo, mid)
    m.estado = "activo"
    db.commit()
    registro.escribir_puntero(m)
    p = mundo["partidos"][0]
    r = cliente.post("/api/v1/ml/predict", json={"local": p["local"], "visitante": p["visitante"], "partido_id": "fixture-ajeno"})
    assert r.status_code == 200 and r.json()["ok"]
    assert db.scalars(select(MlPrediccion)).all() == []  # el canal público no registra nada
    registro._cache_puntero.clear()


# ---------- M3: generación 2 (hiperparámetros y características afinados) ----------
def test_el_jerarquico_usa_por_defecto_la_generacion_2_y_la_guarda_en_el_artefacto():
    art = entrenamiento.entrenar_jerarquico(_por_liga(), 10**9)
    assert art["hiper"] == entrenamiento.HIPER_DEFECTO and art["generacion"] == "g3"
    estado = entrenamiento.EstadoLiga.de_dict(next(iter(art["ligas"].values()))["estado"])
    assert estado.k_elo == 8.0 and estado.alfa == 0.08 and estado.extras == ("abs_elo", "forma")
    assert len(estado.features("a", "b")) == 7 and len(art["universal"][0]) == 7


def test_los_artefactos_de_la_generacion_1_se_siguen_leyendo_con_sus_valores_originales():
    viejo = entrenamiento.EstadoLiga().a_dict()
    for clave in ("forma", "k_elo", "alfa", "extras"):
        viejo.pop(clave)
    estado = entrenamiento.EstadoLiga.de_dict(viejo)
    assert estado.k_elo == entrenamiento.K_ELO and estado.alfa == entrenamiento.ALFA_GOLES and len(estado.features("a", "b")) == 5


def test_las_caracteristicas_extra_reaccionan_a_la_brecha_y_a_la_forma():
    e = entrenamiento.EstadoLiga(extras=("abs_elo", "forma"))
    base = e.features("A", "B")
    for _ in range(5):
        e.actualizar("A", "B", 3, 0)
    despues = e.features("A", "B")
    assert despues[5] > base[5] and despues[6] > base[6]
