"""Seguridad del agente: escalada de rol, autoconfirmación, aprobaciones, presupuesto de IA,
validación de `.env`, confianza de destino y allowlist de Telegram."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.models.agent_runtime import AgentApproval, AgentTask
from backend.api.routers import agent as agent_router
from backend.api.services import admin_env, agent_guard, agent_tools, task_orchestrator
import backend.api.models  # noqa: F401

USUARIO = {"sub": "usuario-1", "rol": "user"}
ADMIN = {"sub": "admin-1", "rol": "admin"}


@pytest.fixture()
def entorno(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine)

    def _db():
        db = sesion()
        try:
            yield db
        finally:
            db.close()

    actual = {"usuario": USUARIO}
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[obtener_usuario_actual] = lambda: actual["usuario"]
    monkeypatch.setattr(task_orchestrator, "SessionLocal", sesion)
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", False)
    agent_guard.resetear_contadores()
    yield SimpleNamespace(client=TestClient(app), sesion=sesion, actual=actual)
    app.dependency_overrides.clear()
    agent_guard.resetear_contadores()


HEADERS = {"Authorization": "Bearer prueba"}


def test_es_admin_del_cliente_se_ignora_en_tareas(entorno):
    r = entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.chat", "payload": {"message": "hola", "es_admin": True}})
    assert r.status_code == 200
    with entorno.sesion() as db:
        assert json.loads(db.get(AgentTask, r.json()["id"]).input_json)["es_admin"] is False

    entorno.actual["usuario"] = ADMIN
    r = entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.chat", "payload": {"message": "hola", "es_admin": False}})
    with entorno.sesion() as db:
        assert json.loads(db.get(AgentTask, r.json()["id"]).input_json)["es_admin"] is True


def test_subagentes_heredan_es_admin_del_padre_no_del_cliente(entorno, monkeypatch):
    creados = []

    monkeypatch.setattr(task_orchestrator, "_ejecutar", lambda child_id: creados.append(child_id))
    padre = {"es_admin": False, "requests": [{"kind": "agent.chat", "payload": {"message": "x", "es_admin": True}}]}
    task_orchestrator._ejecutar_paralelo("padre-1", "usuario-1", padre)
    with entorno.sesion() as db:
        hijo = db.query(AgentTask).filter(AgentTask.parent_id == "padre-1").one()
        assert json.loads(hijo.input_json)["es_admin"] is False
        assert hijo.timeout_seconds <= 120 and hijo.max_attempts == 1


def test_limites_de_tarea_acotados(entorno):
    r = entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.qa", "payload": {}, "timeout_seconds": 300})
    assert r.status_code == 422
    r = entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.qa", "payload": {}, "max_attempts": 5})
    assert r.status_code == 422
    tarea = task_orchestrator.crear_tarea("u", "agent.qa", {}, max_attempts=9, timeout_seconds=9999)
    assert (tarea.max_attempts, tarea.timeout_seconds) == (2, 120)


def test_tope_de_tareas_activas_por_usuario(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_TAREAS_ACTIVAS", "2")
    for _ in range(2):
        assert entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.qa", "payload": {}}).status_code == 200
    assert entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.qa", "payload": {}}).status_code == 429


def test_confirm_del_cliente_no_ejecuta_y_pasa_por_aprobacion(entorno, monkeypatch):
    llamadas = []

    async def post_falso(path, payload, params=None, authorization=None):
        llamadas.append((path, params, authorization))
        return {"publicado": True}

    monkeypatch.setattr(agent_tools, "_post", post_falso)
    entorno.actual["usuario"] = ADMIN
    r = entorno.client.post("/api/v1/agent/tools/sports.publish", headers=HEADERS, json={"arguments": {"publish": True, "confirm": True}})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["requires_confirmation"] is True and cuerpo["status"] == "pending"
    assert llamadas == []
    with entorno.sesion() as db:
        assert "confirm" not in json.loads(db.get(AgentApproval, cuerpo["approval_id"]).payload_json)

    aprobada = entorno.client.post(f"/api/v1/agent/approvals/{cuerpo['approval_id']}/approve", headers=HEADERS)
    assert aprobada.status_code == 200 and aprobada.json()["executed"] is True
    assert len(llamadas) == 1 and llamadas[0][1] == {"publicar": True}
    # Un segundo intento (carrera/doble clic) no vuelve a ejecutar.
    repetida = entorno.client.post(f"/api/v1/agent/approvals/{cuerpo['approval_id']}/approve", headers=HEADERS)
    assert repetida.status_code == 404
    assert len(llamadas) == 1


def test_usuario_normal_no_puede_decidir_ni_pedir_herramientas_admin(entorno):
    r = entorno.client.post("/api/v1/agent/tools/sports.publish", headers=HEADERS, json={"arguments": {"publish": True, "confirm": True}})
    assert r.status_code == 403
    assert entorno.client.post("/api/v1/agent/approvals/x/approve", headers=HEADERS).status_code == 403


def test_aprobacion_vencida_no_se_ejecuta(entorno, monkeypatch):
    async def post_falso(*args, **kwargs):
        raise AssertionError("no debe ejecutarse")

    monkeypatch.setattr(agent_tools, "_post", post_falso)
    entorno.actual["usuario"] = ADMIN
    cuerpo = entorno.client.post("/api/v1/agent/tools/sports.publish", headers=HEADERS, json={"arguments": {"publish": True}}).json()
    with entorno.sesion() as db:
        fila = db.get(AgentApproval, cuerpo["approval_id"])
        fila.requested_en = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        db.commit()
    r = entorno.client.post(f"/api/v1/agent/approvals/{cuerpo['approval_id']}/approve", headers=HEADERS)
    assert r.status_code == 410
    with entorno.sesion() as db:
        assert db.get(AgentApproval, cuerpo["approval_id"]).status == "expired"


def test_presupuesto_de_ia_por_minuto_en_chat_y_tareas(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "2")

    async def chat_falso(*args, **kwargs):
        return {"session_id": "s", "run_id": "r", "respuesta": "ok", "modo": "reglas", "herramienta": None}

    monkeypatch.setattr(agent_router, "procesar_mensaje", chat_falso)
    codigos = [entorno.client.post("/api/v1/agent/chat", headers=HEADERS, json={"message": "hola", "usar_ia": True}).status_code for _ in range(3)]
    assert codigos == [200, 200, 429]
    # Sin IA no consume presupuesto.
    assert entorno.client.post("/api/v1/agent/chat", headers=HEADERS, json={"message": "hola", "usar_ia": False}).status_code == 200
    # Las tareas con IA comparten el mismo presupuesto.
    r = entorno.client.post("/api/v1/agent/tasks", headers=HEADERS, json={"kind": "agent.chat", "payload": {"message": "hola", "usar_ia": True}})
    assert r.status_code == 429


def test_presupuesto_diario_y_cuenta_por_usuario(monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "100")
    monkeypatch.setenv("AGENT_IA_MAX_POR_DIA", "3")
    agent_guard.resetear_contadores()
    for _ in range(3):
        agent_guard.consumir_ia("a")
    with pytest.raises(agent_guard.LimiteExcedido):
        agent_guard.consumir_ia("a")
    agent_guard.consumir_ia("b")  # otro usuario no se ve afectado
    agent_guard.consumir_ia("a", es_admin=True)  # admin tiene cupo ampliado
    agent_guard.resetear_contadores()


def test_admin_env_rechaza_inyeccion_de_lineas(tmp_path):
    repo = tmp_path
    for mala in ["abcdefgh\nEVIL=1", "abcdefgh\rEVIL=1", 'abc"defgh', "abc defgh12", "abcdefgh'", "abc$(whoami)xx", "a" * 600, "corta"]:
        with pytest.raises(ValueError):
            admin_env.guardar_proveedor_env(repo, "groq", mala, "modelo-x")
    assert not (repo / ".env").exists()
    admin_env.guardar_proveedor_env(repo, "groq", "gsk_ABCdef123456-_.", "llama-3.3-70b")
    contenido = (repo / ".env").read_text(encoding="utf-8")
    assert "GROQ_API_KEY=gsk_ABCdef123456-_." in contenido and contenido.count("\n") == 2


def test_bearer_solo_a_destinos_confiables(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "http://127.0.0.1:9001")
    assert agent_guard.autorizacion_sports("u", "Bearer real") == "Bearer real"
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "https://externo.example.com")
    assert agent_guard.autorizacion_sports("u", "Bearer real") is None
    monkeypatch.setenv("AGENT_SPORTS_TRUSTED_HOSTS", "externo.example.com")
    assert agent_guard.autorizacion_sports("u", "Bearer real") == "Bearer real"


def test_post_nunca_envia_credencial_a_host_no_confiable(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "https://externo.example.com")
    monkeypatch.delenv("AGENT_SPORTS_TRUSTED_HOSTS", raising=False)
    with pytest.raises(PermissionError):
        asyncio.run(agent_tools._post("/x", {}, authorization="Bearer secreto"))


def test_token_de_servicio_es_de_usuario_y_corto(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "http://localhost:9001")
    cabecera = agent_guard.autorizacion_sports("telegram:5", None)
    datos = jwt.decode(cabecera.removeprefix("Bearer "), settings.WEB_JWT_SECRET, algorithms=["HS256"])
    assert datos["sub"] == "telegram:5" and datos["rol"] == "user" and datos["svc"] == "agent"
    assert datos["exp"] - datos["iat"] <= 120


def test_confirm_en_argumentos_se_ignora_en_la_herramienta():
    resultado = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("sports.publish", {"publish": True, "confirm": True}, es_admin=True))
    assert resultado["requires_confirmation"] is True


# --- Telegram -----------------------------------------------------------------------------------

def _update(user_id: int, texto: str = "hola"):
    respuestas = []

    async def reply_text(mensaje):
        respuestas.append(mensaje)

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id), effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(text=texto, reply_text=reply_text), respuestas=respuestas,
    )


def test_bot_telegram_allowlist_rate_limit_y_errores(monkeypatch):
    from backend.api.bot import laplace_agent_bot as bot

    monkeypatch.setattr(type(settings), "admin_ids", property(lambda self: ["1"]))
    monkeypatch.setenv("AGENT_TELEGRAM_ALLOWED_IDS", "2")
    monkeypatch.setenv("AGENT_TELEGRAM_RATE_PER_MIN", "2")
    agent_guard._VENTANA_CHAT.clear()
    llamados = []

    @bot.protegido
    async def handler(update, context):
        llamados.append(update.effective_user.id)
        if update.effective_message.text == "boom":
            raise RuntimeError("fallo interno")

    desconocido = _update(99)
    asyncio.run(handler(desconocido, None))
    assert llamados == [] and desconocido.respuestas == [bot.MSG_NO_AUTORIZADO]

    permitido = _update(2)
    asyncio.run(handler(permitido, None))
    assert llamados == [2]
    asyncio.run(handler(_update(2, "boom"), None))  # el error se contiene y se avisa
    limitado = _update(2)
    asyncio.run(handler(limitado, None))
    assert limitado.respuestas == [bot.MSG_LIMITE]

    admin = _update(1)
    asyncio.run(handler(admin, None))
    assert 1 in llamados


def test_bot_telegram_sin_allowlist_esta_abierto_a_todos_pero_respeta_vetos(monkeypatch):
    """Decisión del usuario 2026-10-07: el agente funciona para todos; los privilegios son del admin."""
    from backend.api.bot import laplace_agent_bot as bot

    monkeypatch.setattr(type(settings), "admin_ids", property(lambda self: ["1"]))
    monkeypatch.delenv("AGENT_TELEGRAM_ALLOWED_IDS", raising=False)
    monkeypatch.setenv("AGENT_TELEGRAM_BLOCKED_IDS", "3")
    assert bot._esta_autorizado(_update(1)) and bot._esta_autorizado(_update(2))
    assert not bot._esta_autorizado(_update(3))  # vetado
    monkeypatch.setenv("AGENT_TELEGRAM_BLOCKED_IDS", "1")
    assert bot._esta_autorizado(_update(1))  # un admin nunca queda vetado


# --- Tope de predicciones en el punto común (revisión de seguridad 2026-10-07) ----------------------------

def test_tope_de_predicciones_aplica_igual_por_cualquier_camino_y_el_admin_queda_exento(monkeypatch):
    monkeypatch.setenv("AGENT_PREDICCIONES_MAX_POR_MINUTO", "2")
    agent_guard.resetear_contadores()

    async def falso_post(ruta, payload, params=None, authorization=None):
        return {"consenso": {"pick_final": "Local"}, "odds_info": {}}

    monkeypatch.setattr(agent_tools, "_post", falso_post)
    args = {"match_id": "1", "local": "A", "visitante": "B", "league": "X"}

    def llamar(nombre, **kw):
        return asyncio.run(agent_tools.ejecutar_herramienta_deportiva(nombre, args, authorization="Bearer x", **kw))

    llamar("sports.predict", usuario="telegram:5")
    llamar("sports.get_odds", usuario="telegram:5")  # predict y get_odds comparten el mismo presupuesto
    with pytest.raises(agent_guard.LimiteExcedido):
        llamar("sports.predict", usuario="telegram:5")
    for _ in range(5):  # el admin no tiene tope; y sin `usuario` (llamada interna) no se cuenta
        llamar("sports.predict", usuario="telegram:1", es_admin=True)
        llamar("sports.predict")
    llamar("sports.predict", usuario="telegram:6")  # otro usuario tiene su propio presupuesto
    agent_guard.resetear_contadores()
