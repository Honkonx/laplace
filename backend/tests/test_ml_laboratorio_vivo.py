"""El laboratorio deja la predicción del modelo con el partido real y la evaluación en vivo mide al modelo activo contra los resultados."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base
from backend.api.ml.laplace import entrenamiento, pronostico, registro, servicio, simulacion
from backend.api.models.ml_modelo import MlEvaluacion, MlPrediccion
from backend.api.models.partidos import ResultadoPartido
from backend.api.services import laboratorio_pronosticos as lab


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    lab.asegurar_experimentos_base(s)
    s.commit()
    yield s
    s.close()


def _salida(id_=7):
    return {"ok": True, "degradado": False, "modelo": {"id": id_, "version": "v1"}, **pronostico.pronosticar(1.6, 1.1)}


def _comun(pid="fx1"):
    return dict(partido_id=pid, fecha_partido="2999-01-01", local="A", visitante="B", liga="L", hora_kickoff="2999-01-01T20:00:00", datos={})


def test_el_laboratorio_guarda_la_prediccion_con_el_partido_id_real_sin_confirmar_por_su_cuenta(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida())
    lab.registrar_modelo_laplace(db, **_comun())
    # sin commit propio: la fila existe en la transacción del laboratorio y se revierte con ella
    assert db.scalars(select(MlPrediccion)).one().partido_id == "fx1"
    db.rollback()
    assert db.scalars(select(MlPrediccion)).all() == []


def test_un_fallo_al_guardar_la_prediccion_no_impide_registrar_el_comparador(db, monkeypatch):
    from backend.api.models.predicciones import PronosticoExperimental

    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida())

    def rompe(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(registro, "registrar_prediccion", rompe)
    lab.registrar_modelo_laplace(db, **_comun())
    db.commit()
    assert db.query(PronosticoExperimental).filter_by(variante="laplace_modelo").count() == 1


def test_la_evaluacion_en_vivo_mide_al_modelo_activo_con_resultados_reales(db):
    ps = simulacion.simular(5, n_equipos=8, temporadas=3)["partidos"]
    mid = registro.registrar_modelo(db, "m", "v", entrenamiento.entrenar(ps, 10**9), None, None)
    for i, p in enumerate(ps[:25]):
        registro.registrar_prediccion(db, mid, {"local": p["local"], "visitante": p["visitante"]}, {"p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}, "laboratorio", 0.0, f"v{i}")
        db.add(ResultadoPartido(fixture_id=f"v{i}", local=p["local"], visitante=p["visitante"], goles_local=p["gl"], goles_visitante=p["gv"], fecha_partido="2999-01-01", actualizado_en="x"))
    db.commit()
    assert registro.evaluar_sombra(db, mid, "vivo")["propio"]["n"] == 25
    assert db.scalars(select(MlEvaluacion).where(MlEvaluacion.origen == "vivo")).one().n == 25
    assert db.scalars(select(MlEvaluacion).where(MlEvaluacion.origen == "sombra")).all() == []
