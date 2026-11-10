"""test_app_gateway.py — endpoint HTTP real (reemplazo de WF-A2 completo), mismo contrato
externo (`POST /api/v1/deportivo`, header `x-kairos-key`, body `{action, params, device_id}`)."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.config import settings
from backend.api.db.session import Base, get_db
from backend.api.main import app
import backend.api.models  # noqa: F401

HEADERS = {"x-kairos-key": settings.KAIROS_AUTH_SECRET}


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
    # No se usa `with TestClient(app) as client` a propósito — eso dispararía el lifespan
    # completo (arranque del bot de Telegram con polling real si TELEGRAM_BOT_TOKEN está
    # seteado en el .env real del repo). Se setea `app.state.http_client` a mano, igual que
    # `get_db` se overridea a mano, para mantener el test hermético.
    app.state.http_client = httpx.AsyncClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post(client, action, params=None, device_id="dev1"):
    return client.post("/api/v1/deportivo", headers=HEADERS,
                        json={"action": action, "params": params or {}, "device_id": device_id})


def test_sin_header_devuelve_401(client):
    r = client.post("/api/v1/deportivo", json={"action": "ping"})
    assert r.status_code == 401


def test_ping(client):
    r = _post(client, "ping")
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is True


def test_accion_desconocida_da_404(client):
    # Antes: 200 con body `{"type": "error", ...}` (fallo "silencioso" con status 200). Ahora:
    # 404 real — ver `schemas/app_gateway.py::ACCIONES_CON_PARAMS` y `routers/app_gateway.py`.
    # El body sigue viniendo con `type/title/data` (ahora bajo `detail`, mismo patrón que ya
    # usaba `_verificar_auth` para el 401 antes de esta ronda).
    r = _post(client, "no_existe")
    assert r.status_code == 404
    assert r.json()["detail"]["type"] == "error"


def test_registrar_usuario_y_luego_perfil(client):
    r = _post(client, "registrar_usuario", {"nickname": "Fulanito"})
    body = r.json()
    assert body["data"]["registrado"] is True
    assert body["data"]["plan"] == "free"

    r2 = _post(client, "profile")
    assert r2.json()["data"]["nickname"] == "Fulanito"


def test_activar_codigo_invalido(client):
    r = _post(client, "activar_codigo", {"codigo": "NOEXISTE123"})
    assert r.json()["type"] == "error"


def test_juegos_sin_cache_local_cae_a_cascada_sin_pegar_red_real(client, monkeypatch):
    # Sin caché en partidos_dia, el endpoint cae a gateway.obtener_fixtures_cascada — se
    # mockea para que el test sea hermético (nunca pegarle a BSD/livescore6/api-football
    # reales, aunque el .env del repo tenga API keys reales).
    from backend.api.routers import app_gateway

    async def _cascada_vacia(db, client, fecha):
        return [], "ninguna"

    monkeypatch.setattr(app_gateway.gateway, "obtener_fixtures_cascada", _cascada_vacia)
    r = _post(client, "juegos", {"date": "2026-01-01"})
    assert r.status_code == 200
    assert r.json()["type"] == "button_list"


# ---------------------------------------------------------------------------------------------
# Validación real de `params` por acción (ronda de auditoría 2026-09-09) — un test "feliz" y
# uno de `params` inválido/faltante por cada `action` real, para confirmar que:
# (a) el comportamiento de una llamada válida no cambió, y
# (b) un `params` inválido/faltante ahora corta con un 4xx claro, nunca un 500 ni un 200
#     "silencioso" con `type: error`.
# ---------------------------------------------------------------------------------------------

def _asegura_error_422(r):
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["type"] == "error"
    assert "errors" in body["detail"]["data"]


def test_envelope_params_no_dict_da_422(client):
    # `params` truthy pero no-dict (antes: `body.get("params") or {}` lo dejaba pasar tal
    # cual y cualquier `.get()` posterior sobre un string/list revienta con AttributeError
    # sin capturar → 500). Ahora corta en la validación del sobre exterior.
    r = client.post("/api/v1/deportivo", headers=HEADERS,
                     json={"action": "juegos", "params": "no_es_un_dict", "device_id": "dev1"})
    _asegura_error_422(r)


def test_envelope_params_null_se_trata_como_vacio(client):
    # Mismo `or {}` que antes: `params: null` explícito sigue siendo válido (no rompe).
    r = client.post("/api/v1/deportivo", headers=HEADERS,
                     json={"action": "ping", "params": None, "device_id": "dev1"})
    assert r.status_code == 200


def test_juegos_date_muy_largo_da_422(client):
    r = _post(client, "juegos", {"date": "2026-01-01-2026-01-01-2026-01-01-extra-largo"})
    _asegura_error_422(r)


def test_prediccion_sin_match_id_da_422(client):
    r = _post(client, "prediccion", {"local": "A", "visitante": "B"})
    _asegura_error_422(r)


def test_prediccion_match_id_vacio_da_422(client):
    r = _post(client, "prediccion", {"match_id": "   "})
    _asegura_error_422(r)


def test_prediccion_happy_path_dispara_job(client, monkeypatch):
    # Se mockea `_procesar_job_app` (igual que el test de "juegos" mockea la cascada) para no
    # disparar una corrida real del motor de análisis / llamadas de red desde el
    # `asyncio.create_task` de fondo — solo interesa la respuesta síncrona del endpoint.
    from backend.api.routers import app_gateway

    async def _procesar_noop(client, job_id):
        return None

    monkeypatch.setattr(app_gateway, "_procesar_job_app", _procesar_noop)
    r = _post(client, "prediccion", {"match_id": "12345", "date": "2026-01-01",
                                      "local": "Equipo A", "visitante": "Equipo B", "league": "epl"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "prediction"
    assert body["data"]["status"] == "pendiente"
    assert body["data"]["job_id"]


def test_prediccion_match_id_numerico_sigue_funcionando(client, monkeypatch):
    # La app puede mandar match_id como número JSON (id de api-football) — el dispatcher viejo
    # lo toleraba con `str(...)`; el schema nuevo debe seguir tolerándolo.
    from backend.api.routers import app_gateway

    async def _procesar_noop(client, job_id):
        return None

    monkeypatch.setattr(app_gateway, "_procesar_job_app", _procesar_noop)
    r = client.post("/api/v1/deportivo", headers=HEADERS,
                     json={"action": "prediccion", "params": {"match_id": 999888}, "device_id": "dev1"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "pendiente"


def test_check_job_sin_job_id_da_422(client):
    r = _post(client, "check_job", {})
    _asegura_error_422(r)


def test_check_job_happy_path(client, monkeypatch):
    from backend.api.routers import app_gateway

    async def _procesar_noop(client, job_id):
        return None

    monkeypatch.setattr(app_gateway, "_procesar_job_app", _procesar_noop)
    r1 = _post(client, "prediccion", {"match_id": "555", "local": "A", "visitante": "B"})
    job_id = r1.json()["data"]["job_id"]

    r2 = _post(client, "check_job", {"job_id": job_id})
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "pendiente"


def test_top_happy_path(client):
    r = _post(client, "top")
    assert r.status_code == 200
    assert r.json()["type"] == "top_picks_carousel"


def test_stats_happy_path(client):
    r = _post(client, "stats")
    assert r.status_code == 200
    assert r.json()["type"] == "text"


def test_activar_codigo_sin_codigo_da_422(client):
    r = _post(client, "activar_codigo", {})
    _asegura_error_422(r)


def test_registrar_usuario_nickname_corto_da_422(client):
    r = _post(client, "registrar_usuario", {"nickname": "ab"})
    _asegura_error_422(r)


def test_registrar_usuario_sin_nickname_da_422(client):
    r = _post(client, "registrar_usuario", {})
    _asegura_error_422(r)


def test_verificar_partido_happy_path(client):
    r = _post(client, "verificar_partido", {"match_id": "111", "date": "2026-01-01"})
    assert r.status_code == 200
    assert r.json()["type"] == "partido_info"


def test_verificar_partido_usa_fecha_como_fallback_de_date(client):
    # Mismo `params.get("date", params.get("fecha", ""))` del dispatcher viejo — mandar solo
    # "fecha" (sin "date") sigue funcionando igual.
    r = _post(client, "verificar_partido", {"match_id": "111", "fecha": "2026-01-01"})
    assert r.status_code == 200
    assert r.json()["type"] == "partido_info"


def test_historial_limit_invalido_da_422(client):
    # Antes: `int(params.get("limit", 50))` con un `limit` no numérico tiraba `ValueError`
    # sin capturar → 500. Ahora corta en la validación con un 422 claro.
    r = _post(client, "historial", {"limit": "no_es_numero"})
    _asegura_error_422(r)


def test_historial_happy_path(client):
    r = _post(client, "historial", {"limit": 10})
    assert r.status_code == 200
    assert r.json()["type"] == "button_list"


def test_guardar_partidos_partidos_no_es_lista_de_dicts_da_422(client):
    # `partidos_repo.guardar_partidos_dia` ya declaraba `partidos: list[dict]` — antes nada
    # verificaba la forma real en el borde HTTP, así que un `partidos` con elementos que no son
    # dict revienta más adentro con AttributeError sin capturar (500).
    r = _post(client, "guardar_partidos", {"fecha": "2026-01-01", "partidos": ["no_es_un_dict"]})
    _asegura_error_422(r)


def test_guardar_partidos_happy_path(client):
    partido = {"match_id": "777", "local": "Equipo A", "visitante": "Equipo B",
               "hora_chile": "18:00", "status": "NS"}
    r = _post(client, "guardar_partidos", {"fecha": "2026-01-01", "partidos": [partido]})
    assert r.status_code == 200
    assert r.json()["data"]["guardados"] == 1


def test_activar_codigo_rechaza_device_id_vacio_sin_quemar_codigo(client):
    from backend.api.models.usuarios import CodigoAcceso

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(CodigoAcceso(codigo="KS-PRO-TEST001", plan="pro", dias=30, usado=0, creado_en="2026-10-16 00:00:00"))
        db.commit()
    finally:
        db.close()

    r = _post(client, "activar_codigo", {"codigo": "KS-PRO-TEST001"}, device_id="")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "error"
    assert body["data"]["activado"] is False
    assert body["data"]["success"] is False

    # Verificar que el código NO se quemó y sigue disponible para un device_id real o JWT
    r_ok = _post(client, "activar_codigo", {"codigo": "KS-PRO-TEST001"}, device_id="app_real_123")
    assert r_ok.status_code == 200
    body_ok = r_ok.json()
    assert body_ok["data"]["activado"] is True
    assert body_ok["data"]["success"] is True
    assert body_ok["data"]["plan"] == "pro"


def test_activar_codigo_resuelve_device_id_desde_jwt_si_body_trae_placeholder(client):
    from backend.api.models.usuarios import CodigoAcceso, Usuario

    r_reg = client.post(
        "/api/v1/auth/registro",
        json={"username": "userjwtcode", "password": "claveCorrecta1", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"},
    )
    assert r_reg.status_code == 200
    token = r_reg.json()["token"]
    dev_id_real = r_reg.json()["device_id"]

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        db.add(CodigoAcceso(codigo="KS-MAX-JWT0001", plan="max", dias=30, usado=0, creado_en="2026-10-16 00:00:00"))
        db.commit()
    finally:
        db.close()

    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    r_act = client.post(
        "/api/v1/deportivo",
        headers=headers,
        json={"action": "activar_codigo", "params": {"codigo": "KS-MAX-JWT0001"}, "device_id": "laplace"},
    )
    assert r_act.status_code == 200
    data = r_act.json()["data"]
    assert data["activado"] is True
    assert data["success"] is True
    assert data["plan"] == "max"

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        u = db.query(Usuario).filter(Usuario.device_id == dev_id_real).first()
        assert u is not None
        assert u.plan == "max"
    finally:
        db.close()

