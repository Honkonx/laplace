"""Trabajos programados del modelo Laplace: evaluación diaria con aviso al cruzar los umbrales de evidencia y reentreno semanal."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import main
from backend.api.db import scheduler_repo
from backend.api.db.session import Base
from backend.api.ml.laplace import job_reentreno, registro
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.routers.scheduler import JOB_MODELO_LAPLACE, JOB_REENTRENO_LAPLACE


@pytest.fixture()
def sesion(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "SessionLocal", fabrica)
    return fabrica


@pytest.fixture()
def alertas(monkeypatch):
    emitidas = []
    from backend.api.services import alerting

    monkeypatch.setattr(alerting, "emitir_alerta", lambda evento, detalle: emitidas.append((evento, detalle)) or True)
    return emitidas


def _evaluados(fabrica, n):
    with fabrica() as db:
        for i in range(n):
            db.add(PronosticoExperimental(experimento_codigo="laplace_modelo", partido_id=f"p{i}", fecha_partido="2026-11-10", local="A", visitante="B", fuente="laplace",
                                          variante="laplace_modelo", corte_datos_en="2026-11-10T00:00:00", creado_en="x", resultado_real="1-0", log_loss=1.0, rps=0.2))
        db.commit()


def _ultimo(fabrica, job):
    with fabrica() as db:
        return scheduler_repo.ultimo_run(db, job)


def test_sin_modelos_ni_observaciones_registra_cero_y_no_avisa(sesion, alertas):
    asyncio.run(main._job_modelo_laplace())
    run = _ultimo(sesion, JOB_MODELO_LAPLACE)
    assert run.ok and "lab=0" in run.detalle and alertas == []


def test_avisa_una_sola_vez_al_cruzar_el_umbral_exploratorio(sesion, alertas):
    with sesion() as db:
        scheduler_repo.registrar_run(db, JOB_MODELO_LAPLACE, ok=True, detalle="lab=40")
    _evaluados(sesion, 52)
    asyncio.run(main._job_modelo_laplace())
    assert alertas == [("modelo_laplace_evidencia", {"kind": "exploratoria", "evaluados": 52})]
    assert "lab=52" in _ultimo(sesion, JOB_MODELO_LAPLACE).detalle
    asyncio.run(main._job_modelo_laplace())  # la corrida siguiente ya parte de lab=52: no repite el aviso
    assert len(alertas) == 1


def test_avisa_la_promocion_al_llegar_a_200(sesion, alertas):
    with sesion() as db:
        scheduler_repo.registrar_run(db, JOB_MODELO_LAPLACE, ok=True, detalle="lab=199")
    _evaluados(sesion, 200)
    asyncio.run(main._job_modelo_laplace())
    assert [a[1]["kind"] for a in alertas] == ["promocion"]


def test_un_fallo_inesperado_se_registra_y_no_rompe_el_scheduler(sesion, alertas, monkeypatch):
    def rompe(db):
        raise RuntimeError("x")

    monkeypatch.setattr(registro, "modelo_sombra", rompe)
    asyncio.run(main._job_modelo_laplace())
    run = _ultimo(sesion, JOB_MODELO_LAPLACE)
    assert run.ok is False and run.detalle == "excepcion inesperada"


def test_el_reentreno_registra_el_detalle_del_subproceso(sesion, monkeypatch):
    monkeypatch.setattr(job_reentreno, "reentreno_activo", lambda: True)
    monkeypatch.setattr(job_reentreno, "ejecutar_reentreno", lambda: {"ok": True, "detalle": "promovido por las guardas del reentreno"})
    asyncio.run(main._job_reentreno_laplace())
    run = _ultimo(sesion, JOB_REENTRENO_LAPLACE)
    assert run.ok and "promovido" in run.detalle


def test_el_reentreno_apagado_no_hace_nada(sesion, monkeypatch):
    monkeypatch.setattr(job_reentreno, "reentreno_activo", lambda: False)
    asyncio.run(main._job_reentreno_laplace())
    assert _ultimo(sesion, JOB_REENTRENO_LAPLACE) is None


def test_el_reentreno_con_excepcion_queda_registrado_como_fallo(sesion, monkeypatch):
    def rompe():
        raise RuntimeError("x")

    monkeypatch.setattr(job_reentreno, "reentreno_activo", lambda: True)
    monkeypatch.setattr(job_reentreno, "ejecutar_reentreno", rompe)
    asyncio.run(main._job_reentreno_laplace())
    run = _ultimo(sesion, JOB_REENTRENO_LAPLACE)
    assert run.ok is False and run.detalle == "excepcion inesperada"
