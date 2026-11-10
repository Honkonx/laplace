"""test_scheduler.py — routers/scheduler.py: disparo manual de WF-D/WF-E + healthcheck.

Cubre el hallazgo CRÍTICO de la auditoría 2026-09-09: `POST /resultados` y `POST /top-picks`
no tenían NINGUNA protección (cualquiera con la URL podía forzar una publicación real al canal
de Telegram o gastar cuota de API). Ahora exigen `Depends(requerir_admin)` a nivel de router,
igual que `routers/admin.py` (mismo patrón de fixture que `test_admin.py`). También cubre
`GET /status` (nuevo) y que cada disparo (manual o simulando el cron) deja un rastro real en
`scheduler_runs` (`db/scheduler_repo.py`)."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.rate_limit import limiter
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.routers import scheduler as scheduler_router
import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)


@pytest.fixture()
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.state.http_client = httpx.AsyncClient()
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token_admin(client) -> str:
    client.post("/api/v1/auth/registro", json={"username": "elAdminSched", "password": "claveAdmin1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    r_login = client.post("/api/v1/auth/login", json={"username": "elAdminSched", "password": "claveAdmin1"})
    token = r_login.json()["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    from backend.api.db import usuarios_repo

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        # rol separado de plan desde 2026-09-10 (ver models/usuarios.py §v7 y
        # test_admin.py::_token_admin) — `requerir_admin` ya no mira `plan`.
        usuarios_repo.asignar_rol(db, me["device_id"], "admin")
    finally:
        db.close()

    # Mismo motivo que test_admin.py::_token_admin: el JWT ya emitido trae el rol viejo en el
    # payload, hay que loguear de nuevo para que `requerir_admin` vea `rol: "admin"`.
    r_login2 = client.post("/api/v1/auth/login", json={"username": "elAdminSched", "password": "claveAdmin1"})
    return r_login2.json()["token"]


def _token_no_admin(client) -> str:
    r = client.post("/api/v1/auth/registro", json={"username": "usuarioSchedNormal", "password": "claveNormal1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    return r.json()["token"]


ENDPOINTS_POST = ["/api/v1/resultados/verificar", "/api/v1/scheduler/resultados", "/api/v1/scheduler/top-picks", "/api/v1/scheduler/laplace-agents", "/api/v1/scheduler/refresco-cuotas"]
ENDPOINTS_GET = ["/api/v1/scheduler/status"]


@pytest.mark.parametrize("endpoint", ENDPOINTS_POST)
def test_post_sin_token_da_401_o_422(client, endpoint):
    # Igual que test_admin.py: Header(...) requerido por FastAPI -> 422 si falta el header por
    # completo, antes de que `obtener_usuario_actual` corra y de el 401 real.
    r = client.post(endpoint)
    assert r.status_code in (401, 422)


@pytest.mark.parametrize("endpoint", ENDPOINTS_GET)
def test_get_sin_token_da_401_o_422(client, endpoint):
    r = client.get(endpoint)
    assert r.status_code in (401, 422)


@pytest.mark.parametrize("endpoint", ENDPOINTS_POST)
def test_post_sin_ser_admin_da_403(client, endpoint):
    token = _token_no_admin(client)
    r = client.post(endpoint, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS_GET)
def test_get_sin_ser_admin_da_403(client, endpoint):
    token = _token_no_admin(client)
    r = client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_disparar_resultados_exitoso_devuelve_datos_y_registra_run(client, monkeypatch):
    async def _fake_ejecutar_ciclo(db, http_client):
        return {"sin_pendientes": True}

    monkeypatch.setattr(scheduler_router.resultados_scheduler, "ejecutar_ciclo_resultados", _fake_ejecutar_ciclo)

    token = _token_admin(client)
    r = client.post("/api/v1/scheduler/resultados", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"sin_pendientes": True}

    r_status = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    assert r_status.status_code == 200
    jobs = r_status.json()["jobs"]
    assert jobs["wfe_resultados"]["ultimo_exitoso_en"] is not None
    assert jobs["wfe_resultados"]["ultima_corrida_ok"] is True
    # El otro job todavía no corrió en esta BD de test.
    assert jobs["wfd_top_picks"]["ultimo_exitoso_en"] is None


def test_disparar_resultados_con_error_propaga_y_registra_run_fallido(client, monkeypatch):
    async def _fake_ejecutar_ciclo_falla(db, http_client):
        raise RuntimeError("fallo simulado de red")

    monkeypatch.setattr(scheduler_router.resultados_scheduler, "ejecutar_ciclo_resultados", _fake_ejecutar_ciclo_falla)

    token = _token_admin(client)
    with pytest.raises(RuntimeError):
        client.post("/api/v1/scheduler/resultados", headers={"Authorization": f"Bearer {token}"})

    r_status = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    jobs = r_status.json()["jobs"]
    assert jobs["wfe_resultados"]["ultimo_exitoso_en"] is None  # nunca tuvo éxito
    assert jobs["wfe_resultados"]["ultima_corrida_ok"] is False
    assert jobs["wfe_resultados"]["ultima_corrida_en"] is not None  # sí quedó rastro del intento


def test_disparar_top_picks_exitoso_publica_por_default(client, monkeypatch):
    llamadas = {"publicado": False}

    async def _fake_generar(db, http_client):
        return {"sin_candidatos": False, "baja_confianza": False, "picks": []}

    async def _fake_publicar(db, http_client, resultado):
        llamadas["publicado"] = True
        return True

    monkeypatch.setattr(scheduler_router.top_picks, "generar_top_picks_dia", _fake_generar)
    monkeypatch.setattr(scheduler_router.top_picks, "publicar_top_picks", _fake_publicar)

    token = _token_admin(client)
    r = client.post("/api/v1/scheduler/top-picks", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["publicado"] is True
    assert llamadas["publicado"] is True

    r_status = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    assert r_status.json()["jobs"]["wfd_top_picks"]["ultimo_exitoso_en"] is not None


def test_disparar_top_picks_publicar_false_no_publica(client, monkeypatch):
    async def _fake_generar(db, http_client):
        return {"sin_candidatos": False, "baja_confianza": False, "picks": []}

    async def _fake_publicar_no_debe_llamarse(db, http_client, resultado):
        raise AssertionError("no debería publicar cuando publicar=false")

    monkeypatch.setattr(scheduler_router.top_picks, "generar_top_picks_dia", _fake_generar)
    monkeypatch.setattr(scheduler_router.top_picks, "publicar_top_picks", _fake_publicar_no_debe_llamarse)

    token = _token_admin(client)
    r = client.post(
        "/api/v1/scheduler/top-picks", params={"publicar": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "publicado" not in r.json()


def test_status_sin_ninguna_corrida_devuelve_todo_none(client):
    token = _token_admin(client)
    r = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["scheduler_corriendo"] is False  # lifespan de APScheduler no corre bajo TestClient sin "with"
    for job in ("wfd_top_picks", "wfe_resultados", "laplace_agents_autoeval", "refresco_cuotas"):
        estado = body["jobs"][job]
        assert estado["ultimo_exitoso_en"] is None
        assert estado["ultima_corrida_en"] is None
        assert estado["ultima_corrida_ok"] is None
        assert estado["estado"] == "nunca"
        assert estado["atrasado"] is True


def test_disparar_laplace_agents_exitoso_registra_run(client, monkeypatch):
    async def _fake_ciclo(db, http_client, fecha=None):
        return {"fecha": "2026-09-09", "fuente_fixtures": "test", "candidatos_liga_conocida": 3,
                "ya_existian": 1, "nuevos_capados_a": 2, "analizados": 2, "errores": 0, "detalle": []}

    monkeypatch.setattr(scheduler_router.laplace_agents, "ejecutar_ciclo_autoevaluacion", _fake_ciclo)

    token = _token_admin(client)
    r = client.post("/api/v1/scheduler/laplace-agents", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["analizados"] == 2

    r_status = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    assert r_status.json()["jobs"]["laplace_agents_autoeval"]["ultimo_exitoso_en"] is not None


def test_disparar_laplace_agents_con_error_propaga_y_registra_run_fallido(client, monkeypatch):
    async def _falla(db, http_client, fecha=None):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(scheduler_router.laplace_agents, "ejecutar_ciclo_autoevaluacion", _falla)

    token = _token_admin(client)
    with pytest.raises(RuntimeError):
        client.post("/api/v1/scheduler/laplace-agents", headers={"Authorization": f"Bearer {token}"})

    r_status = client.get("/api/v1/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    body = r_status.json()["jobs"]["laplace_agents_autoeval"]
    assert body["ultima_corrida_ok"] is False
    assert body["ultimo_exitoso_en"] is None


# NOTA: los tests de `settings.LAPLACE_AGENTS_ACTIVO` (flag que apaga el cron automático de
# `main.py::_job_laplace_agents`) viven en `test_main_scheduler.py`, junto al resto de tests de
# `_job_laplace_agents` — mismo patrón `asyncio.run(...)` que ya usa ese archivo (no hay
# `pytest-asyncio` instalado en este venv, ver `test_laplace_bot.py`). Este endpoint
# (`POST /scheduler/laplace-agents`, disparo manual) ignora ese flag a propósito — ver su
# docstring en `routers/scheduler.py`.


def test_estado_run_detecta_scheduler_atrasado():
    from datetime import datetime
    from backend.api.routers.scheduler import _estado_run

    estado = _estado_run("2026-09-01 00:00:00", 180, ahora=datetime(2026, 9, 1, 4, 0))
    assert estado["atrasado"] is True
    assert estado["estado"] == "atrasado"
