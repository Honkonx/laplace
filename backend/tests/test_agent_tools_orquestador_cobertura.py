"""Cobertura de `agent_tools` (reintentos, errores y validaciones) y de `task_orchestrator`
(reintentos, cancelación, idempotencia, reencolado). Sin red, sin BD real y sin claves reales:
HTTP simulado con `httpx.MockTransport` y SQLite en memoria."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401
from backend.api.core.config import settings
from backend.api.db.session import Base
from backend.api.models.agent_runtime import AgentEvent, AgentTask
from backend.api.services import agent_guard, agent_tools, task_orchestrator
from backend.api.services.agent_guard import LimiteExcedido


_CLIENTE_REAL = httpx.AsyncClient


def _correr(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------------------------
# agent_tools
# --------------------------------------------------------------------------------------------

@pytest.fixture()
def herramientas(monkeypatch):
    agent_tools._READ_CACHE.clear()
    agent_tools._REQUEST_WINDOW.clear()
    agent_guard.resetear_contadores()
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "http://127.0.0.1:9001")
    yield
    agent_tools._READ_CACHE.clear()
    agent_tools._REQUEST_WINDOW.clear()
    agent_guard.resetear_contadores()


def _http_simulado(monkeypatch, manejador):
    """Reemplaza `httpx.AsyncClient` de `agent_tools` por uno con transporte simulado."""
    def fabrica(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(manejador)
        return _CLIENTE_REAL(*args, **kwargs)

    monkeypatch.setattr(agent_tools.httpx, "AsyncClient", fabrica)


def _guion(*pasos):
    """Manejador que consume `pasos` en orden (el último se repite): una Response o una excepción a lanzar."""
    llamadas = []
    cola = list(pasos)

    def manejador(request: httpx.Request):
        llamadas.append(request)
        paso = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(paso, Exception):
            raise paso
        return paso

    manejador.llamadas = llamadas
    return manejador


def test_limite_temporal_de_herramientas(herramientas):
    agent_tools._REQUEST_WINDOW[:] = [time.monotonic()] * agent_tools._MAX_REQUESTS_PER_MINUTE
    with pytest.raises(RuntimeError, match="Límite temporal"):
        agent_tools._controlar_limite()


def test_catalogo_oculta_herramientas_de_admin_al_usuario_normal():
    todas = {t["name"] for t in agent_tools.listar_herramientas_deportivas(es_admin=True)}
    visibles = {t["name"] for t in agent_tools.listar_herramientas_deportivas(es_admin=False)}
    assert {"sports.results", "sports.top_picks", "sports.publish"} <= todas - visibles
    assert "sports.predict" in visibles


def test_texto_argumento_valida_tipo_largo_y_requeridos():
    assert agent_tools._texto_argumento({"team": "  River "}, "team", "equipo") == "River"
    assert agent_tools._texto_argumento({"equipo": "Boca"}, "team", "equipo") == "Boca"
    assert agent_tools._texto_argumento({}, "team", requerido=False) is None
    assert agent_tools._texto_argumento({"team": "   "}, "team", requerido=False) is None
    with pytest.raises(ValueError, match="debe ser texto"):
        agent_tools._texto_argumento({"team": 5}, "team")
    with pytest.raises(ValueError, match="demasiado largo"):
        agent_tools._texto_argumento({"team": "x" * 201}, "team")
    with pytest.raises(ValueError, match="Falta el argumento team"):
        agent_tools._texto_argumento({}, "team")


def test_fecha_acepta_vacio_compacto_iso_y_rechaza_basura():
    assert agent_tools._fecha(None) == date.today().strftime("%Y%m%d")
    assert agent_tools._fecha("20261007") == "20261007"
    assert agent_tools._fecha("2026-10-07") == "20261007"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        agent_tools._fecha("mañana")


_STAGES = {"Stages": [
    "no-es-dict",
    {"Snm": "Premier League", "Events": [
        {"Eid": 1, "T1": [{"Nm": "Arsenal"}], "T2": [{"Nm": "Chelsea"}], "Esd": "20261007150000", "Eps": "NS"},
        "evento-roto",
    ]},
    {"CompN": "LaLiga", "Events": [{"Eid": 2, "T1": [{"Nm": "Real Madrid"}], "T2": [{"Nm": "Sevilla"}]}]},
]}


def test_filtrar_partidos_desde_stages_con_filtros_y_limite():
    todos = agent_tools._filtrar_partidos(_STAGES, {})
    assert [p["local"] for p in todos] == ["Arsenal", "Real Madrid"]
    assert agent_tools._filtrar_partidos(_STAGES, {"league": "laliga"})[0]["local"] == "Real Madrid"
    assert agent_tools._filtrar_partidos(_STAGES, {"team": "chelsea"})[0]["visitante"] == "Chelsea"
    assert agent_tools._filtrar_partidos(_STAGES, {"limit": 1}) == todos[:1]
    assert agent_tools._filtrar_partidos(_STAGES, {"league": "serie z"}) == []


def test_filtrar_partidos_con_lista_directa_ignora_basura():
    data = {"partidos": [{"local": "A", "visitante": "B", "liga": "X"}, 7, None]}
    assert agent_tools._filtrar_partidos(data, {"equipo": "a"}) == [{"local": "A", "visitante": "B", "liga": "X"}]
    assert agent_tools._filtrar_partidos({"partidos": "no-lista"}, {}) == []


def test_get_cachea_la_respuesta_y_no_repite_la_llamada(herramientas, monkeypatch):
    manejador = _guion(httpx.Response(200, json={"ok": 1}))
    _http_simulado(monkeypatch, manejador)
    assert _correr(agent_tools._get("/x", {"a": 1})) == {"ok": 1}
    assert _correr(agent_tools._get("/x", {"a": 1})) == {"ok": 1}
    assert len(manejador.llamadas) == 1


def test_get_reintenta_hasta_3_veces_ante_5xx_y_luego_informa(herramientas, monkeypatch):
    manejador = _guion(httpx.Response(503))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(RuntimeError, match="3 intentos"):
        _correr(agent_tools._get("/caido"))
    assert len(manejador.llamadas) == 3


def test_get_se_recupera_tras_un_timeout_y_un_corte_de_red(herramientas, monkeypatch):
    manejador = _guion(httpx.ReadTimeout("lento"), httpx.ConnectError("sin red"), httpx.Response(200, json={"v": 2}))
    _http_simulado(monkeypatch, manejador)
    assert _correr(agent_tools._get("/lento")) == {"v": 2}
    assert len(manejador.llamadas) == 3


def test_get_no_reintenta_un_4xx(herramientas, monkeypatch):
    manejador = _guion(httpx.Response(404))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(httpx.HTTPStatusError):
        _correr(agent_tools._get("/no-existe"))
    assert len(manejador.llamadas) == 1


def test_post_no_reenvia_credenciales_a_un_host_no_confiable(herramientas, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "https://externo.example.com")
    manejador = _guion(httpx.Response(200, json={}))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(PermissionError, match="no es de confianza"):
        _correr(agent_tools._post("/p", {}, authorization="Bearer secreto"))
    assert manejador.llamadas == []


def test_post_un_timeout_no_se_reintenta(herramientas, monkeypatch):
    manejador = _guion(httpx.ReadTimeout("45 s"))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(RuntimeError, match="tardó demasiado"):
        _correr(agent_tools._post("/p", {"a": 1}))
    assert len(manejador.llamadas) == 1


def test_post_reintenta_una_vez_ante_5xx_y_luego_informa(herramientas, monkeypatch):
    manejador = _guion(httpx.Response(502))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(RuntimeError, match="2 intentos"):
        _correr(agent_tools._post("/p", {}))
    assert len(manejador.llamadas) == 2


def test_post_se_recupera_tras_un_corte_de_red_y_envia_la_autorizacion(herramientas, monkeypatch):
    manejador = _guion(httpx.ConnectError("corte"), httpx.Response(200, json={"hecho": True}))
    _http_simulado(monkeypatch, manejador)
    assert _correr(agent_tools._post("/p", {"a": 1}, {"q": "1"}, authorization="Bearer t")) == {"hecho": True}
    assert len(manejador.llamadas) == 2
    assert manejador.llamadas[-1].headers["authorization"] == "Bearer t"
    assert json.loads(manejador.llamadas[-1].content) == {"a": 1}


def test_post_no_reintenta_un_4xx(herramientas, monkeypatch):
    manejador = _guion(httpx.Response(422))
    _http_simulado(monkeypatch, manejador)
    with pytest.raises(httpx.HTTPStatusError):
        _correr(agent_tools._post("/p", {}))
    assert len(manejador.llamadas) == 1


def test_porcentajes_y_tasa_base_nunca_inventan(monkeypatch):
    assert agent_tools._porcentajes({"local": 0.5, "empate": 0.25, "visitante": 0.25}) == {"local": 50.0, "empate": 25.0, "visitante": 25.0}
    assert agent_tools._porcentajes({"local": 0.5}) is None
    assert agent_tools._porcentajes({"local": "x", "empate": 1, "visitante": 1}) is None
    assert agent_tools._porcentajes(None) is None

    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "tasas_base_liga", lambda partido: {"liga_codigo": "E0", "partidos": 900, "pct_local": 45.0})
    assert agent_tools._tasa_base({})["partidos"] == 900
    monkeypatch.setattr(modelo_historico, "tasas_base_liga", lambda partido: None)
    assert agent_tools._tasa_base({}) is None

    def rompe(partido):
        raise RuntimeError("sin artefactos")

    monkeypatch.setattr(modelo_historico, "tasas_base_liga", rompe)
    assert agent_tools._tasa_base({}) is None


def test_resumir_prediccion_con_pick_y_sin_pick(monkeypatch):
    monkeypatch.setattr(agent_tools, "_tasa_base", lambda partido: None)
    con_pick = agent_tools.resumir_prediccion({"consenso": {
        "pick_final": "Local", "confianza_final": "ALTA", "nivel": 2, "prob_ponderada": {"local": 0.6, "empate": 0.2, "visitante": 0.2},
        "modulos_en_consenso": ["odds"], "modulos_disidentes": ["historico"], "criterio_pick": "mayor prob",
    }}, {})
    assert con_pick["pick"] == "Local" and con_pick["modulos_usados"] == ["odds", "historico"]
    assert con_pick["prob_ponderada_pct"]["local"] == 60.0 and con_pick["total_modulos"] == 2
    sin_pick = agent_tools.resumir_prediccion({
        "consenso": {"pick_final": "Sin pronóstico propio"}, "motivos_sin_pronostico": ["a", "b", "c", "d"],
        "referencia_tasa_base": {"pct_local": 40},
    }, {})
    assert sin_pick["pick"] is None and sin_pick["motivos_sin_pronostico"] == ["a", "b", "c"]
    assert sin_pick["referencia_tasa_base"] == {"pct_local": 40}
    vacio = agent_tools.resumir_prediccion("basura", {})
    assert vacio["pick"] is None and vacio["motivos_sin_pronostico"] == [] and vacio["referencia_tasa_base"] is None
    assert agent_tools.resumir_prediccion({"consenso": "roto"}, {})["pick"] is None


def test_capacidades_deportivas_disponibles_y_caidas(herramientas, monkeypatch):
    _http_simulado(monkeypatch, _guion(httpx.Response(200, json={"component": "sports"})))
    ok = _correr(agent_tools.consultar_capacidades_deportivas())
    assert ok["available"] is True and ok["capabilities"] == {"component": "sports"}
    _http_simulado(monkeypatch, _guion(httpx.ConnectError("apagado")))
    caido = _correr(agent_tools.consultar_capacidades_deportivas())
    assert caido == {"available": False, "url": "http://127.0.0.1:9001/capabilities", "reason": "ConnectError"}


def _ejecutar(nombre, argumentos=None, **kwargs):
    return _correr(agent_tools.ejecutar_herramienta_deportiva(nombre, argumentos or {}, **kwargs))


def test_ejecutar_rechaza_herramienta_desconocida_y_exige_rol(herramientas):
    with pytest.raises(ValueError, match="no registrada"):
        _ejecutar("sports.inventada")
    with pytest.raises(PermissionError, match="administrador"):
        _ejecutar("sports.publish", {"publish": True})
    assert _ejecutar("sports.publish", {"publish": True}, es_admin=True) == {"ok": False, "requires_confirmation": True, "tool": "sports.publish"}


def test_ejecutar_herramientas_de_conocimiento_no_usan_la_red(herramientas, monkeypatch):
    for modulo, funcion in (("conocimiento_equipos", "perfil_equipo"), ("conocimiento_referencia", "perfil_liga"), ("conocimiento_referencia", "buscar_glosario")):
        monkeypatch.setattr(getattr(agent_tools, modulo), funcion, lambda *a, **k: {"estado": "ok"})
    for texto in ("texto_equipo", "texto_liga", "texto_glosario"):
        monkeypatch.setattr(agent_tools.conocimiento_texto, texto, lambda data: "texto")
    for nombre, args in (("knowledge.team_profile", {"team": "River", "league": "Liga X"}), ("knowledge.league_profile", {"liga": "Liga X"}), ("knowledge.glossary", {"term": "RPS"})):
        r = _ejecutar(nombre, args)
        assert r["ok"] is True and r["estado"] == "ok" and r["texto"] == "texto"
    with pytest.raises(ValueError, match="Falta el argumento"):
        _ejecutar("knowledge.glossary", {})


def test_ejecutar_list_leagues_devuelve_el_catalogo_real():
    r = _ejecutar("sports.list_leagues")
    assert r["ok"] is True and r["leagues"] and {"slug", "avg_goals", "standings", "odds"} <= set(r["leagues"][0])


def test_ejecutar_fixtures_top_picks_y_get_match(herramientas, monkeypatch):
    rutas = []

    async def falso_get(path, params=None):
        rutas.append((path, params))
        if path.endswith("/top-picks"):
            return {"picks": [{"local": "A"}]}
        return {"partidos": [{"match_id": "7", "local": "River", "visitante": "Boca", "liga": "Liga X"}, {"id": 8, "local": "C", "visitante": "D"}]}

    monkeypatch.setattr(agent_tools, "_get", falso_get)
    fixtures = _ejecutar("sports.list_fixtures", {"date": "2026-10-07", "team": "river"})
    assert fixtures["date"] == "20261007" and len(fixtures["fixtures"]) == 1
    assert _ejecutar("sports.list_top_picks", {"date": "20261007"})["picks"] == [{"local": "A"}]
    assert _ejecutar("sports.get_match", {"match_id": "7", "date": "20261007"})["match"]["local"] == "River"
    assert _ejecutar("sports.get_match", {"match_id": "8"})["match"]["local"] == "C"
    assert _ejecutar("sports.get_match", {"match_id": "99"})["match"] is None
    with pytest.raises(ValueError, match="requiere match_id"):
        _ejecutar("sports.get_match", {})
    assert ("/api/v1/web/top-picks", {"date": "20261007"}) in rutas


_ARGS_PREDECIR = {"match_id": "7", "local": "River", "visitante": "Boca", "league": "Liga X", "date": "2026-10-07"}


def test_ejecutar_predict_valida_argumentos_y_sesion(herramientas, monkeypatch):
    with pytest.raises(ValueError, match="requiere: match_id, local"):
        _ejecutar("sports.predict", {"visitante": "Boca", "league": "L"})
    with pytest.raises(PermissionError, match="sesión de usuario"):
        _ejecutar("sports.predict", _ARGS_PREDECIR)

    enviado = {}

    async def falso_post(path, payload, params=None, authorization=None):
        if path == "/api/v1/prediccion-web":  # la consulta al modelo Laplace (/api/v1/ml/predict) no es la del bot
            enviado.update(path=path, payload=payload, authorization=authorization)
        return {"consenso": {"pick_final": "Local"}, "odds_info": {"1": 2.0}}

    monkeypatch.setattr(agent_tools, "_post", falso_post)
    monkeypatch.setattr(agent_tools, "_tasa_base", lambda partido: None)
    r = _ejecutar("sports.predict", _ARGS_PREDECIR, authorization="Bearer x")
    assert r["resumen"]["pick"] == "Local" and enviado["payload"]["fecha"] == "20261007" and enviado["payload"]["liga"] == "Liga X"
    odds = _ejecutar("sports.get_odds", _ARGS_PREDECIR, authorization="Bearer x")
    assert odds == {"ok": True, "tool": "sports.get_odds", "match_id": "7", "odds": {"1": 2.0}}


def test_ejecutar_predict_aplica_tope_al_usuario_normal_y_no_al_admin(herramientas, monkeypatch):
    monkeypatch.setenv("AGENT_PREDICCIONES_MAX_POR_MINUTO", "1")

    async def falso_post(*args, **kwargs):
        return {"consenso": {}}

    monkeypatch.setattr(agent_tools, "_post", falso_post)
    _ejecutar("sports.predict", _ARGS_PREDECIR, authorization="Bearer x", usuario="u1")
    with pytest.raises(LimiteExcedido):
        _ejecutar("sports.predict", _ARGS_PREDECIR, authorization="Bearer x", usuario="u1")
    for _ in range(3):
        _ejecutar("sports.predict", _ARGS_PREDECIR, authorization="Bearer x", usuario="admin", es_admin=True)


def test_ejecutar_acciones_de_admin_aprobadas(herramientas, monkeypatch):
    llamadas = []

    async def falso_post(path, payload, params=None, authorization=None):
        llamadas.append((path, payload, params))
        return {"hecho": True}

    monkeypatch.setattr(agent_tools, "_post", falso_post)
    r = _ejecutar("sports.results", {"fixture_ids": [1], "date": "2026-10-07"}, es_admin=True, aprobado=True)
    assert r["result"] == {"hecho": True} and llamadas[-1][1] == {"fixture_ids": [1], "fecha": "2026-10-07"}
    _ejecutar("sports.top_picks", {"publish": True}, es_admin=True, aprobado=True)
    assert llamadas[-1][2] == {"publicar": False}  # top_picks nunca publica
    _ejecutar("sports.publish", {"publish": True}, es_admin=True, aprobado=True)
    assert llamadas[-1][2] == {"publicar": True}
    with pytest.raises(ValueError, match="publish=true"):
        _ejecutar("sports.publish", {"publish": "si"}, es_admin=True, aprobado=True)


def test_ejecutar_herramienta_en_catalogo_pero_sin_implementar(herramientas, monkeypatch):
    nueva = agent_tools.SportsTool("sports.fantasma", "x", True, False)
    monkeypatch.setattr(agent_tools, "SPORTS_TOOLS", agent_tools.SPORTS_TOOLS + (nueva,))
    with pytest.raises(ValueError, match="no implementada"):
        _ejecutar("sports.fantasma")


# --------------------------------------------------------------------------------------------
# task_orchestrator
# --------------------------------------------------------------------------------------------

class _EjecutorFalso:
    def __init__(self):
        self.enviados = []

    def submit(self, funcion, *args):
        self.enviados.append((funcion, args))


class _Entorno:
    pass


def _leer(sesion, task_id):
    with sesion() as db:
        item = db.get(AgentTask, task_id)
        db.expunge(item)
        return item


def _eventos(sesion, task_id):
    with sesion() as db:
        return [ev.event_type for ev in db.query(AgentEvent).filter(AgentEvent.task_id == task_id).order_by(AgentEvent.id).all()]


@pytest.fixture()
def orq(monkeypatch, tmp_path):
    # Archivo temporal y no `:memory:` + StaticPool: los subagentes en paralelo corren en hilos distintos y StaticPool les da UNA sola conexión de sqlite3, que no tolera uso
    # concurrente (`sqlite3.InterfaceError: bad parameter or other API misuse`, intermitente: fallaba ~2 de cada 10 corridas). Con archivo cada hilo tiene su conexión, como en producción.
    engine = create_engine(f"sqlite:///{tmp_path / 'orquestador.db'}", connect_args={"check_same_thread": False, "timeout": 15})
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine)
    e = _Entorno()
    e.sesion, e.ejecutor, e.alertas = sesion, _EjecutorFalso(), []
    e.tarea = lambda id_: _leer(sesion, id_)
    e.eventos = lambda id_: _eventos(sesion, id_)
    monkeypatch.setattr(task_orchestrator, "SessionLocal", sesion)
    monkeypatch.setattr(task_orchestrator, "EXECUTOR", e.ejecutor)
    monkeypatch.setattr(task_orchestrator, "emitir_alerta", lambda tipo, datos: e.alertas.append((tipo, datos)))
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", False)
    task_orchestrator._EN_COLA.clear()
    agent_guard.resetear_contadores()
    yield e
    task_orchestrator._EN_COLA.clear()
    agent_guard.resetear_contadores()


def _fijar(orq, task_id, **campos):
    with orq.sesion() as db:
        item = db.get(AgentTask, task_id)
        for clave, valor in campos.items():
            setattr(item, clave, valor)
        db.commit()


def test_crear_tarea_persiste_fuerza_es_admin_y_acota_limites(orq):
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola", "es_admin": True}, max_attempts=9, timeout_seconds=1)
    fila = orq.tarea(t.id)
    assert fila.status == "queued" and (fila.max_attempts, fila.timeout_seconds) == (2, 5)
    assert json.loads(fila.input_json)["es_admin"] is False
    assert orq.eventos(t.id) == ["task.queued"]
    assert orq.ejecutor.enviados == []  # AGENT_LOCAL_EXECUTOR desactivado: lo toma el worker


def test_crear_tarea_rechaza_tipos_fuera_del_registro(orq):
    with pytest.raises(ValueError, match="no permitido"):
        task_orchestrator.crear_tarea("u1", "shell.exec", {})


def test_crear_tarea_es_idempotente_por_usuario_y_clave(orq):
    a = task_orchestrator.crear_tarea("u1", "agent.qa", {}, idempotency_key="k1")
    b = task_orchestrator.crear_tarea("u1", "agent.qa", {}, idempotency_key="k1")
    otro = task_orchestrator.crear_tarea("u2", "agent.qa", {}, idempotency_key="k1")
    assert a.id == b.id and otro.id != a.id
    with orq.sesion() as db:
        assert db.query(AgentTask).count() == 2


def test_crear_tarea_respeta_el_tope_de_tareas_activas(orq, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_TAREAS_ACTIVAS", "1")
    task_orchestrator.crear_tarea("u1", "agent.qa", {})
    with pytest.raises(LimiteExcedido):
        task_orchestrator.crear_tarea("u1", "agent.qa", {})
    task_orchestrator.crear_tarea("u2", "agent.qa", {})  # el tope es por usuario


def test_crear_tarea_con_ejecutor_local_la_encola(orq, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", True)
    t = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    assert orq.ejecutor.enviados == [(task_orchestrator._ejecutar_y_liberar, (t.id,))]
    assert t.id in task_orchestrator._EN_COLA


def test_encolar_no_duplica_y_liberar_vuelve_a_permitirlo(orq, monkeypatch):
    task_orchestrator._encolar("t1")
    task_orchestrator._encolar("t1")
    assert len(orq.ejecutor.enviados) == 1
    ejecutadas = []
    monkeypatch.setattr(task_orchestrator, "_ejecutar", lambda task_id: ejecutadas.append(task_id))
    task_orchestrator._ejecutar_y_liberar("t1")
    assert ejecutadas == ["t1"] and "t1" not in task_orchestrator._EN_COLA
    task_orchestrator._encolar("t1")
    assert len(orq.ejecutor.enviados) == 2


def test_liberar_la_cola_aunque_la_ejecucion_falle(orq, monkeypatch):
    def rompe(task_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_orchestrator, "_ejecutar", rompe)
    task_orchestrator._EN_COLA.add("t9")
    with pytest.raises(RuntimeError):
        task_orchestrator._ejecutar_y_liberar("t9")
    assert "t9" not in task_orchestrator._EN_COLA


def test_recuperar_tareas_interrumpidas_marca_solo_las_running(orq):
    corriendo = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    en_cola = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    _fijar(orq, corriendo.id, status="running")
    assert task_orchestrator.recuperar_tareas_interrumpidas() == 1
    assert orq.tarea(corriendo.id).status == "failed" and "reiniciado" in orq.tarea(corriendo.id).error
    assert orq.tarea(en_cola.id).status == "queued"
    assert task_orchestrator.recuperar_tareas_interrumpidas() == 0


def test_reencolar_pendientes_ignora_canceladas_y_en_marcha(orq):
    pendiente = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    cancelada = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    corriendo = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    _fijar(orq, cancelada.id, cancel_requested=1)
    _fijar(orq, corriendo.id, status="running")
    assert task_orchestrator.reencolar_tareas_pendientes() == 1
    assert [args for _, args in orq.ejecutor.enviados] == [(pendiente.id,)]
    assert task_orchestrator.reencolar_tareas_pendientes() == 1  # ya en cola: no se duplica
    assert len(orq.ejecutor.enviados) == 1


def test_listar_subagentes_solo_expone_el_registro_cerrado():
    subagentes = task_orchestrator.listar_subagentes()
    assert {s["id"] for s in subagentes} == set(task_orchestrator.SUBAGENT_REGISTRY) and all(s["enabled"] for s in subagentes)


def test_cancelar_tarea_en_cola_la_cancela_y_arrastra_a_los_hijos(orq):
    padre = task_orchestrator.crear_tarea("u1", "agent.parallel", {})
    hijo_cola = task_orchestrator.crear_tarea("u1", "agent.qa", {}, padre.id)
    hijo_corriendo = task_orchestrator.crear_tarea("u1", "agent.qa", {}, padre.id)
    _fijar(orq, hijo_corriendo.id, status="running")
    assert task_orchestrator.cancelar_tarea(padre.id, "u1") is True
    assert orq.tarea(padre.id).status == "cancelled" and orq.tarea(padre.id).cancel_requested == 1
    assert orq.tarea(hijo_cola.id).status == "cancelled"
    corriendo = orq.tarea(hijo_corriendo.id)
    assert corriendo.status == "running" and corriendo.cancel_requested == 1
    assert "task.cancel_requested" in orq.eventos(padre.id)


def test_cancelar_tarea_ajena_inexistente_o_terminada_devuelve_false(orq):
    t = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    assert task_orchestrator.cancelar_tarea(t.id, "otro-usuario") is False
    assert task_orchestrator.cancelar_tarea("no-existe", "u1") is False
    for estado in ("succeeded", "failed", "partial", "cancelled"):
        _fijar(orq, t.id, status=estado)
        assert task_orchestrator.cancelar_tarea(t.id, "u1") is False
    assert orq.tarea(t.id).cancel_requested == 0


def test_ejecutar_chat_exitoso_guarda_la_salida(orq, monkeypatch):
    vistos = {}

    async def falso(db, user_id, mensaje, session_id, canal, usar_ia, es_admin):
        vistos.update(user_id=user_id, mensaje=mensaje, canal=canal, usar_ia=usar_ia, es_admin=es_admin)
        return {"respuesta": "ok"}

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", falso)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola", "usar_ia": True}, es_admin=True)
    task_orchestrator._ejecutar(t.id)
    fila = orq.tarea(t.id)
    assert fila.status == "succeeded" and json.loads(fila.output_json) == {"respuesta": "ok"} and fila.attempt_count == 1
    assert vistos == {"user_id": "u1", "mensaje": "hola", "canal": "task", "usar_ia": True, "es_admin": True}
    assert orq.eventos(t.id) == ["task.queued", "task.running", "task.succeeded"]
    assert orq.alertas == []


def test_ejecutar_dos_veces_la_misma_tarea_no_la_repite(orq, monkeypatch):
    llamadas = []

    async def falso(*args):
        llamadas.append(1)
        return {}

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", falso)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"})
    task_orchestrator._ejecutar(t.id)
    task_orchestrator._ejecutar(t.id)
    assert len(llamadas) == 1 and orq.tarea(t.id).attempt_count == 1


def test_ejecutar_qa_y_capacidades_deportivas(orq, monkeypatch):
    async def disponible():
        return {"available": True}

    monkeypatch.setattr(task_orchestrator, "consultar_capacidades_deportivas", disponible)
    qa = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    caps = task_orchestrator.crear_tarea("u1", "sports.capabilities", {})
    task_orchestrator._ejecutar(qa.id)
    task_orchestrator._ejecutar(caps.id)
    assert json.loads(orq.tarea(qa.id).output_json)["status"] == "passed"
    assert json.loads(orq.tarea(caps.id).output_json) == {"available": True}

    async def caido():
        return {"available": False}

    monkeypatch.setattr(task_orchestrator, "consultar_capacidades_deportivas", caido)
    degradada = task_orchestrator.crear_tarea("u1", "agent.qa", {})
    task_orchestrator._ejecutar(degradada.id)
    assert json.loads(orq.tarea(degradada.id).output_json)["status"] == "degraded"


def test_ejecutar_con_fallo_reencola_hasta_agotar_intentos_y_alerta(orq, monkeypatch):
    async def falla(*args):
        raise ConnectionError("sin red")

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", falla)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"}, max_attempts=2)
    task_orchestrator._ejecutar(t.id)
    fila = orq.tarea(t.id)
    assert fila.status == "queued" and fila.attempt_count == 1 and fila.terminado_en is None and "ConnectionError" in fila.error
    assert orq.ejecutor.enviados == [(task_orchestrator._ejecutar, (t.id,))]
    assert "task.retry_scheduled" in orq.eventos(t.id) and orq.alertas == []

    task_orchestrator._ejecutar(t.id)  # segundo y último intento
    fila = orq.tarea(t.id)
    assert fila.status == "failed" and fila.attempt_count == 2 and fila.terminado_en
    assert orq.eventos(t.id)[-1] == "task.failed"
    assert orq.alertas == [("agent.task_failed", {"task_id": t.id, "kind": "agent.chat", "error_type": "ConnectionError"})]
    assert len(orq.ejecutor.enviados) == 1  # no hay un tercer intento


def test_ejecutar_con_un_solo_intento_falla_de_inmediato(orq, monkeypatch):
    async def falla(*args):
        raise RuntimeError("x")

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", falla)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"}, max_attempts=1)
    task_orchestrator._ejecutar(t.id)
    assert orq.tarea(t.id).status == "failed" and orq.ejecutor.enviados == []


def test_ejecutar_respeta_el_timeout_de_la_tarea(orq, monkeypatch):
    async def lenta(*args):
        await asyncio.sleep(30)

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", lenta)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"}, max_attempts=1)
    _fijar(orq, t.id, timeout_seconds=0)
    task_orchestrator._ejecutar(t.id)
    fila = orq.tarea(t.id)
    assert fila.status == "failed" and fila.error.startswith("TimeoutError")


def test_ejecutar_cancelada_durante_la_marcha_termina_cancelada_sin_reintento(orq, monkeypatch):
    async def cancela_y_falla(db, *args):
        db.query(AgentTask).one().cancel_requested = 1
        raise RuntimeError("interrumpida")

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", cancela_y_falla)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"}, max_attempts=2)
    task_orchestrator._ejecutar(t.id)
    assert orq.tarea(t.id).status == "cancelled" and orq.ejecutor.enviados == [] and orq.alertas == []


def test_ejecutar_tarea_en_cola_con_cancelacion_pedida_se_cancela_sin_correr(orq, monkeypatch):
    async def no_debe_correr(*args):
        raise AssertionError("no debe ejecutarse")

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", no_debe_correr)
    t = task_orchestrator.crear_tarea("u1", "agent.chat", {"message": "hola"})
    _fijar(orq, t.id, cancel_requested=1)
    task_orchestrator._ejecutar(t.id)
    assert orq.tarea(t.id).status == "cancelled" and "task.cancelled" in orq.eventos(t.id)
    task_orchestrator._ejecutar("no-existe")  # no lanza


def test_ejecutar_operacion_desconocida_falla_con_motivo(orq):
    t = task_orchestrator.crear_tarea("u1", "agent.qa", {}, max_attempts=1)
    _fijar(orq, t.id, kind="shell.exec")
    task_orchestrator._ejecutar(t.id)
    fila = orq.tarea(t.id)
    assert fila.status == "failed" and "Tarea no registrada" in fila.error


def test_paralelo_exitoso_y_parcial(orq, monkeypatch):
    async def disponible():
        return {"available": True}

    monkeypatch.setattr(task_orchestrator, "consultar_capacidades_deportivas", disponible)
    padre = task_orchestrator.crear_tarea("u1", "agent.parallel", {"requests": [{"kind": "agent.qa"}, {"kind": "sports.capabilities", "payload": {}}]})
    task_orchestrator._ejecutar(padre.id)
    fila = orq.tarea(padre.id)
    salida = json.loads(fila.output_json)
    assert fila.status == "succeeded" and salida["subagents"] == 2 and {c["status"] for c in salida["children"]} == {"succeeded"}
    assert "subagent.created" in [e for h in salida["children"] for e in orq.eventos(h["id"])]

    async def falla(*args):
        raise RuntimeError("hijo roto")

    monkeypatch.setattr(task_orchestrator, "procesar_mensaje", falla)
    padre2 = task_orchestrator.crear_tarea("u1", "agent.parallel", {"requests": [{"kind": "agent.qa"}, {"kind": "agent.chat", "payload": {"message": "x"}}]})
    task_orchestrator._ejecutar(padre2.id)
    fila2 = orq.tarea(padre2.id)
    assert fila2.status == "partial"
    assert sorted(c["status"] for c in json.loads(fila2.output_json)["children"]) == ["failed", "succeeded"]


@pytest.mark.parametrize("requests_", [[], "no-lista", [{"kind": "agent.qa"}] * 5, [{"kind": "agent.parallel"}], ["texto"]])
def test_paralelo_valida_el_fan_out_cerrado(orq, requests_):
    with pytest.raises(ValueError):
        task_orchestrator._ejecutar_paralelo("padre", "u1", {"requests": requests_})
    with orq.sesion() as db:
        assert db.query(AgentTask).count() == 0
