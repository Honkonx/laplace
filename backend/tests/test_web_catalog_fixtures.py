"""Catálogo de partidos de la web: relevancia por id y por nombre base, búsqueda en todas las ligas y
fallback acotado (2026-10-07)."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401
from backend.api.core.rate_limit import limiter
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.models.partidos import PartidoDia
from backend.api.routers import web_catalog

FECHA = "2026-10-07"


def _fila(match_id, liga, local, visitante, codigo=None):
    return PartidoDia(fecha=FECHA, match_id=match_id, liga_slug=liga.lower().replace(" ", "-"), liga_nombre=liga,
                      liga_codigo=codigo, local=local, visitante=visitante, hora_chile="20:00", status="scheduled",
                      cache_invalidado=0, kick_off_utc="2026-10-07T23:00:00Z")


@pytest.fixture()
def sesion():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


@pytest.fixture()
def cliente(sesion):
    app.dependency_overrides[get_db] = lambda: sesion
    app.state.http_client = httpx.AsyncClient()
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_nombre_base_quita_la_fase():
    assert web_catalog._nombre_base("Liga MX: Apertura") == "liga mx"
    assert web_catalog._nombre_base("Primera A: Clausura") == "primera a"


def test_relevancia_por_nombre_base_por_id_y_excluye_juveniles_y_amistosos():
    es = web_catalog._is_priority
    assert es("Liga MX: Apertura") and es("Liga Profesional Argentina") and es("Primera A: Clausura")
    assert es("Nombre raro", "39")  # id canónico de la Premier League
    assert not es("Premier League")  # ambiguo sin id
    assert not es("Friendlies") and not es("Club Friendlies 2026") and not es("Liga MX Femenil: Apertura")
    assert not es("Primera C") and not es("Serie C: Group A")


def test_prioridad_muestra_solo_relevantes_y_busqueda_abre_todas(cliente, sesion):
    sesion.add_all([
        _fila("1", "Liga MX: Apertura", "Club America", "Chivas"),
        _fila("2", "Primera C", "Liniers", "Cañuelas"),
        _fila("3", "Eliteserien", "Brann", "Viking"),
    ])
    sesion.commit()
    relevantes = cliente.get("/api/v1/web/fixtures", params={"date": "20261007"}).json()
    assert [f["home"]["name"] for f in relevantes["fixtures"]] == ["Club America"] and relevantes["scope"] == "priority"
    busqueda = cliente.get("/api/v1/web/fixtures", params={"date": "20261007", "q": "Brann"}).json()
    assert [f["home"]["name"] for f in busqueda["fixtures"]] == ["Brann"]


def test_dia_sin_ligas_relevantes_usa_fallback_acotado_sin_basura(cliente, sesion):
    sesion.add_all([_fila(str(i), "Eliteserien", f"L{i}", f"V{i}") for i in range(40)]
                   + [_fila("f1", "Friendlies", "A", "B"), _fila("f2", "Liga X Women", "C", "D")])
    sesion.commit()
    r = cliente.get("/api/v1/web/fixtures", params={"date": "20261007", "limit": 100}).json()
    assert r["scope"] == "fallback" and r["total"] == web_catalog.FALLBACK_MAX
    nombres = {f["league"]["name"] for f in r["fixtures"]}
    assert nombres == {"Eliteserien"}  # sin amistosos ni femenino
