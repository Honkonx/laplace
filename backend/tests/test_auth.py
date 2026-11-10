"""test_auth.py — login usuario+clave (app/web, sin correo), agregado 2026-09-07.

Cubre: registro real, username duplicado (409), login correcto, password incorrecta (401
genérico), JWT inválido/expirado en `obtener_usuario_actual`, y que el hash de Argon2 nunca
sea la password en texto plano.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.auth_deps import ALGORITMO_JWT, obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.core.rate_limit import limiter
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.services.auth_password import hashear_password, verificar_password
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
    # El rate limiter de /login y /registro (backend/api/core/rate_limit.py) es un singleton
    # a nivel de proceso — sin resetear acá, los intentos de un test se acumulan sobre los
    # del siguiente (TestClient siempre pega desde la misma IP simulada) y un test que no
    # tiene nada que ver con rate limiting puede empezar a fallar con 429.
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_registro_exitoso_devuelve_token(client):
    r = client.post("/api/v1/auth/registro", json={"username": "usuario_prueba", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "usuario_prueba"
    assert body["plan"] == "free"
    assert "token" in body and body["token"]


def test_registro_username_duplicado_da_409(client):
    client.post("/api/v1/auth/registro", json={"username": "duplicado", "password": "clave12345", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    r = client.post("/api/v1/auth/registro", json={"username": "duplicado", "password": "otraclave99", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    assert r.status_code == 409


def test_registro_origen_invalido_da_400(client):
    r = client.post("/api/v1/auth/registro", json={"username": "usuarionuevo", "password": "clave12345", "origen": "telegram"})
    assert r.status_code == 400


def test_registro_username_corto_da_400(client):
    r = client.post("/api/v1/auth/registro", json={"username": "ab", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    assert r.status_code == 400


def test_login_correcto_devuelve_token(client):
    client.post("/api/v1/auth/registro", json={"username": "loginok", "password": "miclave123", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    r = client.post("/api/v1/auth/login", json={"username": "loginok", "password": "miclave123"})
    assert r.status_code == 200
    assert r.json()["token"]


def test_login_password_incorrecta_da_401_generico(client):
    client.post("/api/v1/auth/registro", json={"username": "loginmal", "password": "claveCorrecta1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    r = client.post("/api/v1/auth/login", json={"username": "loginmal", "password": "claveIncorrecta1"})
    assert r.status_code == 401
    # Mensaje genérico — nunca debe distinguir "usuario no existe" de "password incorrecta"
    assert "incorrectos" in r.json()["detail"].lower()


def test_login_usuario_inexistente_mismo_401_generico(client):
    r = client.post("/api/v1/auth/login", json={"username": "noexiste123", "password": "cualquierclave"})
    assert r.status_code == 401
    assert "incorrectos" in r.json()["detail"].lower()


def test_hash_argon2_no_es_la_password_en_texto_plano():
    hash_ = hashear_password("miPasswordSecreta1")
    assert hash_ != "miPasswordSecreta1"
    assert hash_.startswith("$argon2")


def test_verificar_password_ida_y_vuelta():
    hash_ = hashear_password("otraClaveDePrueba2")
    assert verificar_password("otraClaveDePrueba2", hash_) is True
    assert verificar_password("claveIncorrecta", hash_) is False


def test_obtener_usuario_actual_token_valido():
    token = jwt.encode(
        {"sub": "abc-123", "username": "u1", "plan": "free",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.WEB_JWT_SECRET, algorithm=ALGORITMO_JWT,
    )
    payload = obtener_usuario_actual(f"Bearer {token}")
    assert payload["username"] == "u1"


def test_obtener_usuario_actual_token_expirado_da_401():
    token = jwt.encode(
        {"sub": "abc-123", "username": "u1", "plan": "free",
         "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        settings.WEB_JWT_SECRET, algorithm=ALGORITMO_JWT,
    )
    with pytest.raises(HTTPException) as exc:
        obtener_usuario_actual(f"Bearer {token}")
    assert exc.value.status_code == 401


def test_obtener_usuario_actual_token_invalido_da_401():
    with pytest.raises(HTTPException) as exc:
        obtener_usuario_actual("Bearer token-basura-invalido")
    assert exc.value.status_code == 401


def test_obtener_usuario_actual_header_sin_bearer_da_401():
    with pytest.raises(HTTPException) as exc:
        obtener_usuario_actual("tokensinbearer")
    assert exc.value.status_code == 401


def test_registro_emite_jti_unico(client):
    r1 = client.post("/api/v1/auth/registro", json={"username": "jtiuser1", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    r2 = client.post("/api/v1/auth/registro", json={"username": "jtiuser2", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    p1 = jwt.decode(r1.json()["token"], settings.WEB_JWT_SECRET, algorithms=[ALGORITMO_JWT])
    p2 = jwt.decode(r2.json()["token"], settings.WEB_JWT_SECRET, algorithms=[ALGORITMO_JWT])
    assert p1["jti"] and p2["jti"]
    assert p1["jti"] != p2["jti"]


def test_logout_revoca_el_token_y_login_posterior_lo_rechaza(client):
    r = client.post("/api/v1/auth/registro", json={"username": "logoutuser", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    r_logout = client.post("/api/v1/auth/logout", headers=headers)
    assert r_logout.status_code == 200
    assert r_logout.json()["cerrado"] is True

    # el mismo token ya no sirve para acciones protegidas (jti quedó en token_revocado)
    r_logout_de_nuevo = client.post("/api/v1/auth/logout", headers=headers)
    assert r_logout_de_nuevo.status_code == 401


def test_revocar_token_es_idempotente(db_session):
    from backend.api.db.tokens_repo import esta_revocado, revocar_token

    r1 = revocar_token(db_session, jti="jti-fijo-1", device_id="dev1")
    r2 = revocar_token(db_session, jti="jti-fijo-1", device_id="dev1")
    assert r1["ya_estaba"] is False
    assert r2["ya_estaba"] is True
    assert esta_revocado(db_session, "jti-fijo-1") is True
    assert esta_revocado(db_session, "jti-que-no-existe") is False


def test_logout_sin_authorization_da_401(client):
    r = client.post("/api/v1/auth/logout")
    assert r.status_code in (401, 422)  # Header(...) requerido — FastAPI puede devolver 422


def test_logout_token_sin_jti_da_400_explicito(client):
    """Simula un token emitido antes del claim `jti` (transición) — no debe crashear, debe
    devolver un 400 explicando que ese token puntual no se puede revocar."""
    token_viejo = jwt.encode(
        {"sub": "dev-viejo", "username": "u1", "plan": "free",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.WEB_JWT_SECRET, algorithm=ALGORITMO_JWT,
    )
    r = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_viejo}"})
    assert r.status_code == 400


def test_constraint_unique_username_a_nivel_bd_rechaza_duplicado(db_session):
    """Prueba la constraint UNIQUE real de `usuarios.username` (migración 2026-09-09,
    9b999dd77b12) a nivel de BD/ORM, sin pasar por el chequeo previo de auth.py — verifica que
    el fix cierra la carrera TOCTOU incluso si el SELECT de chequeo se salteara por completo."""
    from sqlalchemy.exc import IntegrityError

    from backend.api.models.usuarios import Usuario

    db_session.add(Usuario(device_id="dev-a", activo=1, plan="free", creado_en="2026-09-09 00:00:00",
                            origen="web", username="carrera", password_hash="hash1"))
    db_session.commit()

    db_session.add(Usuario(device_id="dev-b", activo=1, plan="free", creado_en="2026-09-09 00:00:00",
                            origen="web", username="carrera", password_hash="hash2"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    total = db_session.query(Usuario).filter(Usuario.username == "carrera").count()
    assert total == 1


def test_constraint_unique_username_permite_multiples_null(db_session):
    """Confirma el comportamiento estándar de SQLite: varias filas con `username IS NULL` no
    conflictúan entre sí (usuarios de Telegram, que no tienen username) — solo colisiona un
    valor no-nulo repetido."""
    from backend.api.models.usuarios import Usuario

    db_session.add(Usuario(device_id="tg-1", activo=1, plan="free", creado_en="2026-09-09 00:00:00", origen="telegram"))
    db_session.add(Usuario(device_id="tg-2", activo=1, plan="free", creado_en="2026-09-09 00:00:00", origen="telegram"))
    db_session.commit()  # no debe lanzar IntegrityError

    total = db_session.query(Usuario).filter(Usuario.device_id.in_(["tg-1", "tg-2"])).count()
    assert total == 2


def test_registro_concurrente_mismo_username_uno_falla_con_409(client, monkeypatch):
    """Simula la ventana TOCTOU real: dos requests concurrentes que ambas ven "username libre"
    en el SELECT de chequeo (`obtener_usuario_por_username` parcheado para devolver siempre
    None, como si ambas leyeran antes de que la otra hiciera commit) — sin la constraint UNIQUE
    de la migración 9b999dd77b12, las dos colarían; con ella, el segundo INSERT debe chocar con
    `IntegrityError` y el router debe traducirlo a 409 (nunca un 500)."""
    import backend.api.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "obtener_usuario_por_username", lambda db, username: None)

    r1 = client.post("/api/v1/auth/registro", json={"username": "carreraapp", "password": "clave12345", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})
    r2 = client.post("/api/v1/auth/registro", json={"username": "carreraapp", "password": "otraclave99", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"})

    codigos = {r1.status_code, r2.status_code}
    assert codigos == {200, 409}
    fallido = r1 if r1.status_code == 409 else r2
    assert fallido.json()["detail"] == "Ese nombre de usuario ya está en uso"

    # Verificar la post-condición real en la BD, no solo el código HTTP — debe haber quedado
    # UNA sola fila con ese username, no dos.
    from backend.api.models.usuarios import Usuario
    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        assert db.query(Usuario).filter(Usuario.username == "carreraapp").count() == 1
    finally:
        db.close()


def test_login_fallido_queda_registrado_en_intento_login_fallido(client):
    from backend.api.db.auditoria_repo import contar_intentos_fallidos_recientes

    client.post("/api/v1/auth/registro", json={"username": "auditlogin", "password": "claveCorrecta1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"})
    client.post("/api/v1/auth/login", json={"username": "auditlogin", "password": "claveIncorrecta1"})
    client.post("/api/v1/auth/login", json={"username": "noexisteaudit", "password": "cualquiera"})

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        assert contar_intentos_fallidos_recientes(db, "auditlogin") == 1
        assert contar_intentos_fallidos_recientes(db, "noexisteaudit") == 1
    finally:
        db.close()


def test_registro_y_login_devuelven_device_id_canonico(client):
    r_reg = client.post(
        "/api/v1/auth/registro",
        json={"username": "usuariodevid", "password": "claveCorrecta1", "origen": "app", "terms_accepted": True, "terms_version": "2026-09-25"},
    )
    assert r_reg.status_code == 200
    datos_reg = r_reg.json()
    assert isinstance(datos_reg["device_id"], str) and len(datos_reg["device_id"]) >= 16

    r_login = client.post(
        "/api/v1/auth/login",
        json={"username": "usuariodevid", "password": "claveCorrecta1"},
    )
    assert r_login.status_code == 200
    datos_login = r_login.json()
    assert datos_login["device_id"] == datos_reg["device_id"]



def test_activar_codigo_jwt_actualiza_plan_y_emite_nuevo_token(client):
    from backend.api.db import codigos_repo

    r_reg = client.post(
        "/api/v1/auth/registro",
        json={"username": "usuariocodigo", "password": "claveCorrecta1", "origen": "web", "terms_accepted": True, "terms_version": "2026-09-25"},
    )
    assert r_reg.status_code == 200
    token = r_reg.json()["token"]

    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        lote = codigos_repo.generar_codigos_lote(db, "pro", 30, 1)
        codigo = lote["codigos"][0]
    finally:
        db.close()

    r_act = client.post(
        "/api/v1/auth/activar-codigo",
        json={"codigo": codigo},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_act.status_code == 200
    datos_act = r_act.json()
    assert datos_act["activado"] is True
    assert datos_act["plan"] == "pro"
    assert datos_act["token"]

    r_me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {datos_act['token']}"},
    )
    assert r_me.status_code == 200
    assert r_me.json()["plan"] == "pro"
    assert r_me.json()["activo_hasta"] is not None
