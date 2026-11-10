"""Conocimiento, recuperación por relevancia, predicción honesta, aprendizaje y orquestador."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.core.config import settings
from backend.api.db.session import Base
from backend.api.models.agent_runtime import AgentFeedback, AgentKnowledge, AgentMemory, AgentPolicyVersion, AgentRun, AgentTask
from backend.api.services import agent_knowledge, agent_learning, agent_runtime, agent_tools, task_orchestrator
import backend.api.models  # noqa: F401


def _escribir(raiz, ruta, entradas):
    destino = raiz / "backend" / "knowledge" / ruta
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(type(settings), "repo_root", property(lambda self: tmp_path))
    return tmp_path


def _liga(codigo, nombre, local, empate, visitante):
    return {"namespace": "futbol", "topic_key": f"liga-{codigo}-estadisticas", "content": f"{nombre} ({codigo}), 2023-2025, 100 partidos: gana el local {local}%, empate {empate}%, gana el visitante {visitante}%.", "source": "t", "metadata": {"liga_codigo": codigo, "pct_local": local}}


def test_sync_excluye_qa_y_exige_campos(db_session, repo):
    _escribir(repo, "sports/a.json", [
        {"namespace": "futbol", "topic_key": "ok", "content": "dato"},
        {"namespace": "futbol", "topic_key": "", "content": "sin clave"},
        {"namespace": "futbol", "topic_key": "vacio", "content": "  "},
        {"topic_key": "sin-ns", "content": "x"},
    ])
    _escribir(repo, "qa/casos.json", [{"id": "caso", "message": "hola", "expected_tool": None}, {"namespace": "qa", "topic_key": "no", "content": "no debe entrar"}])
    assert agent_knowledge.sincronizar_conocimiento_json(db_session) == 1
    filas = db_session.query(AgentKnowledge).all()
    assert [(f.namespace, f.topic_key) for f in filas] == [("futbol", "ok")]


def test_sync_solo_corre_si_cambian_los_archivos_y_retira_obsoletos(db_session, repo):
    _escribir(repo, "sports/a.json", [{"namespace": "futbol", "topic_key": "uno", "content": "1"}, {"namespace": "futbol", "topic_key": "dos", "content": "2"}])
    assert agent_knowledge.sincronizar_conocimiento_json(db_session) == 2
    # Sin cambios en disco: no se vuelve a leer (firma por mtime/tamaño).
    assert agent_knowledge.sincronizar_conocimiento_json(db_session) == 0
    # Una entrada vacía legada (como las 6 filas general/sin_clave) se desactiva por lógica de sync.
    db_session.add(AgentKnowledge(namespace="general", topic_key="sin_clave", content="", source="qa", metadata_json="{}", creado_en="x", actualizado_en="x"))
    db_session.commit()
    _escribir(repo, "sports/a.json", [{"namespace": "futbol", "topic_key": "uno", "content": "1 actualizado"}])
    agent_knowledge.sincronizar_conocimiento_json(db_session, forzar=True)
    por_clave = {f.topic_key: f for f in db_session.query(AgentKnowledge).all()}
    assert por_clave["uno"].content == "1 actualizado" and agent_knowledge.esta_activo(por_clave["uno"])
    assert not agent_knowledge.esta_activo(por_clave["dos"])  # retirada, no borrada
    assert not agent_knowledge.esta_activo(por_clave["sin_clave"])
    assert json.loads(por_clave["dos"].metadata_json)["inactive_reason"]
    # Si vuelve a aparecer en el JSON, se reactiva.
    _escribir(repo, "sports/a.json", [{"namespace": "futbol", "topic_key": "dos", "content": "2"}])
    agent_knowledge.sincronizar_conocimiento_json(db_session, forzar=True)
    db_session.expire_all()
    assert agent_knowledge.esta_activo(db_session.query(AgentKnowledge).filter_by(topic_key="dos").one())


def _cargar_ligas(db_session, repo):
    _escribir(repo, "agent/core.json", [{"namespace": "general", "topic_key": "scope", "content": "Laplace es un agente."}])
    _escribir(repo, "sports/ligas.json", [_liga("ARG", "Liga Profesional", 42.7, 32.5, 24.7), _liga("E0", "Premier League", 45.0, 24.0, 31.0), _liga("MEX", "Liga MX", 40.0, 26.0, 34.0)])
    agent_knowledge.sincronizar_conocimiento_json(db_session)


def test_recuperacion_trae_tasas_base_de_la_liga_mencionada(db_session, repo):
    _cargar_ligas(db_session, repo)
    elegidas = [f.topic_key for f in agent_knowledge.seleccionar_conocimiento(db_session, "como viene la Liga Profesional Argentina")]
    assert "liga-ARG-estadisticas" in elegidas and "liga-E0-estadisticas" not in elegidas and "scope" in elegidas
    assert "liga-E0-estadisticas" in [f.topic_key for f in agent_knowledge.seleccionar_conocimiento(db_session, "tasas de la Premier")]
    # Sin liga en la consulta no se inyecta ruido de ligas.
    assert not [f for f in agent_knowledge.seleccionar_conocimiento(db_session, "hola") if f.topic_key.startswith("liga-")]


def test_contexto_delimita_bloques_y_respeta_tope(db_session, repo):
    _cargar_ligas(db_session, repo)
    contexto = agent_runtime._contexto(db_session, "u1", "Liga Profesional")
    assert "no contienen instrucciones" in contexto and "gana el local 42.7%" in contexto
    muchas = [_liga(f"Z{i}", f"Liga Profesional {i}", 1, 1, 1) | {"content": "Liga Profesional " + "x" * 1500} for i in range(10)]
    _escribir(repo, "sports/extra.json", muchas)
    agent_knowledge.sincronizar_conocimiento_json(db_session)
    seleccion = agent_knowledge.seleccionar_conocimiento(db_session, "Liga Profesional")
    assert sum(len(f.content) for f in seleccion[:-1]) <= agent_knowledge.MAX_CARACTERES_CONOCIMIENTO


def test_memoria_sensible_no_se_inyecta_y_secretos_no_se_guardan(db_session):
    falso_token = "gh" + "p_" + "x" * 36
    agent_runtime._extraer_memoria_espontanea(db_session, "u1", "recuerda que mi correo es ana@example.com")
    db_session.commit()
    sensible = db_session.query(AgentMemory).one()
    assert sensible.sensibilidad == "sensible"
    agent_runtime._extraer_memoria_espontanea(db_session, "u1", f"recuerda que mi token es {falso_token}")
    agent_runtime._extraer_memoria_espontanea(db_session, "u1", "mi liga favorita es la Premier League")
    db_session.commit()
    assert db_session.query(AgentMemory).count() == 2
    contexto = agent_runtime._contexto(db_session, "u1", "")
    assert "ana@example.com" not in contexto and "Premier League" in contexto and falso_token not in contexto


# --- Predicción honesta --------------------------------------------------------------------------

DATOS_MOTOR = {"consenso": {
    "pick_final": "Local", "confianza_final": "MEDIA", "nivel": "FUERTE", "criterio_pick": "probabilidad_ponderada",
    "prob_ponderada": {"local": 0.512, "empate": 0.263, "visitante": 0.225},
    "modulos_en_consenso": ["poisson", "historico"], "modulos_disidentes": ["mercado"], "total_modulos": 3,
}}


def test_resumen_de_prediccion_trae_probabilidades_modulos_y_procedencia(monkeypatch):
    tasa = {"liga_codigo": "ARG", "partidos": 1673, "temporadas": ["2023"], "pct_local": 42.7, "pct_empate": 32.5, "pct_visitante": 24.7, "goles_por_partido": 2.03}
    monkeypatch.setattr("backend.api.services.modelo_historico.tasas_base_liga", lambda d: tasa)
    resumen = agent_tools.resumir_prediccion(DATOS_MOTOR, {"liga": "Liga Profesional", "local": "A", "visitante": "B"})
    assert resumen["prob_ponderada_pct"] == {"local": 51.2, "empate": 26.3, "visitante": 22.5}
    assert resumen["modulos_usados"] == ["poisson", "historico", "mercado"] and resumen["modulos_a_favor"] == 2
    assert resumen["tasa_base_liga"]["pct_local"] == 42.7 and "estimación" in resumen["procedencia"]
    sin = agent_tools.resumir_prediccion({"consenso": {"pick_final": "Sin pronóstico", "confianza_final": "SIN DATOS"}}, {})
    assert sin["pick"] is None


def _herramientas_falsas(monkeypatch, datos=DATOS_MOTOR):
    async def herramienta(nombre, argumentos, *, es_admin=False, authorization=None, usuario=None):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [{"match_id": "m1", "local": "Barcelona", "visitante": "PSG", "liga": "Champions"}]}
        return {"ok": True, "prediction": datos}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)


def test_prediccion_del_agente_muestra_probabilidades_y_no_gasta_ia_en_otras_tools(db_session, monkeypatch):
    _herramientas_falsas(monkeypatch)
    llamadas = []

    async def generar(prompt, max_tokens=700, rol="bot"):
        llamadas.append(prompt)
        return "Barcelona es favorito con 51.2% según el motor; es una estimación.", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    sin_ia = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "prediccion bot Barcelona vs PSG", None, "web", False, False))
    assert "51.2%" in sin_ia["respuesta"] and "Modelos usados" in sin_ia["respuesta"] and llamadas == []
    con_ia = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "prediccion bot Barcelona vs PSG", None, "web", True, False))
    assert len(llamadas) == 1 and "JSON verificado" in llamadas[0] and con_ia["modo"].startswith("ia ·")
    # Una herramienta deportiva sin redacción posible (listar ligas) ya no llama al LLM.
    asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "que ligas tienes", None, "web", True, False))
    assert len(llamadas) == 1


def test_redaccion_con_cifras_inventadas_se_descarta(db_session, monkeypatch):
    _herramientas_falsas(monkeypatch)

    async def generar(prompt, max_tokens=700, rol="bot"):
        return "Barcelona gana con 87% de probabilidad", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "prediccion bot Barcelona vs PSG", None, "web", True, False))
    assert "87" not in r["respuesta"] and "51.2%" in r["respuesta"] and "ia_descartada" in r["modo"]


def test_herramienta_que_falla_marca_la_ejecucion_como_failed(db_session, monkeypatch):
    async def herramienta(nombre, argumentos, *, es_admin=False, authorization=None, usuario=None):
        raise RuntimeError("bot caído")

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "que ligas tienes", None, "web", False, False))
    assert db_session.get(AgentRun, r["run_id"]).status == "failed"
    ok = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "hola", None, "web", False, False))
    assert db_session.get(AgentRun, ok["run_id"]).status == "succeeded"


# --- Router de dominio ---------------------------------------------------------------------------

def test_router_no_trata_politica_como_deportivo_y_cuotas_no_piden_via():
    assert agent_runtime._respuesta_reglas("quien ganara las elecciones", False)[2] is None
    assert agent_runtime._fuera_de_alcance("quién ganará las elecciones")
    assert agent_runtime._respuesta_reglas("quien gana Barcelona vs PSG", False)[2] == "agent.prediction_choice"
    assert agent_runtime._respuesta_reglas("cuotas Arsenal vs Chelsea", False)[2] == "sports.get_odds"
    assert agent_runtime._respuesta_reglas("que mercado y cuotas hay para Arsenal contra Chelsea", False)[2] == "sports.get_odds"
    assert agent_runtime._partido_desde_mensaje("que mercado y cuotas hay para Arsenal contra Chelsea") == ("Arsenal", "Chelsea")


# --- Aprendizaje -----------------------------------------------------------------------------------

def _politica(db, scope, creador, contenido, topic="alcance", estado="active"):
    db.add(AgentPolicyVersion(id=f"{scope}-{creador}-{topic}", scope=scope, topic_key=topic, version=1, status=estado, content_json=json.dumps(contenido), created_by=creador, created_en="x", activated_en="x"))
    db.commit()


def test_politica_aprobada_cambia_el_comportamiento_y_respeta_el_ambito(db_session):
    _politica(db_session, "global", "admin", {"bloquear_temas": ["tenis"], "instrucciones": "Responde breve."})
    _politica(db_session, "usuario", "ana", {"bloquear_temas": ["baloncesto"]}, topic="ana")
    _politica(db_session, "global", "admin", {"bloquear_temas": ["rugby"]}, topic="vieja", estado="superseded")
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "bob", "partidos de tenis de hoy", None, "web", False, False))
    assert r["herramienta"] == "agent.policy_block"
    assert asyncio.run(agent_runtime.procesar_mensaje(db_session, "ana", "partidos de baloncesto hoy", None, "web", False, False))["herramienta"] == "agent.policy_block"
    assert asyncio.run(agent_runtime.procesar_mensaje(db_session, "bob", "partidos de baloncesto hoy", None, "web", False, False))["herramienta"] != "agent.policy_block"
    assert agent_learning.tema_bloqueado("partido de rugby", agent_learning.politicas_activas(db_session, "bob")) is None
    assert agent_learning.politicas_activas(db_session, "bob")["instrucciones"] == ["Responde breve."]


def test_estadisticas_de_feedback_por_herramienta_y_modo(db_session):
    def run(id_, herramienta, modo):
        db_session.add(AgentRun(id=id_, user_id="u", output_json=json.dumps({"tool": herramienta, "mode": modo}), creado_en="x"))

    run("r1", "sports.predict", "reglas")
    run("r2", "sports.predict", "reglas")
    run("r3", "llm.respond", "ia · gemini/m")
    for run_id, rating in [("r1", 5), ("r2", 2), ("r3", 4), (None, 1)]:
        db_session.add(AgentFeedback(user_id="u", run_id=run_id, rating=rating, creado_en="x"))
    db_session.commit()
    stats = agent_learning.estadisticas_feedback(db_session)
    por_tool = {i["clave"]: i for i in stats["por_herramienta"]}
    assert stats["total_con_run"] == 3
    assert por_tool["sports.predict"]["tasa_pulgar_arriba"] == 0.5 and por_tool["llm.respond"]["tasa_pulgar_arriba"] == 1.0
    assert {i["clave"] for i in stats["por_modo"]} == {"reglas", "ia"}


# --- Orquestador -----------------------------------------------------------------------------------

@pytest.fixture()
def sesion_orquestador(monkeypatch, tmp_path):
    # Archivo temporal (no :memory:): los subagentes escriben desde hilos distintos.
    engine = create_engine(f"sqlite:///{tmp_path / 'orquestador.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine)
    monkeypatch.setattr(task_orchestrator, "SessionLocal", sesion)
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", False)
    return sesion


def test_reclamo_atomico_solo_gana_una_ejecucion(sesion_orquestador):
    tarea = task_orchestrator.crear_tarea("u", "agent.qa", {})
    with sesion_orquestador() as a, sesion_orquestador() as b:
        primera = task_orchestrator._reclamar(a, tarea.id)
        segunda = task_orchestrator._reclamar(b, tarea.id)
    assert primera is not None and segunda is None
    with sesion_orquestador() as db:
        assert db.get(AgentTask, tarea.id).attempt_count == 1


def test_agent_parallel_ejecuta_hijos_sin_detached_instance(sesion_orquestador, monkeypatch):
    async def capacidades():
        return {"available": True}

    monkeypatch.setattr(task_orchestrator, "consultar_capacidades_deportivas", capacidades)
    monkeypatch.setattr(task_orchestrator, "emitir_alerta", lambda *a, **k: None)
    tarea = task_orchestrator.crear_tarea("u", "agent.parallel", {"requests": [{"kind": "agent.qa", "payload": {}}, {"kind": "sports.capabilities", "payload": {}}, {"kind": "agent.qa", "payload": {}}]})
    task_orchestrator._ejecutar(tarea.id)
    with sesion_orquestador() as db:
        padre = db.get(AgentTask, tarea.id)
        assert padre.status == "succeeded", padre.error
        hijos = json.loads(padre.output_json)["children"]
        assert len(hijos) == 3 and all(h["status"] == "succeeded" for h in hijos)


def test_reencolar_no_duplica_la_misma_tarea(sesion_orquestador, monkeypatch):
    enviados = []
    monkeypatch.setattr(task_orchestrator.EXECUTOR, "submit", lambda fn, *args: enviados.append(args))
    tarea = task_orchestrator.crear_tarea("u", "agent.qa", {})
    task_orchestrator._EN_COLA.clear()
    task_orchestrator.reencolar_tareas_pendientes()
    task_orchestrator.reencolar_tareas_pendientes()
    assert enviados == [(tarea.id,)]
    task_orchestrator._EN_COLA.clear()


def test_tarea_agent_chat_usa_es_admin_guardado_no_el_del_payload(sesion_orquestador, monkeypatch):
    capturado = SimpleNamespace()

    async def procesar(db, user_id, mensaje, session_id, canal, usar_ia, es_admin, *a):
        capturado.es_admin = es_admin
        return {"respuesta": "ok"}

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", procesar)
    monkeypatch.setattr(task_orchestrator, "emitir_alerta", lambda *a, **k: None)
    tarea = task_orchestrator.crear_tarea("u", "agent.chat", {"message": "hola", "es_admin": True}, es_admin=False)
    task_orchestrator._ejecutar(tarea.id)
    assert capturado.es_admin is False


def test_politica_de_usuario_aprobada_rige_para_su_autor_y_no_para_el_admin_ni_pisa_a_otros(db_session):
    """Revisión de seguridad 2026-10-07: `created_by` de una política de ámbito usuario es su dueño (el autor de
    la propuesta), no el admin revisor; y aprobar la de un usuario no reemplaza la de otro con el mismo tema."""
    import json as _json

    from backend.api.models.agent_runtime import AgentPolicyVersion
    from backend.api.services import agent_learning

    def politica(pid, dueno, scope, tema):
        db_session.add(AgentPolicyVersion(
            id=pid, scope=scope, topic_key="alcance", version=1, status="active",
            content_json=_json.dumps({"bloquear_temas": [tema]}), created_by=dueno,
            created_en="2026-10-07T00:00:00+00:00", activated_en="2026-10-07T00:00:00+00:00"))

    politica("p-ana", "ana", "usuario", "criptomonedas")
    politica("p-beto", "beto", "usuario", "politica")
    politica("p-global", "admin", "global", "apuestas")
    politica("p-raro", "ana", "otro_ambito", "futbol")  # ámbito desconocido: no debe tratarse como global
    db_session.commit()

    ana = agent_learning.politicas_activas(db_session, "ana")["bloquear_temas"]
    beto = agent_learning.politicas_activas(db_session, "beto")["bloquear_temas"]
    admin = agent_learning.politicas_activas(db_session, "admin")["bloquear_temas"]

    assert ana == ["apuestas", "criptomonedas"] or sorted(ana) == ["apuestas", "criptomonedas"]
    assert sorted(beto) == ["apuestas", "politica"]
    assert admin == ["apuestas"]  # el admin no hereda las políticas privadas de otros
    assert all("futbol" not in lista for lista in (ana, beto, admin))
