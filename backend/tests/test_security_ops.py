"""test_security_ops.py — rate limiting, CORS y logging estructurado, agregados 2026-09-08
(ronda de seguridad/operaciones sobre backend/api/). Ver:
- backend/api/core/rate_limit.py (límite elegido y por qué)
- backend/api/core/config.py (CORS_ORIGINS)
- backend/api/core/logging_config.py (JsonFormatter)
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.config import settings
from backend.api.core.logging_config import JsonFormatter, configurar_logging
from backend.api.core.rate_limit import limiter
from backend.api.db.session import Base, get_db
from backend.api.main import app
import backend.api.models  # noqa: F401


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
    limiter.reset()  # cada test arranca con el contador de rate limit en cero
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Rate limiting -----------------------------------------------------------------------

def test_login_quinto_intento_en_el_minuto_no_da_429(client):
    """El límite es 5/minuto — los primeros 5 intentos (fallidos, usuario no existe) deben
    devolver 401 normal, nunca 429."""
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "noexiste", "password": "x"})
        assert r.status_code == 401


def test_login_sexto_intento_en_el_minuto_da_429(client):
    """El 6to intento dentro del mismo minuto, misma IP, debe ser bloqueado por slowapi."""
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "noexiste", "password": "x"})
    r = client.post("/api/v1/auth/login", json={"username": "noexiste", "password": "x"})
    assert r.status_code == 429


def test_registro_sexto_intento_en_el_minuto_da_429(client):
    """Mismo límite aplica a /registro (protección contra spam de cuentas)."""
    for i in range(5):
        client.post("/api/v1/auth/registro", json={"username": f"userlim{i}", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    r = client.post("/api/v1/auth/registro", json={"username": "userlim99", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    assert r.status_code == 429


def test_rate_limit_es_por_endpoint_no_global(client):
    """Agotar el límite de /login no debería bloquear /registro (buckets separados por ruta,
    comportamiento default de slowapi con `key_func` sin `scope` compartido)."""
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "noexiste", "password": "x"})
    r = client.post("/api/v1/auth/registro", json={"username": "otroendpoint", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    assert r.status_code != 429


# --- CORS ----------------------------------------------------------------------------------

def test_cors_header_presente_para_origen_permitido(client):
    """conftest.py fija CORS_ORIGINS=http://localhost:4321 antes de importar la app — un
    origen en esa lista debe recibir el header Access-Control-Allow-Origin."""
    assert "http://localhost:4321" in settings.cors_origins_list
    r = client.get("/api/v1/health", headers={"Origin": "http://localhost:4321"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:4321"


def test_cors_header_ausente_para_origen_no_permitido(client):
    """Un origen que NO está en CORS_ORIGINS no debe recibir el header — el browser del
    atacante bloquea la lectura de la respuesta del lado cliente."""
    r = client.get("/api/v1/health", headers={"Origin": "https://sitio-no-autorizado.com"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


def test_cors_origins_list_nunca_incluye_wildcard_con_credentials():
    """Guarda de regresión — CORS_ORIGINS nunca debe configurarse como '*' en este proyecto,
    porque main.py siempre agrega allow_credentials=True junto con la lista."""
    assert "*" not in settings.cors_origins_list


# --- Logging estructurado ------------------------------------------------------------------

def test_json_formatter_produce_json_valido_con_campos_esperados():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="laplace.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="mensaje de prueba %s", args=("con formato",), exc_info=None,
    )
    linea = formatter.format(record)
    payload = json.loads(linea)  # debe parsear sin error — es la garantía real de "es JSON"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "laplace.test"
    assert payload["message"] == "mensaje de prueba con formato"
    assert "timestamp" in payload


def test_json_formatter_incluye_campos_extra():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="laplace.test", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="evento con contexto", args=(), exc_info=None,
    )
    record.device_id = "abc-123"
    payload = json.loads(formatter.format(record))
    assert payload["device_id"] == "abc-123"


def test_configurar_logging_es_idempotente():
    """Llamar configurar_logging() dos veces no debe duplicar handlers — si no fuera
    idempotente, cada línea de log real aparecería repetida N veces."""
    configurar_logging()
    configurar_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
