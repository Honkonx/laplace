"""test_job_reajuste.py — job semanal de reajuste de modelos (`ml/job_reajuste.py`, `main._job_reajustar_modelos`,
`POST /api/v1/scheduler/reajustar-modelos`). Los subprocesos se simulan: nunca se ejecuta el reajuste real."""
from __future__ import annotations

import asyncio
import inspect
import json
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api import main
from backend.api.db import scheduler_repo
from backend.api.db.session import Base
from backend.api.ml import job_reajuste
from backend.api.routers import scheduler as scheduler_router
from test_scheduler import _token_admin, client  # noqa: F401  (fixture y helper del router de scheduler)

RESUMEN_OK = {"reemplazado": False, "ligas_reajustadas": ["COL1"], "motivo": "datos en vivo insuficientes para validar: 1 partidos evaluables (< 100)"}


class Corrida:
    """Sustituto de subprocess.run: responde según el comando."""

    def __init__(self, tiene_numpy=True, rc=0, salida=None, error=None):
        self.llamadas, self.tiene_numpy, self.rc, self.salida, self.error = [], tiene_numpy, rc, salida, error

    def __call__(self, cmd, **kw):
        self.llamadas.append((cmd, kw))
        if self.error:
            raise self.error
        if cmd[1] == "-c":
            return subprocess.CompletedProcess(cmd, 0 if self.tiene_numpy else 1, "", "ModuleNotFoundError")
        return subprocess.CompletedProcess(cmd, self.rc, self.salida if self.salida is not None else "texto previo\n" + json.dumps(RESUMEN_OK), "boom")


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("LAPLACE_PYTHON_ML", "python-simulado")
    monkeypatch.delenv("LAPLACE_REAJUSTE_AUTOMATICO", raising=False)


def test_ejecuta_exportar_y_reajustar_en_un_subproceso_y_resume():
    corrida = Corrida()
    r = job_reajuste.ejecutar_reajuste(ejecutar=corrida)
    assert r["ok"] is True and r["reemplazado"] is False and r["detalle"].startswith("sin reemplazo:")
    cmd = corrida.llamadas[-1][0]
    assert cmd[0] == "python-simulado" and cmd[2:] == ["--exportar", "--aplicar", "--json"]
    assert corrida.llamadas[-1][1]["timeout"] == job_reajuste.TIMEOUT_SEGUNDOS


def test_reemplazo_efectivo_se_informa():
    salida = json.dumps({"reemplazado": True, "ligas_reajustadas": ["COL1", "KOR1"], "motivo": "validado: ..."})
    r = job_reajuste.ejecutar_reajuste(ejecutar=Corrida(salida=salida))
    assert r["ok"] and r["reemplazado"] and "2 ligas" in r["detalle"]


def test_sin_numpy_degrada_con_ok_false_y_motivo_claro():
    corrida = Corrida(tiene_numpy=False)
    r = job_reajuste.ejecutar_reajuste(ejecutar=corrida)
    assert r["ok"] is False and "numpy/scipy" in r["detalle"] and "LAPLACE_PYTHON_ML" in r["detalle"]
    assert len(corrida.llamadas) == 1  # ni siquiera lanza el reajuste


@pytest.mark.parametrize("corrida,esperado", [
    (Corrida(rc=2), "codigo 2"),
    (Corrida(salida="sin json"), "JSON"),
    (Corrida(error=subprocess.TimeoutExpired("x", 1)), "excedio"),
    (Corrida(error=FileNotFoundError()), "no se pudo lanzar"),
])
def test_fallos_del_subproceso_nunca_lanzan(corrida, esperado):
    r = job_reajuste.ejecutar_reajuste(ejecutar=corrida)
    assert r["ok"] is False and esperado in r["detalle"]


def test_sin_interprete_o_sin_script(monkeypatch, tmp_path):
    monkeypatch.delenv("LAPLACE_PYTHON_ML")
    monkeypatch.setattr(job_reajuste.shutil, "which", lambda _: None)
    assert "sin Python" in job_reajuste.ejecutar_reajuste(ejecutar=Corrida())["detalle"]
    monkeypatch.setenv("LAPLACE_PYTHON_ML", "p")
    assert "no existe" in job_reajuste.ejecutar_reajuste(ejecutar=Corrida(), script=tmp_path / "no.py")["detalle"]


@pytest.mark.parametrize("valor,activo", [(None, True), ("1", True), ("true", True), ("0", False), ("false", False), ("off", False), ("", False)])
def test_variable_de_activacion(monkeypatch, valor, activo):
    if valor is not None:
        monkeypatch.setenv("LAPLACE_REAJUSTE_AUTOMATICO", valor)
    assert job_reajuste.reajuste_activo() is activo


def _sesion(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(main, "SessionLocal", fabrica)
    return fabrica


def test_job_registra_la_corrida(monkeypatch):
    fabrica = _sesion(monkeypatch)
    monkeypatch.setattr(job_reajuste, "ejecutar_reajuste", lambda: {"ok": True, "reemplazado": False, "detalle": "sin reemplazo: x"})
    asyncio.run(main._job_reajustar_modelos())
    with fabrica() as db:
        run = scheduler_repo.ultimo_run(db, scheduler_router.JOB_REAJUSTE_MODELOS)
        assert run.ok is True and run.detalle == "sin reemplazo: x"


def test_job_con_ok_false_y_con_excepcion_no_rompe(monkeypatch):
    fabrica = _sesion(monkeypatch)
    monkeypatch.setattr(job_reajuste, "ejecutar_reajuste", lambda: {"ok": False, "reemplazado": False, "detalle": "sin numpy"})
    asyncio.run(main._job_reajustar_modelos())

    def explota():
        raise RuntimeError("inesperado")

    monkeypatch.setattr(job_reajuste, "ejecutar_reajuste", explota)
    asyncio.run(main._job_reajustar_modelos())  # no propaga
    with fabrica() as db:
        runs = db.query(scheduler_repo.SchedulerRun).order_by(scheduler_repo.SchedulerRun.id).all()
        assert [r.ok for r in runs] == [False, False] and runs[1].detalle == "excepcion inesperada"


def test_job_desactivado_no_ejecuta_ni_registra(monkeypatch):
    fabrica = _sesion(monkeypatch)
    monkeypatch.setenv("LAPLACE_REAJUSTE_AUTOMATICO", "0")
    monkeypatch.setattr(job_reajuste, "ejecutar_reajuste", lambda: pytest.fail("no debe ejecutarse"))
    asyncio.run(main._job_reajustar_modelos())
    with fabrica() as db:
        assert scheduler_repo.ultimo_run(db, scheduler_router.JOB_REAJUSTE_MODELOS) is None


def test_el_lifespan_agenda_el_job_el_domingo_de_madrugada():
    fuente = inspect.getsource(main.lifespan)
    assert 'id="reajuste_modelos"' in fuente
    linea = next(ln for ln in fuente.splitlines() if 'id="reajuste_modelos"' in ln)
    assert "_job_reajustar_modelos" in linea and 'day_of_week="sun"' in linea and "hour=3" in linea and "TZ_CHILE" in linea


def test_status_lista_el_job_con_su_ventana_y_el_disparo_manual_lo_registra(client, monkeypatch):  # noqa: F811
    token = _token_admin(client)
    cab = {"Authorization": f"Bearer {token}"}
    estado = client.get("/api/v1/scheduler/status", headers=cab).json()["jobs"]["reajuste_modelos"]
    assert estado["ventana_minutos"] == 11_520 and estado["estado"] == "nunca"

    monkeypatch.setattr(job_reajuste, "ejecutar_reajuste", lambda: {"ok": True, "reemplazado": False, "detalle": "sin reemplazo: x"})
    r = client.post("/api/v1/scheduler/reajustar-modelos", headers=cab)
    assert r.status_code == 200 and r.json()["ok"] is True
    estado = client.get("/api/v1/scheduler/status", headers=cab).json()["jobs"]["reajuste_modelos"]
    assert estado["estado"] == "al_dia" and estado["ultima_corrida_ok"] is True

    monkeypatch.setenv("LAPLACE_REAJUSTE_AUTOMATICO", "0")
    apagado = client.get("/api/v1/scheduler/status", headers=cab).json()["jobs"]["reajuste_modelos"]
    assert apagado["estado"] == "desactivado" and apagado["atrasado"] is False


def test_disparo_manual_exige_admin(client):  # noqa: F811
    assert client.post("/api/v1/scheduler/reajustar-modelos").status_code in (401, 422)
