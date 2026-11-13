"""MP-12: alerta de deriva de lo que el modelo produce. PSI puro, la comparación entre ventanas sobre una base de las migraciones reales, la alarma que salta con un conjunto desplazado y no con el normal,
el trabajo diario y el endpoint (solo administradores)."""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta

import pytest

from backend.api.ml.laplace import deriva, registro
from backend.api.models.ml_modelo import MlModelo, MlPrediccion

AHORA = datetime(2026, 11, 20, 12, 0, 0)


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


def _modelo(db, estado="activo"):
    m = MlModelo(nombre="m", version=f"v{random.random()}", familia="x", tarea="1x2", estado=estado, creado_en="2026-11-01T00:00:00")
    db.add(m)
    db.commit()
    return m


def _predicciones(db, modelo_id, n, dias_atras_min, dias_atras_max, centro=0.45, semilla=1):
    rng = random.Random(semilla)
    for i in range(n):
        local = min(max(rng.gauss(centro, 0.12), 0.05), 0.9)
        empate = (1 - local) * 0.4
        db.add(MlPrediccion(modelo_id=modelo_id, partido_id=f"p{modelo_id}-{semilla}-{i}", entrada_json="{}", probabilidades_json=json.dumps({"local": local, "empate": empate, "visitante": 1 - local - empate}),
                            canal="http", creada_en=(AHORA - timedelta(days=rng.uniform(dias_atras_min, dias_atras_max))).strftime("%Y-%m-%dT%H:%M:%S")))
    db.commit()


def test_el_psi_es_cero_con_la_misma_distribucion_y_grande_con_una_desplazada():
    rng = random.Random(3)
    a = [rng.gauss(0, 1) for _ in range(2000)]
    b = [rng.gauss(0, 1) for _ in range(2000)]
    assert deriva.psi(a, a) == pytest.approx(0.0, abs=1e-9)
    assert deriva.psi(a, b) < 0.05
    assert deriva.psi(a, [x + 1.5 for x in b]) > 0.5
    with pytest.raises(ValueError):
        deriva.psi([], [1.0])


def test_las_variables_se_comparan_por_columna_y_la_peor_manda():
    rng = random.Random(4)
    ref = {"elo": [rng.gauss(1500, 100) for _ in range(1500)], "forma": [rng.gauss(1.5, 0.4) for _ in range(1500)]}
    nuevo = {"elo": [rng.gauss(1500, 100) for _ in range(1500)], "forma": [rng.gauss(2.4, 0.4) for _ in range(1500)]}
    r = deriva.deriva_de_variables(ref, nuevo)
    assert r["alarma"] is True and r["peor"] == "forma" and r["psi"]["elo"] < 0.1 < r["psi"]["forma"]
    assert deriva.deriva_de_variables(ref, ref)["alarma"] is False


def test_con_el_mismo_comportamiento_no_hay_alarma(db):
    m = _modelo(db)
    _predicciones(db, m.id, 300, 31, 150, semilla=1)           # referencia
    _predicciones(db, m.id, 120, 0, 29, semilla=2)             # reciente, misma distribución
    r = deriva.deriva_de_salidas(db, m.id, AHORA)
    assert r["alarma"] is False and r["motivo"] == "estable" and max(r["psi"].values()) < 0.25 and r["n_referencia"] == 300 and r["n_reciente"] == 120


def test_con_un_cambio_de_comportamiento_la_alarma_salta_y_dice_cual(db):
    m = _modelo(db)
    _predicciones(db, m.id, 300, 31, 150, centro=0.45, semilla=1)
    _predicciones(db, m.id, 120, 0, 29, centro=0.70, semilla=2)      # el modelo de pronto da muchísimo más al local
    r = deriva.deriva_de_salidas(db, m.id, AHORA)
    assert r["alarma"] is True and r["psi"][r["peor"]] > 0.25 and "cambió de distribución" in r["motivo"]


def test_sin_pronosticos_suficientes_no_dice_nada_en_vez_de_dispararse_con_ruido(db):
    m = _modelo(db)
    _predicciones(db, m.id, 30, 31, 150)
    _predicciones(db, m.id, 20, 0, 29, centro=0.8, semilla=2)
    r = deriva.deriva_de_salidas(db, m.id, AHORA)
    assert r["alarma"] is False and r["psi"] == {} and "sin pronósticos suficientes" in r["motivo"]


def test_otro_modelo_no_mezcla_sus_pronosticos(db):
    a, b = _modelo(db), _modelo(db, "sombra")
    _predicciones(db, a.id, 300, 31, 150, semilla=1)
    _predicciones(db, a.id, 120, 0, 29, semilla=2)
    _predicciones(db, b.id, 120, 0, 29, centro=0.9, semilla=3)
    assert deriva.deriva_de_salidas(db, a.id, AHORA)["alarma"] is False


def test_las_filas_rotas_se_ignoran(db):
    m = _modelo(db)
    _predicciones(db, m.id, 100, 31, 150)
    _predicciones(db, m.id, 100, 0, 29, semilla=2)
    db.add(MlPrediccion(modelo_id=m.id, partido_id="x", entrada_json="{}", probabilidades_json="no es json", canal="http", creada_en=(AHORA - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")))
    db.commit()
    assert deriva.deriva_de_salidas(db, m.id, AHORA)["n_reciente"] == 100


def test_el_endpoint_es_solo_de_administradores_y_funciona_sin_modelo(db):
    from fastapi.testclient import TestClient

    from backend.api.db.session import get_db
    from backend.api.main import app
    from backend.api.routers.ml_modelo import requerir_admin

    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        c = TestClient(app)
        assert c.get("/api/v1/ml/deriva").status_code in (401, 403, 422)
        app.dependency_overrides[requerir_admin] = lambda: {"rol": "admin"}
        assert c.get("/api/v1/ml/deriva").json()["motivo"] == "no hay un modelo activo"
        m = _modelo(db)
        assert c.get("/api/v1/ml/deriva").json()["modelo_id"] == m.id
    finally:
        app.dependency_overrides.clear()


def test_el_trabajo_diario_anota_la_deriva_y_alerta_si_salta(db, monkeypatch):
    from backend.api.db import scheduler_repo
    from backend.api.ml.laplace import jobs
    from backend.api.services import alerting, laboratorio_pronosticos

    m = _modelo(db)
    _predicciones(db, m.id, 300, 31, 150, centro=0.45, semilla=1)
    _predicciones(db, m.id, 120, 0, 29, centro=0.70, semilla=2)
    original = deriva.deriva_de_salidas
    monkeypatch.setattr(deriva, "deriva_de_salidas", lambda d, mid, ahora=None, umbral=deriva.UMBRAL_ALARMA: original(d, mid, AHORA, umbral))
    alertas, runs = [], []
    monkeypatch.setattr(alerting, "emitir_alerta", lambda tipo, datos: alertas.append(tipo))
    monkeypatch.setattr(laboratorio_pronosticos, "registrar_proximos", lambda d: {"registrados": 0, "candidatos": 0})
    monkeypatch.setattr(laboratorio_pronosticos, "comparar_en_vivo", lambda d: {"evaluados": 0})
    monkeypatch.setattr(registro, "evaluar_sombra", lambda d, mid, o: None)
    monkeypatch.setattr(scheduler_repo, "registrar_run", lambda d, job, ok, detalle: runs.append(detalle))
    monkeypatch.setattr(scheduler_repo, "ultimo_run", lambda d, job: None)
    asyncio.run(jobs.evaluar_modelo_diario(lambda: db))
    assert "modelo_laplace_deriva" in alertas and any("DERIVA" in r for r in runs)
