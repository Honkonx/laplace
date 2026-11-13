"""Rutas de `routers/agent.py` con TestClient: sesiones, memoria (exportación e historial), tareas,
subagentes, aprobaciones, eventos, métricas, feedback y propuestas de aprendizaje.

Siempre se comprueba el aislamiento entre usuarios (uno no ve lo ajeno) y que solo el administrador
decide aprobaciones y revisa propuestas. SQLite en memoria, sin red ni claves reales."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401
from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.models.agent_runtime import (
    AgentEvent,
    AgentKnowledge,
    AgentMemory,
    AgentMessage,
    AgentRun,
    AgentSession,
    AgentTask,
)
from backend.api.routers import agent as agent_router
from backend.api.services import agent_guard, agent_tools, task_orchestrator
from backend.api.services.agent_approvals import crear_aprobacion
from backend.api.services.agent_guard import LimiteExcedido

USUARIO = {"sub": "usuario-1", "rol": "user"}
OTRO = {"sub": "usuario-2", "rol": "user"}
ADMIN = {"sub": "admin-1", "rol": "admin"}
HEADERS = {"Authorization": "Bearer prueba"}
BASE = "/api/v1/agent"


def _ahora(delta_horas: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_horas)).isoformat()


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
    monkeypatch.setattr(agent_router, "sincronizar_conocimiento_json", lambda db: 0)
    agent_guard.resetear_contadores()
    cliente = TestClient(app)
    e = SimpleNamespace(client=cliente, sesion=sesion, engine=engine, actual=actual)
    e.como = lambda usuario: actual.__setitem__("usuario", usuario)
    yield e
    app.dependency_overrides.clear()
    agent_guard.resetear_contadores()


def _insertar(entorno, *filas):
    with entorno.sesion() as db:
        db.add_all(filas)
        db.commit()


# --------------------------------------------------------------------------------------------
# Catálogo, capacidades, uso y métricas
# --------------------------------------------------------------------------------------------

def test_proveedores_solo_para_admin_y_nunca_revela_credenciales(entorno, monkeypatch):
    assert entorno.client.get(f"{BASE}/providers").status_code == 403
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "valor-secreto-de-prueba")
    entorno.como(ADMIN)
    r = entorno.client.get(f"{BASE}/providers")
    assert r.status_code == 200
    por_id = {p["id"]: p for p in r.json()["providers"]}
    assert por_id["anthropic"]["configured"] is True and por_id["anthropic"]["status"] == "configured"
    assert por_id["openai"]["status"] in {"configured", "not_configured"}
    assert "valor-secreto-de-prueba" not in r.text
    assert "ollama_cloud" in por_id


def test_capacidades_y_uso_responden_a_cada_rol(entorno):
    r = entorno.client.get(f"{BASE}/capabilities")
    assert r.status_code == 200 and r.json()["rol"] == "usuario"
    entorno.como(ADMIN)
    assert entorno.client.get(f"{BASE}/capabilities").json()["rol"] == "admin"
    uso = entorno.client.get(f"{BASE}/usage")
    assert uso.status_code == 200 and uso.json()["rol"] == "admin" and uso.json()["tareas_activas"] == 0


def test_metricas_solo_admin_en_formato_prometheus(entorno):
    assert entorno.client.get(f"{BASE}/metrics").status_code == 403
    entorno.client.post(f"{BASE}/tasks", json={"kind": "agent.qa", "payload": {}})
    entorno.client.post(f"{BASE}/memory", json={"topic_key": "t", "content": "hola"})
    entorno.como(ADMIN)
    r = entorno.client.get(f"{BASE}/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert 'laplace_agent_tasks_total{status="queued"} 1' in r.text
    assert "laplace_agent_memories_active 1" in r.text
    for serie in ("approvals_pending", "tool_invocations_total", "events_total"):
        assert f"laplace_agent_{serie}" in r.text


# --------------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------------

def test_chat_delega_en_el_runtime_con_el_rol_del_token(entorno, monkeypatch):
    vistos = []

    async def falso(db, user_id, mensaje, session_id, canal, usar_ia, es_admin, authorization, incognito=False):
        vistos.append((user_id, mensaje, canal, usar_ia, es_admin, authorization))
        return {"session_id": "s", "respuesta": "ok"}

    monkeypatch.setattr(agent_router, "procesar_mensaje", falso)
    assert entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": "hola"}).json()["respuesta"] == "ok"
    entorno.como(ADMIN)
    entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": "hola", "channel": "pwa"})
    assert vistos == [("usuario-1", "hola", "web", False, False, "Bearer prueba"), ("admin-1", "hola", "pwa", False, True, "Bearer prueba")]


def test_chat_valida_el_cuerpo_y_traduce_value_error_a_400(entorno, monkeypatch):
    async def falla(*args, **kwargs):
        raise ValueError("mensaje no permitido")

    monkeypatch.setattr(agent_router, "procesar_mensaje", falla)
    r = entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": "hola"})
    assert r.status_code == 400 and r.json()["detail"] == "mensaje no permitido"
    assert entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": ""}).status_code == 422
    assert entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": "x", "channel": "fax"}).status_code == 422
    assert entorno.client.post(f"{BASE}/chat", json={"message": "x"}).status_code == 422  # sin Authorization


def test_chat_con_ia_consume_el_presupuesto_y_responde_429_al_agotarlo(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "1")

    async def falso(*args, **kwargs):
        return {"respuesta": "ok"}

    monkeypatch.setattr(agent_router, "procesar_mensaje", falso)
    cuerpo = {"message": "hola", "usar_ia": True}
    assert entorno.client.post(f"{BASE}/chat", headers=HEADERS, json=cuerpo).status_code == 200
    r = entorno.client.post(f"{BASE}/chat", headers=HEADERS, json=cuerpo)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # sin IA no consume cupo
    assert entorno.client.post(f"{BASE}/chat", headers=HEADERS, json={"message": "hola"}).status_code == 200


# --------------------------------------------------------------------------------------------
# Herramientas
# --------------------------------------------------------------------------------------------

def test_catalogo_de_herramientas_oculta_las_de_admin(entorno):
    nombres = {t["name"] for t in entorno.client.get(f"{BASE}/tools").json()["tools"]}
    assert "sports.predict" in nombres and "sports.publish" not in nombres
    entorno.como(ADMIN)
    assert "sports.publish" in {t["name"] for t in entorno.client.get(f"{BASE}/tools").json()["tools"]}


def _invocaciones(entorno):
    return entorno.client.get(f"{BASE}/tools/invocations").json()["invocations"]


def test_herramienta_exitosa_queda_registrada_como_succeeded(entorno, monkeypatch):
    async def falso(nombre, argumentos, **kwargs):
        return {"ok": True, "tool": nombre, "eco": argumentos, "usuario": kwargs["usuario"]}

    monkeypatch.setattr(agent_router, "ejecutar_herramienta_deportiva", falso)
    r = entorno.client.post(f"{BASE}/tools/knowledge.glossary", headers=HEADERS, json={"arguments": {"term": "RPS", "confirm": True}})
    assert r.status_code == 200 and r.json()["eco"] == {"term": "RPS"}  # `confirm` del cliente se descarta
    [inv] = _invocaciones(entorno)
    assert inv["tool"] == "knowledge.glossary" and inv["status"] == "succeeded" and inv["finished_at"]


def test_herramienta_no_ok_sin_confirmacion_queda_waiting_confirmation(entorno, monkeypatch):
    async def falso(nombre, argumentos, **kwargs):
        return {"ok": False, "tool": nombre}

    monkeypatch.setattr(agent_router, "ejecutar_herramienta_deportiva", falso)
    assert entorno.client.post(f"{BASE}/tools/x", headers=HEADERS, json={}).status_code == 200
    assert _invocaciones(entorno)[0]["status"] == "waiting_confirmation"


@pytest.mark.parametrize("excepcion,codigo,estado", [
    (LimiteExcedido("tope", 42), 429, "denied"),
    (PermissionError("sin permiso"), 403, "denied"),
    (ValueError("argumento inválido"), 400, "failed"),
    (RuntimeError("backend caído"), 400, "failed"),
    (httpx.ConnectError("sin red"), 400, "failed"),
])
def test_errores_de_herramienta_se_traducen_y_se_auditan(entorno, monkeypatch, excepcion, codigo, estado):
    async def falla(*args, **kwargs):
        raise excepcion

    monkeypatch.setattr(agent_router, "ejecutar_herramienta_deportiva", falla)
    r = entorno.client.post(f"{BASE}/tools/sports.predict", headers=HEADERS, json={"arguments": {}})
    assert r.status_code == codigo
    if codigo == 429:
        assert r.headers["Retry-After"] == "42"
    [inv] = _invocaciones(entorno)
    assert inv["status"] == estado and inv["error"] and inv["finished_at"]


def test_error_inesperado_de_herramienta_se_registra_y_se_propaga(entorno, monkeypatch):
    async def falla(*args, **kwargs):
        raise ZeroDivisionError("bug")

    monkeypatch.setattr(agent_router, "ejecutar_herramienta_deportiva", falla)
    with pytest.raises(ZeroDivisionError):
        entorno.client.post(f"{BASE}/tools/sports.predict", headers=HEADERS, json={"arguments": {}})
    [inv] = _invocaciones(entorno)
    assert inv["status"] == "failed" and inv["error"].startswith("ZeroDivisionError")


def test_invocaciones_son_privadas_de_cada_usuario(entorno, monkeypatch):
    async def falso(nombre, argumentos, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(agent_router, "ejecutar_herramienta_deportiva", falso)
    entorno.client.post(f"{BASE}/tools/a", headers=HEADERS, json={})
    entorno.como(OTRO)
    assert _invocaciones(entorno) == []
    entorno.como(ADMIN)
    assert _invocaciones(entorno) == []  # ni siquiera el admin ve las ajenas por esta ruta
    assert entorno.client.get(f"{BASE}/tools/invocations?limit=0").status_code == 422


# --------------------------------------------------------------------------------------------
# Aprobaciones y eventos
# --------------------------------------------------------------------------------------------

def _aprobacion(entorno, usuario="usuario-1", herramienta="sports.publish", argumentos=None):
    with entorno.sesion() as db:
        item = crear_aprobacion(db, "inv-x", usuario, herramienta, argumentos or {"publish": True})
        db.commit()
        return item.id


def test_cada_usuario_ve_solo_sus_aprobaciones_y_el_admin_todas(entorno):
    propia = _aprobacion(entorno, "usuario-1")
    ajena = _aprobacion(entorno, "usuario-2")
    ids = {a["id"] for a in entorno.client.get(f"{BASE}/approvals").json()["approvals"]}
    assert ids == {propia}
    entorno.como(OTRO)
    assert {a["id"] for a in entorno.client.get(f"{BASE}/approvals").json()["approvals"]} == {ajena}
    entorno.como(ADMIN)
    assert {a["id"] for a in entorno.client.get(f"{BASE}/approvals").json()["approvals"]} == {propia, ajena}


def test_listar_aprobaciones_marca_las_vencidas_como_expired(entorno):
    vieja = _aprobacion(entorno)
    with entorno.sesion() as db:
        from backend.api.models.agent_runtime import AgentApproval

        db.get(AgentApproval, vieja).requested_en = _ahora(-5)
        db.commit()
    [item] = entorno.client.get(f"{BASE}/approvals").json()["approvals"]
    assert item["id"] == vieja and item["status"] == "expired"


def test_solo_el_admin_aprueba_o_rechaza(entorno):
    aprobacion = _aprobacion(entorno)
    for accion in ("approve", "reject"):
        assert entorno.client.post(f"{BASE}/approvals/{aprobacion}/{accion}", headers=HEADERS).status_code == 403
    entorno.como(OTRO)
    assert entorno.client.post(f"{BASE}/approvals/{aprobacion}/approve", headers=HEADERS).status_code == 403


def test_admin_rechaza_sin_ejecutar_y_deja_evento_al_solicitante(entorno, monkeypatch):
    async def no_debe_correr(*args, **kwargs):
        raise AssertionError("un rechazo no ejecuta la herramienta")

    monkeypatch.setattr(agent_tools, "_post", no_debe_correr)
    aprobacion = _aprobacion(entorno, "usuario-1")
    entorno.como(ADMIN)
    r = entorno.client.post(f"{BASE}/approvals/{aprobacion}/reject", headers=HEADERS)
    assert r.status_code == 200 and r.json() == {"id": aprobacion, "status": "rejected", "executed": False}
    assert entorno.client.post(f"{BASE}/approvals/{aprobacion}/reject", headers=HEADERS).status_code == 404  # ya decidida
    entorno.como(USUARIO)
    tipos = [e["type"] for e in entorno.client.get(f"{BASE}/events").json()["events"]]
    assert tipos == ["approval.rejected"]


def test_admin_aprueba_y_se_ejecuta_la_herramienta_una_sola_vez(entorno, monkeypatch):
    llamadas = []

    async def post_falso(path, payload, params=None, authorization=None):
        llamadas.append((path, params))
        return {"publicado": True}

    monkeypatch.setattr(agent_tools, "_post", post_falso)
    aprobacion = _aprobacion(entorno, "usuario-1")
    entorno.como(ADMIN)
    r = entorno.client.post(f"{BASE}/approvals/{aprobacion}/approve", headers=HEADERS)
    assert r.status_code == 200 and r.json()["executed"] is True and "user_id" not in r.json()
    assert llamadas == [("/api/v1/scheduler/top-picks", {"publicar": True})]


def test_aprobar_inexistente_da_404_y_un_fallo_de_ejecucion_da_400(entorno, monkeypatch):
    entorno.como(ADMIN)
    assert entorno.client.post(f"{BASE}/approvals/no-existe/approve", headers=HEADERS).status_code == 404

    async def post_roto(*args, **kwargs):
        raise RuntimeError("el bot no respondió")

    monkeypatch.setattr(agent_tools, "_post", post_roto)
    aprobacion = _aprobacion(entorno)
    r = entorno.client.post(f"{BASE}/approvals/{aprobacion}/approve", headers=HEADERS)
    assert r.status_code == 400 and "no respondió" in r.json()["detail"]


def test_eventos_aislados_por_usuario_y_admin_ve_todos(entorno):
    task_orchestrator.registrar_evento("usuario-1", "a", {"x": 1})
    task_orchestrator.registrar_evento("usuario-2", "b")
    ver = lambda: [e["type"] for e in entorno.client.get(f"{BASE}/events").json()["events"]]  # noqa: E731
    assert ver() == ["a"]
    entorno.como(OTRO)
    assert ver() == ["b"]
    entorno.como(ADMIN)
    assert ver() == ["b", "a"]  # más reciente primero
    assert len(entorno.client.get(f"{BASE}/events?limit=1").json()["events"]) == 1
    assert entorno.client.get(f"{BASE}/events?limit=501").status_code == 422
    assert entorno.client.get(f"{BASE}/events").json()["events"][1]["payload"] == {"x": 1}


# --------------------------------------------------------------------------------------------
# Sesiones, mensajes y ejecuciones
# --------------------------------------------------------------------------------------------

def test_sesiones_y_mensajes_solo_del_dueno(entorno):
    _insertar(
        entorno,
        AgentSession(id="s1", user_id="usuario-1", channel="web", title="Mía", status="active", creado_en=_ahora(), actualizado_en=_ahora()),
        AgentSession(id="s2", user_id="usuario-2", channel="web", title="Ajena", status="active", creado_en=_ahora(), actualizado_en=_ahora()),
        AgentMessage(session_id="s1", user_id="usuario-1", role="user", content="hola", modo="reglas", creado_en=_ahora()),
        AgentMessage(session_id="s1", user_id="usuario-1", role="assistant", content="buenas", modo="reglas", creado_en=_ahora()),
        AgentMessage(session_id="s2", user_id="usuario-2", role="user", content="secreto ajeno", modo="reglas", creado_en=_ahora()),
    )
    assert [s["id"] for s in entorno.client.get(f"{BASE}/sessions").json()["sessions"]] == ["s1"]
    mensajes = entorno.client.get(f"{BASE}/sessions/s1/messages").json()["messages"]
    assert [m["content"] for m in mensajes] == ["hola", "buenas"]
    ajena = entorno.client.get(f"{BASE}/sessions/s2/messages")
    assert ajena.status_code == 404 and "secreto" not in ajena.text
    assert entorno.client.get(f"{BASE}/sessions/no-existe/messages").status_code == 404
    entorno.como(ADMIN)
    assert entorno.client.get(f"{BASE}/sessions/s1/messages").status_code == 404  # tampoco el admin lee chats ajenos


def test_ejecuciones_solo_las_propias_y_con_limite(entorno):
    _insertar(
        entorno,
        AgentRun(id="r1", user_id="usuario-1", status="succeeded", output_json=json.dumps({"modo": "reglas"}), creado_en=_ahora(-1)),
        AgentRun(id="r2", user_id="usuario-1", status="succeeded", creado_en=_ahora()),
        AgentRun(id="r3", user_id="usuario-2", status="succeeded", creado_en=_ahora()),
    )
    corridas = entorno.client.get(f"{BASE}/runs").json()["runs"]
    assert [r["id"] for r in corridas] == ["r2", "r1"] and corridas[1]["output"] == {"modo": "reglas"}
    assert len(entorno.client.get(f"{BASE}/runs?limit=1").json()["runs"]) == 1
    assert entorno.client.get(f"{BASE}/runs?limit=201").status_code == 422


# --------------------------------------------------------------------------------------------
# Memoria
# --------------------------------------------------------------------------------------------

def _guardar(entorno, **campos):
    cuerpo = {"topic_key": "preferencia", "content": "prefiero ligas europeas", **campos}
    return entorno.client.post(f"{BASE}/memory", json=cuerpo)


def test_guardar_memoria_de_usuario_deja_historial_de_creacion(entorno):
    r = _guardar(entorno)
    assert r.status_code == 200 and r.json()["saved"] is True and r.json()["scope"] == "usuario"
    historial = entorno.client.get(f"{BASE}/memory/{r.json()['id']}/history").json()["history"]
    assert [h["action"] for h in historial] == ["create"] and historial[0]["changed_by"] == "usuario-1"
    assert historial[0]["after"]["content"] == "prefiero ligas europeas"


def test_memoria_global_solo_la_crea_el_admin_y_todos_la_leen(entorno):
    assert _guardar(entorno, scope="global").status_code == 403
    entorno.como(ADMIN)
    assert _guardar(entorno, scope="global", content="regla global").status_code == 200
    entorno.como(OTRO)
    assert [m["content"] for m in entorno.client.get(f"{BASE}/memory").json()["memory"]] == ["regla global"]


def test_memoria_rechaza_credenciales_y_marca_datos_personales_como_sensibles(entorno):
    r = _guardar(entorno, content="mi api key es " + "sk" + "-abcdefghijklmnop1234")
    assert r.status_code == 400 and "credencial" in r.json()["detail"]
    pii = _guardar(entorno, content="mi correo es persona@example.com").json()
    with entorno.sesion() as db:
        assert db.get(AgentMemory, pii["id"]).sensibilidad == "sensible"
    # un valor más restrictivo pedido por el cliente se respeta
    privada = _guardar(entorno, content="nota", sensibilidad="privada").json()
    with entorno.sesion() as db:
        assert db.get(AgentMemory, privada["id"]).sensibilidad == "privada"


def test_memoria_valida_el_cuerpo(entorno):
    assert _guardar(entorno, scope="otro").status_code == 422
    assert _guardar(entorno, confidence=2).status_code == 422
    assert _guardar(entorno, sensibilidad="publica").status_code == 422
    assert entorno.client.post(f"{BASE}/memory", json={"topic_key": "x", "content": ""}).status_code == 422


def test_memoria_privada_de_un_usuario_no_se_ve_ni_se_borra_por_otro(entorno):
    mia = _guardar(entorno).json()["id"]
    entorno.como(OTRO)
    assert entorno.client.get(f"{BASE}/memory").json()["memory"] == []
    assert entorno.client.delete(f"{BASE}/memory/{mia}").status_code == 404
    assert entorno.client.get(f"{BASE}/memory/{mia}/history").status_code == 404
    entorno.como(ADMIN)
    assert entorno.client.delete(f"{BASE}/memory/{mia}").status_code == 404  # el admin no borra memorias privadas ajenas
    with entorno.sesion() as db:
        assert db.get(AgentMemory, mia).activo == 1


def test_borrar_memoria_la_archiva_con_historial_y_desaparece_del_listado(entorno):
    mid = _guardar(entorno).json()["id"]
    r = entorno.client.delete(f"{BASE}/memory/{mid}")
    assert r.status_code == 200 and r.json() == {"id": mid, "archived": True}
    assert entorno.client.get(f"{BASE}/memory").json()["memory"] == []
    acciones = [h["action"] for h in entorno.client.get(f"{BASE}/memory/{mid}/history").json()["history"]]
    assert acciones == ["create", "archive"]
    assert entorno.client.delete(f"{BASE}/memory/9999").status_code == 404


def test_memoria_global_no_la_borra_ni_la_lee_en_historial_un_usuario_normal(entorno):
    entorno.como(ADMIN)
    gid = _guardar(entorno, scope="global").json()["id"]
    entorno.como(USUARIO)
    assert entorno.client.delete(f"{BASE}/memory/{gid}").status_code == 404
    assert entorno.client.get(f"{BASE}/memory/{gid}/history").status_code == 404
    entorno.como(ADMIN)
    assert entorno.client.delete(f"{BASE}/memory/{gid}").status_code == 200


def test_memoria_vencida_no_se_lista_ni_se_exporta(entorno):
    _guardar(entorno, content="vigente")
    _guardar(entorno, content="vencida", expira_en=_ahora(-1))
    _guardar(entorno, content="futura", expira_en=_ahora(5))
    assert {m["content"] for m in entorno.client.get(f"{BASE}/memory").json()["memory"]} == {"vigente", "futura"}
    exportada = entorno.client.get(f"{BASE}/memory/export").json()
    assert exportada["format"] == "json" and {m["content"] for m in exportada["memory"]} == {"vigente", "futura"}


def test_exportar_memoria_jsonl_excluye_sensibles_y_ajenas(entorno):
    _guardar(entorno, content="publica 1")
    _guardar(entorno, content="mi correo es persona@example.com")
    _guardar(entorno, content="privada", sensibilidad="privada")
    entorno.como(OTRO)
    _guardar(entorno, content="de otro usuario")
    entorno.como(USUARIO)
    r = entorno.client.get(f"{BASE}/memory/export?formato=jsonl")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    filas = [json.loads(linea) for linea in r.text.splitlines()]
    assert [f["content"] for f in filas] == ["publica 1"] and filas[0]["sensitivity"] == "normal"
    assert entorno.client.get(f"{BASE}/memory/export?formato=xml").status_code == 422


# --------------------------------------------------------------------------------------------
# Conocimiento y búsqueda
# --------------------------------------------------------------------------------------------

def test_conocimiento_lista_solo_las_entradas_activas(entorno):
    _insertar(
        entorno,
        AgentKnowledge(namespace="glosario", topic_key="rps", content="Ranked probability score", source="knowledge/a.json", metadata_json="{}", creado_en=_ahora(), actualizado_en=_ahora()),
        AgentKnowledge(namespace="glosario", topic_key="viejo", content="retirado", source="knowledge/a.json", metadata_json=json.dumps({"inactive": True}), creado_en=_ahora(), actualizado_en=_ahora()),
    )
    r = entorno.client.get(f"{BASE}/knowledge").json()["knowledge"]
    assert [k["topic_key"] for k in r] == ["rps"]


def test_busqueda_exige_minimo_de_caracteres(entorno):
    assert entorno.client.get(f"{BASE}/search?q=a").status_code == 422
    assert entorno.client.get(f"{BASE}/search").status_code == 422


def test_busqueda_con_fallback_sql_respeta_la_privacidad(entorno):
    _insertar(
        entorno,
        AgentMessage(session_id="s1", user_id="usuario-1", role="user", content="quiero el River Plate", modo="reglas", creado_en=_ahora()),
        AgentMessage(session_id="s2", user_id="usuario-2", role="user", content="River Plate de otro", modo="reglas", creado_en=_ahora()),
        AgentKnowledge(namespace="n", topic_key="river", content="River Plate es un club", source="s", metadata_json="{}", creado_en=_ahora(), actualizado_en=_ahora()),
    )
    _guardar(entorno, content="me gusta River Plate")
    entorno.como(OTRO)
    _guardar(entorno, content="memoria ajena de River Plate")
    entorno.como(USUARIO)
    r = entorno.client.get(f"{BASE}/search?q=River").json()
    assert r["engine"] == "sql-like"
    contenidos = {x["content"] for x in r["results"]}
    assert contenidos == {"quiero el River Plate", "me gusta River Plate", "River Plate es un club"}


def test_busqueda_fts5_filtra_lo_que_no_es_del_usuario(entorno):
    try:
        with entorno.engine.begin() as conexion:
            conexion.execute(text("CREATE VIRTUAL TABLE agent_search_fts USING fts5(kind, ref_id, owner_id, scope, content, topic_key)"))
    except Exception:
        pytest.skip("SQLite sin FTS5 en este entorno")
    filas = [
        ("knowledge", "1", "", "global", "estadistica de River", "k"),
        ("message", "2", "usuario-1", "usuario", "River mensaje propio", ""),
        ("message", "3", "usuario-2", "usuario", "River mensaje ajeno", ""),
        ("memory", "4", "usuario-2", "usuario", "River memoria ajena", "m"),
        ("memory", "5", "", "global", "River memoria global", "g"),
    ]
    with entorno.engine.begin() as conexion:
        for fila in filas:
            conexion.execute(text("INSERT INTO agent_search_fts VALUES (:a,:b,:c,:d,:e,:f)"), dict(zip("abcdef", fila)))
    r = entorno.client.get(f"{BASE}/search?q=River").json()
    assert r["engine"] == "sqlite-fts5"
    assert {x["id"] for x in r["results"]} == {"1", "2", "5"}


# --------------------------------------------------------------------------------------------
# Feedback y aprendizaje
# --------------------------------------------------------------------------------------------

def test_feedback_con_y_sin_ejecucion_propia(entorno):
    _insertar(entorno, AgentRun(id="mia", user_id="usuario-1", creado_en=_ahora()), AgentRun(id="ajena", user_id="usuario-2", creado_en=_ahora()))
    assert entorno.client.post(f"{BASE}/feedback", json={"rating": 5, "run_id": "mia", "label": "util"}).json()["saved"] is True
    assert entorno.client.post(f"{BASE}/feedback", json={"rating": 3}).status_code == 200
    assert entorno.client.post(f"{BASE}/feedback", json={"rating": 5, "run_id": "ajena"}).status_code == 404
    assert entorno.client.post(f"{BASE}/feedback", json={"rating": 5, "run_id": "no-existe"}).status_code == 404
    for malo in (0, 6):
        assert entorno.client.post(f"{BASE}/feedback", json={"rating": malo}).status_code == 422


def test_estadisticas_de_feedback_solo_para_admin(entorno):
    assert entorno.client.get(f"{BASE}/learning/feedback-stats").status_code == 403
    _insertar(entorno, AgentRun(id="r", user_id="usuario-1", output_json=json.dumps({"herramienta": "sports.predict", "modo": "reglas"}), creado_en=_ahora()))
    entorno.client.post(f"{BASE}/feedback", json={"rating": 4, "run_id": "r"})
    entorno.como(ADMIN)
    r = entorno.client.get(f"{BASE}/learning/feedback-stats")
    assert r.status_code == 200 and isinstance(r.json(), dict)


def _proponer(entorno, **campos):
    cuerpo = {"topic_key": "tono", "proposal": {"estilo": "breve"}, **campos}
    return entorno.client.post(f"{BASE}/learning/proposals", json=cuerpo)


def test_propuestas_de_aprendizaje_privadas_y_globales_solo_del_admin(entorno):
    propia = _proponer(entorno)
    assert propia.status_code == 200 and propia.json()["status"] == "pending"
    assert _proponer(entorno, scope="global").status_code == 403
    entorno.como(OTRO)
    assert entorno.client.get(f"{BASE}/learning/proposals").json()["proposals"] == []
    entorno.como(ADMIN)
    assert len(entorno.client.get(f"{BASE}/learning/proposals").json()["proposals"]) == 1
    assert _proponer(entorno, scope="global").status_code == 200


def test_solo_el_admin_revisa_propuestas_y_solo_las_pendientes(entorno):
    pid = _proponer(entorno).json()["id"]
    assert entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=approved").status_code == 403
    entorno.como(ADMIN)
    assert entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=quizas").status_code == 422
    assert entorno.client.post(f"{BASE}/learning/proposals/no-existe/review?status=approved").status_code == 404
    rechazada = entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=rejected&note=no%20aplica").json()
    assert rechazada["status"] == "rejected" and rechazada["applied"] is False and rechazada["policy_version_id"] is None
    assert entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=approved").status_code == 404  # ya revisada
    assert entorno.client.get(f"{BASE}/learning/policies").json()["policies"] == []


def test_aprobar_propuesta_crea_politica_del_autor_no_del_revisor(entorno):
    pid = _proponer(entorno).json()["id"]
    entorno.como(ADMIN)
    r = entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=approved").json()
    assert r["applied"] is True and r["policy_version_id"]
    [politica] = entorno.client.get(f"{BASE}/learning/policies").json()["policies"]
    assert politica["created_by"] == "usuario-1" and politica["version"] == 1 and politica["status"] == "active"
    assert politica["content"] == {"estilo": "breve"}
    entorno.como(USUARIO)
    assert [p["id"] for p in entorno.client.get(f"{BASE}/learning/policies").json()["policies"]] == [politica["id"]]
    entorno.como(OTRO)
    assert entorno.client.get(f"{BASE}/learning/policies").json()["policies"] == []
    eventos = [e for e in _eventos_de(entorno, "admin-1") if e == "policy.approved"]
    assert eventos == ["policy.approved"]  # el revisor queda en la auditoría


def _eventos_de(entorno, usuario):
    with entorno.sesion() as db:
        return [e.event_type for e in db.query(AgentEvent).filter(AgentEvent.user_id == usuario).all()]


def test_nueva_politica_reemplaza_solo_la_del_mismo_dueno_y_se_puede_revertir(entorno):
    def aprobar(usuario, contenido):
        entorno.como(usuario)
        pid = _proponer(entorno, proposal={"v": contenido}).json()["id"]
        entorno.como(ADMIN)
        return entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=approved").json()["policy_version_id"]

    v1 = aprobar(USUARIO, 1)
    ajena = aprobar(OTRO, 1)
    v2 = aprobar(USUARIO, 2)
    estados = {p["id"]: (p["status"], p["version"]) for p in entorno.client.get(f"{BASE}/learning/policies").json()["policies"]}
    assert estados[v1] == ("superseded", 1) and estados[v2][0] == "active"
    assert estados[ajena][0] == "active"  # la política de otro usuario con el mismo tema no se toca

    assert entorno.client.post(f"{BASE}/learning/policies/{v1}/rollback").status_code == 200
    estados = {p["id"]: p["status"] for p in entorno.client.get(f"{BASE}/learning/policies").json()["policies"]}
    assert estados[v1] == "active" and estados[v2] == "superseded" and estados[ajena] == "active"
    assert "policy.rollback" in _eventos_de(entorno, "admin-1")


def test_revertir_politica_exige_admin_y_existencia(entorno):
    assert entorno.client.post(f"{BASE}/learning/policies/x/rollback").status_code == 403
    entorno.como(ADMIN)
    assert entorno.client.post(f"{BASE}/learning/policies/no-existe/rollback").status_code == 404


def test_politicas_globales_solo_las_ve_el_admin(entorno):
    entorno.como(ADMIN)
    pid = _proponer(entorno, scope="global", topic_key="seguridad").json()["id"]
    entorno.client.post(f"{BASE}/learning/proposals/{pid}/review?status=approved")
    assert len(entorno.client.get(f"{BASE}/learning/policies").json()["policies"]) == 1
    entorno.como(USUARIO)
    assert entorno.client.get(f"{BASE}/learning/policies").json()["policies"] == []


# --------------------------------------------------------------------------------------------
# Tareas y subagentes
# --------------------------------------------------------------------------------------------

def _crear(entorno, **campos):
    return entorno.client.post(f"{BASE}/tasks", json={"kind": "agent.qa", "payload": {}, **campos})


def test_tipo_de_tarea_fuera_del_registro_da_400(entorno):
    r = _crear(entorno, kind="shell.exec")
    assert r.status_code == 400 and "Tipo no permitido" in r.json()["detail"]


def test_crear_listar_y_leer_tareas_propias(entorno):
    creada = _crear(entorno).json()
    assert creada["status"] == "queued" and creada["kind"] == "agent.qa"
    assert [t["id"] for t in entorno.client.get(f"{BASE}/tasks").json()["tasks"]] == [creada["id"]]
    detalle = entorno.client.get(f"{BASE}/tasks/{creada['id']}").json()
    assert detalle["status"] == "queued" and detalle["cancel_requested"] is False and detalle["output"] == {}
    assert entorno.client.get(f"{BASE}/tasks?limit=0").status_code == 422


def test_las_tareas_de_otro_usuario_no_se_ven_ni_se_cancelan(entorno):
    creada = _crear(entorno).json()
    entorno.como(OTRO)
    assert entorno.client.get(f"{BASE}/tasks").json()["tasks"] == []
    assert entorno.client.get(f"{BASE}/tasks/{creada['id']}").status_code == 404
    assert entorno.client.post(f"{BASE}/tasks/{creada['id']}/cancel").status_code == 404
    entorno.como(ADMIN)
    assert entorno.client.get(f"{BASE}/tasks/{creada['id']}").status_code == 404
    with entorno.sesion() as db:
        assert db.get(AgentTask, creada["id"]).status == "queued"


def test_cancelar_tarea_propia_y_luego_ya_no_se_puede(entorno):
    creada = _crear(entorno).json()
    r = entorno.client.post(f"{BASE}/tasks/{creada['id']}/cancel")
    assert r.status_code == 200 and r.json() == {"id": creada["id"], "cancel_requested": True}
    assert entorno.client.get(f"{BASE}/tasks/{creada['id']}").json()["status"] == "cancelled"
    assert entorno.client.post(f"{BASE}/tasks/{creada['id']}/cancel").status_code == 404
    assert entorno.client.post(f"{BASE}/tasks/no-existe/cancel").status_code == 404


def test_tarea_idempotente_devuelve_la_misma(entorno):
    a = _crear(entorno, idempotency_key="clave-1").json()
    b = _crear(entorno, idempotency_key="clave-1").json()
    assert a["id"] == b["id"]
    assert len(entorno.client.get(f"{BASE}/tasks").json()["tasks"]) == 1


def test_tarea_hija_exige_un_padre_propio(entorno):
    padre = _crear(entorno, kind="agent.parallel").json()
    hija = _crear(entorno, parent_id=padre["id"])
    assert hija.status_code == 200
    assert _crear(entorno, parent_id="no-existe").status_code == 404
    entorno.como(OTRO)
    assert _crear(entorno, parent_id=padre["id"]).status_code == 404


def test_tareas_con_ia_consumen_presupuesto(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "1")
    assert _crear(entorno, kind="agent.chat", payload={"message": "a", "usar_ia": False}).status_code == 200  # sin IA: gratis
    assert _crear(entorno, kind="agent.chat", payload={"message": "a", "usar_ia": True}).status_code == 200
    r = _crear(entorno, kind="agent.chat", payload={"message": "a", "usar_ia": True})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_crear_tarea_traduce_errores_del_orquestador(entorno, monkeypatch):
    def tope(*args, **kwargs):
        raise LimiteExcedido("Demasiadas tareas activas", 30)

    monkeypatch.setattr(agent_router, "crear_tarea", tope)
    r = _crear(entorno)
    assert r.status_code == 429 and r.headers["Retry-After"] == "30"

    def invalida(*args, **kwargs):
        raise KeyError("payload")

    monkeypatch.setattr(agent_router, "crear_tarea", invalida)
    assert _crear(entorno).status_code == 400


def test_llamadas_ia_de_una_tarea():
    cuenta = agent_router._llamadas_ia_de_tarea
    assert cuenta("agent.chat", {"usar_ia": True}) == 1
    assert cuenta("agent.chat", {}) == 0
    assert cuenta("agent.qa", {"usar_ia": True}) == 0
    solicitudes = [{"kind": "agent.chat", "payload": {"usar_ia": True}}] * 6 + [{"kind": "agent.qa"}]
    assert cuenta("agent.parallel", {"requests": solicitudes}) == 4  # solo se miran las 4 primeras
    mezcla = [{"kind": "agent.chat", "payload": {"usar_ia": True}}, {"kind": "agent.chat", "payload": "roto"}, "texto", {"kind": "agent.qa"}]
    assert cuenta("agent.parallel", {"requests": mezcla}) == 1
    assert cuenta("agent.parallel", {"requests": "no-lista"}) == 0


def test_subagentes_expone_el_registro_cerrado(entorno):
    r = entorno.client.get(f"{BASE}/subagents").json()["subagents"]
    assert {s["id"] for s in r} == {"laplace.chat", "sports.bridge", "qa.contracts"} and all(s["enabled"] for s in r)
