"""test_admin.py — dashboard de administración global, v1 solo-lectura.

Cubre `routers/admin.py` (todos los endpoints GET, prefix `/api/v1/admin`): 403 sin ser admin
(usuario logueado con plan != "admin"), 401 sin token, y 200 con datos reales siendo admin.
Mismo patrón de fixture (BD en memoria, `TestClient`) que `test_auth.py`.
"""
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


def _token_admin(client) -> str:
    client.post("/api/v1/auth/registro", json={"username": "elAdmin", "password": "claveAdmin1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    # gestionar_usuario opera sobre device_id — el registro por usuario+clave usa un UUID
    # generado como device_id (ver usuarios_repo.crear_usuario_credenciales), así que primero
    # hay que leerlo desde /auth/me con el token recién emitido.
    r_login = client.post("/api/v1/auth/login", json={"username": "elAdmin", "password": "claveAdmin1"})
    token = r_login.json()["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    from backend.api.db import usuarios_repo

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        # rol separado de plan desde 2026-09-10 (ver models/usuarios.py §v7) — `requerir_admin`
        # ya no mira `plan`, así que promover a admin acá es `asignar_rol`, no `cambiar_plan`.
        usuarios_repo.asignar_rol(db, me["device_id"], "admin")
    finally:
        db.close()

    # El JWT ya emitido trae `rol: "usuario"` en el payload (se hasheó al momento del login,
    # antes del cambio de rol de arriba) — hay que loguear de nuevo para obtener un token
    # cuyo claim `rol` refleje el "admin" recién asignado, porque `requerir_admin` lee el
    # rol directo del payload del JWT, no de la BD en cada request.
    r_login2 = client.post("/api/v1/auth/login", json={"username": "elAdmin", "password": "claveAdmin1"})
    return r_login2.json()["token"]


def _token_no_admin(client) -> str:
    r = client.post("/api/v1/auth/registro", json={"username": "usuarioNormal", "password": "claveNormal1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    return r.json()["token"]


ENDPOINTS = [
    "/api/v1/admin/usuarios",
    "/api/v1/admin/codigos",
    "/api/v1/admin/historial-plan",
    "/api/v1/admin/intentos-login",
    "/api/v1/admin/jobs",
    "/api/v1/admin/stats",
    "/api/v1/admin/calibracion",
]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_endpoint_sin_token_da_401(client, endpoint):
    r = client.get(endpoint)
    # Header(...) es requerido por FastAPI — sin el header Authorization en absoluto, FastAPI
    # devuelve 422 (falta el parámetro) antes de que `obtener_usuario_actual` pueda correr y
    # dar el 401 real; mismo comportamiento ya documentado en
    # test_auth.py::test_logout_sin_authorization_da_401.
    assert r.status_code in (401, 422)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_endpoint_sin_ser_admin_da_403(client, endpoint):
    token = _token_no_admin(client)
    r = client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_listar_usuarios_admin_devuelve_paginado(client):
    token = _token_admin(client)
    client.post("/api/v1/auth/registro", json={"username": "otroUsuario", "password": "claveOtro1", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})

    r = client.get("/api/v1/admin/usuarios", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2  # el admin + otroUsuario
    assert body["limit"] == 50 and body["offset"] == 0
    assert any(u["username"] == "otroUsuario" for u in body["usuarios"])


def test_listar_usuarios_admin_busqueda_por_q(client):
    token = _token_admin(client)
    client.post("/api/v1/auth/registro", json={"username": "buscameYa", "password": "claveBusca1", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})

    r = client.get("/api/v1/admin/usuarios", params={"q": "buscame"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["usuarios"][0]["username"] == "buscameYa"


def test_listar_codigos_admin(client):
    token = _token_admin(client)

    from backend.api.db import codigos_repo

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        codigos_repo.generar_codigos_lote(db, "pro", 30, 2)
    finally:
        db.close()

    r = client.get("/api/v1/admin/codigos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["codigos"]) == 2


def test_historial_plan_admin_ve_el_cambio_a_admin(client):
    token = _token_admin(client)

    # Desde el 2026-09-10, `_token_admin` promueve con `asignar_rol` (rol separado de plan,
    # ver models/usuarios.py §v7) — ya no deja un registro en HistorialPlan por sí solo. Se
    # genera acá un cambio de PLAN real (independiente del rol) para verificar que el listado
    # lo ve, igual que antes.
    from backend.api.db import admin_repo

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        admin_repo.gestionar_usuario(db, "agregar", "u_hist_plan_test", plan="max", actor_admin_id="elAdmin")
    finally:
        db.close()

    r = client.get("/api/v1/admin/historial-plan", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(h["plan_nuevo"] == "max" and h["medio"] == "admin" for h in body["historial"])


def test_intentos_login_admin_ve_el_intento_fallido(client):
    token = _token_admin(client)
    client.post("/api/v1/auth/registro", json={"username": "conFallo", "password": "claveCorrecta1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    client.post("/api/v1/auth/login", json={"username": "conFallo", "password": "claveIncorrecta1"})

    r = client.get("/api/v1/admin/intentos-login", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(i["username_intentado"] == "conFallo" for i in body["intentos"])


def test_listar_jobs_admin_vacio_sin_jobs(client):
    token = _token_admin(client)
    r = client.get("/api/v1/admin/jobs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["jobs"] == []


def test_listar_jobs_admin_filtra_por_status(client):
    token = _token_admin(client)

    from backend.api.db import jobs_repo

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        jobs_repo.crear_job_app(db, "match1", "2026-09-08", "dev1", "pro")
        creado = jobs_repo.crear_job_app(db, "match2", "2026-09-08", "dev2", "pro")
        jobs_repo.actualizar_job_app(db, creado["job_id"], "listo", {"pick": "1"})
    finally:
        db.close()

    r_todos = client.get("/api/v1/admin/jobs", headers={"Authorization": f"Bearer {token}"})
    assert r_todos.json()["total"] == 2

    r_listos = client.get("/api/v1/admin/jobs", params={"status": "listo"}, headers={"Authorization": f"Bearer {token}"})
    body = r_listos.json()
    assert body["total"] == 1
    assert body["jobs"][0]["match_id"] == "match2"


def test_stats_admin_devuelve_shape_esperado(client):
    token = _token_admin(client)
    r = client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert "periodo_dias" in body and "pick_final" in body and "por_fuente" in body
    assert body["pick_final"]["total"] == 0  # sin predicciones evaluadas todavía en esta BD de test


def test_calibracion_admin_devuelve_shape_esperado_bd_vacia(client):
    token = _token_admin(client)
    r = client.get("/api/v1/admin/calibracion", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert "pick_final" in body and "por_modulo" in body and "brier_score_poisson" in body
    assert body["pick_final"]["evaluados"] == 0
    assert body["pick_final"]["confiable"] is False
    assert body["brier_score_poisson"]["muestra"] == 0
    assert "advertencia_general" in body and body["advertencia_general"]


def test_laboratorio_admin_registra_sombra_y_reporta(client):
    token = _token_admin(client)
    payload = {
        "experimento_codigo": "api_football_prediction", "partido_id": "lab-fixture", "fecha_partido": "2026-10-01",
        "local": "River", "visitante": "Boca", "fuente": "api-football", "variante": "api_football_prediction",
        "corte_datos_en": "2026-10-01T12:00:00Z", "hora_kickoff": "2026-10-01T18:00:00Z",
        "pick": "Local", "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2,
    }
    creado = client.post("/api/v1/admin/laboratorio-pronosticos", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert creado.status_code == 201
    assert creado.json()["estado"] == "sombra"
    reporte = client.get("/api/v1/admin/laboratorio-pronosticos", headers={"Authorization": f"Bearer {token}"})
    assert reporte.status_code == 200
    assert any(item["experimento"] == "api_football_prediction" for item in reporte.json()["comparadores"])


# --- v1.1 — escritura real (PATCH rol/plan), 2026-09-10 --------------------------------------


def _registrar_usuario(client, username: str) -> str:
    """Registra un usuario normal (no admin) y devuelve su `device_id` (leído vía /auth/me)."""
    client.post("/api/v1/auth/registro", json={"username": username, "password": "clavePlana1", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "clavePlana1"}).json()["token"]
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["device_id"]


def test_patch_rol_sin_token_da_401_o_422(client):
    r = client.patch("/api/v1/admin/usuarios/algun_device/rol", json={"rol": "admin"})
    assert r.status_code in (401, 422)


def test_patch_rol_sin_ser_admin_da_403(client):
    token = _token_no_admin(client)
    r = client.patch(
        "/api/v1/admin/usuarios/algun_device/rol", json={"rol": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_patch_rol_admin_real_cambia_el_rol_y_queda_en_bd(client):
    token = _token_admin(client)
    device_id = _registrar_usuario(client, "paraAscender")

    r = client.patch(
        f"/api/v1/admin/usuarios/{device_id}/rol", json={"rol": "agente"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accion"] == "rol_actualizado" and body["rol"] == "agente" and body["rol_anterior"] == "usuario"

    # Post-condición real en BD (empirical-verification-before-fix.md), no solo el 200.
    from backend.api.models.usuarios import Usuario

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
        assert usuario.rol == "agente"
    finally:
        db.close()

    r_lista = client.get("/api/v1/admin/usuarios", params={"q": "paraAscender"}, headers={"Authorization": f"Bearer {token}"})
    assert r_lista.json()["usuarios"][0]["rol"] == "agente"


def test_patch_rol_invalido_da_400(client):
    token = _token_admin(client)
    device_id = _registrar_usuario(client, "conRolInvalido")

    r = client.patch(
        f"/api/v1/admin/usuarios/{device_id}/rol", json={"rol": "superusuario"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_patch_rol_device_id_inexistente_da_400(client):
    token = _token_admin(client)
    r = client.patch(
        "/api/v1/admin/usuarios/device_que_no_existe/rol", json={"rol": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_patch_plan_sin_token_da_401_o_422(client):
    r = client.patch("/api/v1/admin/usuarios/algun_device/plan", json={"plan": "pro"})
    assert r.status_code in (401, 422)


def test_patch_plan_sin_ser_admin_da_403(client):
    token = _token_no_admin(client)
    r = client.patch(
        "/api/v1/admin/usuarios/algun_device/plan", json={"plan": "pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_patch_plan_admin_real_cambia_el_plan_y_queda_en_bd(client):
    token = _token_admin(client)
    device_id = _registrar_usuario(client, "paraCambiarPlan")

    r = client.patch(
        f"/api/v1/admin/usuarios/{device_id}/plan", json={"plan": "max"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accion"] == "plan_actualizado" and body["plan"] == "max"

    from backend.api.models.usuarios import Usuario

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
        assert usuario.plan == "max"
    finally:
        db.close()

    # Queda registrado en HistorialPlan con el admin actor real (no vacío) — mismo mecanismo
    # que ya cubre test_historial_plan_admin_ve_el_cambio_a_admin arriba.
    r_hist = client.get("/api/v1/admin/historial-plan", headers={"Authorization": f"Bearer {token}"})
    assert any(
        h["device_id"] == device_id and h["plan_nuevo"] == "max" and h["medio"] == "admin"
        for h in r_hist.json()["historial"]
    )


def test_patch_plan_no_acepta_admin_como_valor(client):
    """"admin" ya no es un valor de plan válido desde que `rol` se separó de `plan`
    (`admin_repo.PLANES_VALIDOS` ya no lo incluye, ver la sección v1.1 de
    `PROPUESTA_DASHBOARD_ADMIN.md`)."""
    token = _token_admin(client)
    device_id = _registrar_usuario(client, "intentaPlanAdmin")

    r = client.patch(
        f"/api/v1/admin/usuarios/{device_id}/plan", json={"plan": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_patch_plan_invalido_da_400(client):
    token = _token_admin(client)
    device_id = _registrar_usuario(client, "conPlanInvalido")

    r = client.patch(
        f"/api/v1/admin/usuarios/{device_id}/plan", json={"plan": "diamante"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_patch_plan_device_id_inexistente_da_400(client):
    token = _token_admin(client)
    r = client.patch(
        "/api/v1/admin/usuarios/device_que_no_existe/plan", json={"plan": "pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
