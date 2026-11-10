"""test_prediccion_web.py — endpoint público POST /api/v1/prediccion-web, usado por frontend/
(React+Vite). Mockea el enriquecimiento (standings/odds/H2H reales) para que el test sea
hermético — el motor Poisson en sí ya tiene su propia suite (test_pronostico.py/test_motor.py)."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base, get_db
from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.main import app
from backend.api.routers import prediccion_web as prediccion_web_router
import backend.api.models  # noqa: F401


@pytest.fixture()
def client(monkeypatch):
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
    app.dependency_overrides[obtener_usuario_actual] = lambda: {"sub": "test-user", "rol": "user"}
    app.state.http_client = httpx.AsyncClient()

    async def _enriquecer_fake(db, client, partido, match_id, fecha):
        return {
            "local": partido["local"], "visitante": partido["visitante"], "liga": partido["liga"],
            "partido": f"{partido['local']} vs {partido['visitante']}", "partido_id": match_id,
            "pos_local": 3, "pos_visit": 8, "forma_local_wins": 4, "forma_visit_wins": 2,
            "standings_info": "LOCAL pos3 | VISITANTE pos8",
            "odds_local": 1.8, "odds_empate": 3.4, "odds_visit": 4.2, "odds_disponibles": True,
            "odds_info": "River @1.8 | Empate @3.4 | Boca @4.2",
            "goles_local_avg": 1.6, "goles_visit_avg": 1.1,
            "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.4,
            "liga_goles_avg": 2.5,
            "h2h_local_wins": 3, "h2h_visit_wins": 1, "h2h_empates": 1, "h2h_total": 5,
            "h2h_disponible": True, "h2h_resumen": "River gana el historial reciente",
            "total_h2h": 5,
            # El motor no debe ejecutar ni presentar Poisson como un análisis válido si
            # los datos fueron valores de respaldo. Este fixture representa tres fuentes
            # reales, igual que una respuesta completa del enriquecedor de producción.
            "calidad_datos": {
                "eligible": True, "tier": "completa", "sources": ["tabla", "odds", "h2h"],
                "source_count": 3, "reason": None,
            },
        }

    monkeypatch.setattr(prediccion_web_router, "_enriquecer_partido", _enriquecer_fake)

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_prediccion_web_devuelve_analisis_real(client):
    r = client.post("/api/v1/prediccion-web", json={
        "match_id": "12345", "local": "River Plate", "visitante": "Boca Juniors",
        "liga": "Liga Profesional", "fecha": "20260101",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["local"] == "River Plate"
    assert body["visitante"] == "Boca Juniors"
    assert "modulos" in body and "poisson" in body["modulos"]
    assert body["modulos"]["poisson"]["ok"] is True
    assert "consenso" in body
    assert body["standings_info"] == "LOCAL pos3 | VISITANTE pos8"
    assert body["odds_info"].startswith("River @1.8")
    assert body["h2h_resumen"] == "River gana el historial reciente"
    assert "resumen_estadistico" in body


def test_prediccion_web_body_invalido_da_422(client):
    r = client.post("/api/v1/prediccion-web", json={"match_id": "12345"})
    assert r.status_code == 422
