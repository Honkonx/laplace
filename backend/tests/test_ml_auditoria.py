"""Auditoría del modelo (`ml/laplace/auditoria.py`): cadena de sellos (MP-5), memoria de errores (MP-1), puerta del reentreno (MP-2) y memoria por equipo (MP-4).

Sobre una base construida con las MIGRACIONES REALES (no `create_all`): una columna o tabla sin migrar rompe aquí, no en producción."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select, text

from backend.api.ml.laplace import auditoria, entrenamiento, estado_vivo, registro, simulacion
from backend.api.models.ml_modelo import MlError, MlEstadoVivo, MlModelo, MlPrediccion
from backend.api.models.partidos import ResultadoPartido

P = {"p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}


@pytest.fixture()
def db(base_migrada, monkeypatch, tmp_path):
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path / "artefactos")
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


def _modelo(db, estado="activo", nombre="m", version="v1"):
    m = MlModelo(nombre=nombre, version=version, familia="x", tarea="1x2", estado=estado, creado_en="2026-11-13T00:00:00")
    db.add(m)
    db.commit()
    return m


def _pred(db, mid, i, local="Alfa", visita="Beta", p=None):
    return registro.registrar_prediccion(db, mid, {"local": local, "visitante": visita}, p or P, "sombra", 1.0, f"fx{i}")


def _resultado(db, i, gl, gv, local="Alfa", visita="Beta", liga="Liga X"):
    db.add(ResultadoPartido(fixture_id=f"fx{i}", local=local, visitante=visita, liga=liga, goles_local=gl, goles_visitante=gv, fecha_partido="2999-01-15", actualizado_en="x"))
    db.commit()


# ---------------------------------------------------------------- MP-5
def test_la_migracion_real_crea_las_columnas_del_sello_y_la_tabla_de_errores(db):
    cols = {r[1] for r in db.execute(text("PRAGMA table_info(ml_predicciones)"))}
    assert {"hash_previo", "hash_fila"} <= cols
    assert db.execute(text("SELECT count(*) FROM ml_errores")).scalar() == 0


def test_cada_pronostico_nuevo_queda_sellado_y_encadenado(db):
    m = _modelo(db)
    for i in range(4):
        _pred(db, m.id, i)
    filas = db.scalars(select(MlPrediccion).order_by(MlPrediccion.id)).all()
    assert filas[0].hash_previo == auditoria.GENESIS
    assert all(filas[i].hash_previo == filas[i - 1].hash_fila for i in range(1, 4))
    assert len({f.hash_fila for f in filas}) == 4
    assert auditoria.verificar_cadena(db) == {"ok": True, "filas_selladas": 4, "filas_anteriores_a_la_cadena": 0, "ruptura": None}


@pytest.mark.parametrize("sabotaje, motivo", [
    ("UPDATE ml_predicciones SET probabilidades_json = '{\"local\": 0.99, \"empate\": 0.005, \"visitante\": 0.005}' WHERE id = 2", "contenido"),
    ("DELETE FROM ml_predicciones WHERE id = 2", "no coincide"),
])
def test_la_cadena_detecta_una_fila_alterada_o_borrada(db, sabotaje, motivo):
    m = _modelo(db)
    for i in range(4):
        _pred(db, m.id, i)
    db.execute(text(sabotaje))
    db.commit()
    r = auditoria.verificar_cadena(db)
    assert r["ok"] is False and motivo in r["ruptura"]["motivo"]
    assert r["ruptura"]["id"] in (2, 3)


def test_las_filas_anteriores_a_la_cadena_no_cuentan_pero_una_sin_sello_despues_si(db):
    m = _modelo(db)
    db.add(MlPrediccion(modelo_id=m.id, partido_id="viejo", entrada_json="{}", probabilidades_json=json.dumps(P["p1x2"]), canal="http", creada_en="2026-01-01"))
    db.commit()
    _pred(db, m.id, 1)
    assert auditoria.verificar_cadena(db)["ok"] is True
    db.add(MlPrediccion(modelo_id=m.id, partido_id="colada", entrada_json="{}", probabilidades_json=json.dumps(P["p1x2"]), canal="http", creada_en="2026-11-01"))
    db.commit()
    r = auditoria.verificar_cadena(db)
    assert r["ok"] is False and "sin sello" in r["ruptura"]["motivo"] and r["filas_anteriores_a_la_cadena"] == 1


def test_una_base_vacia_tiene_cadena_valida(db):
    assert auditoria.verificar_cadena(db)["ok"] is True


# ---------------------------------------------------------------- MP-1
def test_el_bucle_guarda_el_error_por_partido_y_es_idempotente(db):
    m = _modelo(db)
    _pred(db, m.id, 1, p={"p1x2": {"local": 0.7, "empate": 0.2, "visitante": 0.1}})
    _pred(db, m.id, 2, p={"p1x2": {"local": 0.7, "empate": 0.2, "visitante": 0.1}})
    _resultado(db, 1, 2, 0)            # acierta
    _resultado(db, 2, 0, 1)            # falla
    assert auditoria.cerrar_bucle(db, m.id) == 2
    assert auditoria.cerrar_bucle(db, m.id) == 0
    a, f = sorted(db.scalars(select(MlError)), key=lambda e: e.partido_id)
    assert (a.acierto, f.acierto) == (1, 0) and a.rps < f.rps and a.log_loss < f.log_loss
    assert a.tramo == "0.7-0.8" and a.resultado == "H" and f.resultado == "A"


def test_el_bucle_ignora_pronosticos_posteriores_al_partido_y_partidos_sin_resultado(db):
    m = _modelo(db)
    _pred(db, m.id, 1)
    _pred(db, m.id, 2)
    db.add(ResultadoPartido(fixture_id="fx1", local="Alfa", visitante="Beta", liga="L", goles_local=1, goles_visitante=0, fecha_partido="2000-01-01", actualizado_en="x"))
    db.add(ResultadoPartido(fixture_id="fx2", local="Alfa", visitante="Beta", liga="L", goles_local=None, goles_visitante=None, fecha_partido="2999-01-01", actualizado_en="x"))
    db.commit()
    assert auditoria.cerrar_bucle(db, m.id) == 0


def test_el_informe_marca_los_segmentos_sin_muestra_y_lista_los_peores(db):
    m = _modelo(db)
    for i in range(40):
        _pred(db, m.id, i, p={"p1x2": {"local": 0.6, "empate": 0.25, "visitante": 0.15}})
        _resultado(db, i, 1, 0, liga="Grande" if i < 35 else "Chica")
    auditoria.cerrar_bucle(db, m.id)
    r = auditoria.informe_errores(db, m.id, peores=3)
    por = {g["clave"]: g for g in r["por_liga"]}
    assert r["n"] == 40 and por["Grande"]["suficiente"] is True and por["Chica"]["suficiente"] is False
    assert por["Grande"]["acierto"] == 1.0 and por["Grande"]["prob_media_del_favorito"] == 0.6
    assert len(r["peores"]) == 3 and r["por_mes"][0]["clave"] == "2999-01"


def test_el_informe_sin_datos_no_falla(db):
    assert auditoria.informe_errores(db)["n"] == 0


# ---------------------------------------------------------------- MP-2
def test_la_puerta_exige_mejora_minima_y_calibracion_y_avisa_si_no_es_comparable():
    vig = {"n": 1000, "log_loss": 1.000, "rps": 0.200, "ece": 0.010}
    mejor = auditoria.puerta_reentreno({"n": 1000, "log_loss": 0.998, "rps": 0.199, "ece": 0.010}, vig)
    assert mejor["pasa"] is True and mejor["comparable"] is True and mejor["delta_log_loss"] == 0.002 and mejor["pareada"] is False
    assert auditoria.puerta_reentreno({"n": 1000, "log_loss": 0.9995, "rps": 0.2, "ece": 0.01}, vig)["pasa"] is False                # mejora < 0,001
    assert auditoria.puerta_reentreno({"n": 1000, "log_loss": 0.990, "rps": 0.2, "ece": 0.030}, vig)["pasa"] is False                # peor calibrado
    distinto = auditoria.puerta_reentreno({"n": 1100, "log_loss": 0.990, "rps": 0.2, "ece": 0.010}, vig)
    assert distinto["comparable"] is False and "indicativo" in distinto["veredicto"]
    sin = auditoria.puerta_reentreno({"n": 10, "log_loss": 1.0}, None)
    assert sin["hay_vigente"] is False and sin["pasa"] is None


def test_la_evaluacion_historica_del_vigente_se_lee_de_la_base(db):
    m = _modelo(db)
    assert auditoria.evaluacion_historica_de(db, m.id) is None
    registro.registrar_evaluacion(db, m.id, {"propio": {"n": 500, "log_loss": 1.01, "brier": 0.6, "rps": 0.2, "ece": 0.02}, "referencias": {}}, "historica")
    assert auditoria.evaluacion_historica_de(db, m.id) == {"n": 500, "log_loss": 1.01, "rps": 0.2, "ece": 0.02}


# ---------------------------------------------------------------- MP-4
@pytest.fixture()
def modelo_con_memoria(db):
    a = simulacion.simular(11, n_equipos=8, temporadas=2)["partidos"]
    for p in a:
        p["liga"] = "AAA"
    art = entrenamiento.entrenar_jerarquico({"AAA": a}, max(p["dia"] for p in a) + 1)
    mid = registro.registrar_modelo(db, "jer", "v1", art, None, None)
    m = db.get(MlModelo, mid)
    m.estado = "activo"
    db.commit()
    return m, art, sorted({p["local"] for p in a})[0]


def test_la_memoria_por_equipo_sale_del_artefacto_y_luego_de_la_base_al_dia(db, modelo_con_memoria):
    m, art, equipo = modelo_con_memoria
    r = auditoria.memoria_equipo(db, m, "AAA", equipo.upper(), art)
    assert r["fuente"] == "artefacto" and r["equipo"] == equipo and r["partidos"] > 0 and r["rating_elo"] > 0 and r["modelo"]["id"] == m.id
    est = entrenamiento.EstadoLiga.de_dict(art["ligas"]["AAA"]["estado"])
    est.elo[equipo] += 50
    db.add(MlEstadoVivo(modelo_id=m.id, liga="AAA", estado_json=json.dumps(est.a_dict()), hasta_dia=1, partidos=5, actualizado_en="2026-11-13T06:40:00"))
    db.commit()
    vivo = auditoria.memoria_equipo(db, m, "AAA", equipo, art)
    assert vivo["fuente"] == "estado_vivo" and vivo["actualizado_en"] == "2026-11-13T06:40:00" and vivo["rating_elo"] == pytest.approx(r["rating_elo"] + 50, abs=0.1)


def test_la_memoria_por_equipo_dice_none_si_no_conoce_la_liga_o_el_equipo(db, modelo_con_memoria):
    m, art, _ = modelo_con_memoria
    assert auditoria.memoria_equipo(db, m, "ZZZ", "X", art) is None
    assert auditoria.memoria_equipo(db, m, "AAA", "Equipo Inexistente", art) is None


def test_la_fiabilidad_es_baja_con_pocos_partidos(db, modelo_con_memoria):
    m, art, equipo = modelo_con_memoria
    art["ligas"]["AAA"]["estado"]["n"][equipo] = 3
    assert auditoria.memoria_equipo(db, m, "AAA", equipo, art)["fiabilidad"] == "baja"


def test_el_endpoint_de_memoria_y_los_de_auditoria(db, modelo_con_memoria, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.db.session import get_db
    from backend.api.main import app
    from backend.api.routers.ml_modelo import requerir_admin

    m, _, equipo = modelo_con_memoria
    estado_vivo.limpiar_cache()
    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        c = TestClient(app)
        ok = c.get(f"/api/v1/ml/equipo/AAA/{equipo}")
        assert ok.status_code == 200 and ok.json()["equipo"] == equipo and ok.json()["contrato"] == "ml-1"
        assert c.get("/api/v1/ml/equipo/AAA/Inexistente").status_code == 404
        assert c.get("/api/v1/ml/errores").status_code in (401, 403, 422)   # sin credenciales de administrador no entrega nada
        assert c.get("/api/v1/ml/cadena").status_code in (401, 403, 422)
        app.dependency_overrides[requerir_admin] = lambda: {"rol": "admin"}
        assert c.get("/api/v1/ml/cadena").json()["ok"] is True
        assert c.get("/api/v1/ml/errores").json()["n"] == 0
    finally:
        app.dependency_overrides.clear()


def test_sin_modelo_activo_la_memoria_por_equipo_dice_404_y_no_5xx(db):
    from fastapi.testclient import TestClient

    from backend.api.db.session import get_db
    from backend.api.main import app

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        r = TestClient(app).get("/api/v1/ml/equipo/E0/Arsenal")
        assert r.status_code == 404 and "no hay un modelo" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
