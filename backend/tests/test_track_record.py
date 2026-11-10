"""test_track_record.py — `GET /api/v1/track-record`, router PÚBLICO (sin auth, a diferencia
de `/api/v1/admin/calibracion`). Mismo patrón de fixture (`TestClient` + BD en memoria) que
`test_admin.py`."""
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


def test_track_record_no_requiere_autenticacion(client):
    r = client.get("/api/v1/track-record")
    assert r.status_code == 200


def test_track_record_devuelve_estructura_honesta_con_bd_vacia(client):
    r = client.get("/api/v1/track-record")
    data = r.json()

    assert data["volumen_real"]["total_filas_analisis_comparativo"] == 0
    assert data["pick_final"]["confiable"] is False
    assert data["brier_score"]["muestra"] == 0
    assert data["rps"]["muestra"] == 0
    assert "metodologia" in data
    assert data["advertencia_general"]


def test_track_record_no_esta_bajo_prefix_admin(client):
    """Confirma que el endpoint público NO vive bajo `/api/v1/admin/*` (donde sí exigiría
    `requerir_admin`) — es un router separado a propósito."""
    r = client.get("/api/v1/admin/track-record")
    assert r.status_code == 404
