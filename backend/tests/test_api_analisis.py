"""test_api_analisis.py — prueba el endpoint HTTP real (TestClient de FastAPI), reemplazo
del núcleo de la acción 'prediccion'/'check_job' de WF-A2. Usa una BD en memoria (override de
`get_db`) — nunca toca backend/db/bot_deportivo.db real."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base, get_db
from backend.api.main import app
import backend.api.models  # noqa: F401


@pytest.fixture()
def client():
    # StaticPool: una sola conexión compartida — sin esto, cada acceso a
    # "sqlite:///:memory:" abre una BD en memoria NUEVA y vacía (bug real encontrado
    # corriendo esta suite por primera vez: "no such table").
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_check(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_crear_analisis_persiste_y_se_puede_leer(client):
    payload = {
        "local": "Real Madrid", "visitante": "Barcelona", "liga": "La Liga",
        "partido_id": "clasico_test_1",
        "goles_local_avg": 1.8, "goles_visit_avg": 1.2,
        "pos_local": 2, "pos_visit": 1,
        "forma_local_wins": 3, "forma_visit_wins": 4,
        "h2h_local_wins": 4, "h2h_visit_wins": 3, "h2h_empates": 3, "h2h_total": 10,
        "h2h_disponible": True,
        "odds_local": 2.10, "odds_empate": 3.20, "odds_visit": 3.50,
        "odds_disponibles": True,
    }
    r = client.post("/api/v1/analisis", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["partido_id"] == "clasico_test_1"
    assert data["consenso"]["pick_final"] in ("Local", "Empate", "Visitante")

    # Verificación empírica real (no solo "no tiró error"): confirmar que quedó en la BD
    r2 = client.get("/api/v1/analisis/clasico_test_1")
    assert r2.status_code == 200
    leido = r2.json()
    assert leido["ok"] is True
    assert leido["pick_final"] == data["consenso"]["pick_final"]
    assert leido["local"] == "Real Madrid"


def test_leer_analisis_inexistente(client):
    r = client.get("/api/v1/analisis/no-existe-este-partido")
    assert r.status_code == 200
    assert r.json()["ok"] is False
