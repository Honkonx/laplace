"""`agent_main.py` (fábrica de la app independiente del agente) y `agent_worker.py` (bucle del worker).
Sin red, sin Telegram real y sin la BD real: todo lo externo se reemplaza."""
from __future__ import annotations

import runpy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import agent_main, agent_worker
from backend.api.bot import laplace_agent_bot
from backend.api.core.config import settings
from backend.api.services import task_orchestrator


class _BotFalso:
    def __init__(self):
        self.pasos = []
        self.updater = SimpleNamespace(start_polling=self._async("polling"), stop=self._async("updater.stop"))

    def _async(self, nombre):
        async def paso():
            self.pasos.append(nombre)

        return paso

    async def initialize(self):
        self.pasos.append("initialize")

    async def start(self):
        self.pasos.append("start")

    async def stop(self):
        self.pasos.append("stop")

    async def shutdown(self):
        self.pasos.append("shutdown")


class _Sesion:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


@pytest.fixture()
def arranque(monkeypatch):
    """Neutraliza lo que `lifespan` toca fuera del proceso y registra qué se llamó."""
    registro = {"recuperadas": 0, "reencoladas": 0, "sincronizadas": 0}

    def recuperar():
        registro["recuperadas"] += 1
        return 0

    def reencolar():
        registro["reencoladas"] += 1
        return 0

    def sincronizar(db):
        registro["sincronizadas"] += 1

    monkeypatch.setattr(agent_main, "recuperar_tareas_interrumpidas", recuperar)
    monkeypatch.setattr(agent_main, "reencolar_tareas_pendientes", reencolar)
    monkeypatch.setattr(agent_main, "sincronizar_conocimiento_json", sincronizar)
    monkeypatch.setattr(agent_main, "SessionLocal", lambda: _Sesion())
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", False)
    return registro


def _arrancar():
    """Entra y sale del lifespan como lo hace uvicorn."""
    with TestClient(agent_main.app) as cliente:
        return cliente.get("/health")


def test_arranque_sin_token_no_inicia_telegram_y_recupera_tareas(arranque, monkeypatch):
    def no_debe_construirse():
        raise AssertionError("sin token no se construye el bot")

    monkeypatch.setattr(laplace_agent_bot, "construir_app", no_debe_construirse)
    respuesta = _arrancar()
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok", "component": "agent", "version": agent_main.app.version}
    assert arranque == {"recuperadas": 1, "reencoladas": 0, "sincronizadas": 1}


def test_arranque_con_ejecutor_local_reencola_las_tareas_pendientes(arranque, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_LOCAL_EXECUTOR", True)
    _arrancar()
    assert arranque["reencoladas"] == 1


def test_arranque_con_token_inicia_y_apaga_el_bot_en_orden(arranque, monkeypatch):
    bot = _BotFalso()
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "token-de-prueba")
    monkeypatch.setattr(laplace_agent_bot, "construir_app", lambda: bot)
    _arrancar()
    assert bot.pasos == ["initialize", "start", "polling", "updater.stop", "stop", "shutdown"]


def test_si_el_bot_no_arranca_la_api_del_agente_sigue_disponible(arranque, monkeypatch):
    class _BotQueFalla(_BotFalso):
        async def initialize(self):
            raise RuntimeError("token inválido")

    bot = _BotQueFalla()
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "token-de-prueba")
    monkeypatch.setattr(laplace_agent_bot, "construir_app", lambda: bot)
    assert _arrancar().status_code == 200
    assert bot.pasos == []  # no se intenta apagar un bot que nunca arrancó


def test_si_construir_el_bot_lanza_la_api_sigue_disponible(arranque, monkeypatch):
    def rompe():
        raise RuntimeError("AGENT_TELEGRAM_BOT_TOKEN no está configurado")

    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(laplace_agent_bot, "construir_app", rompe)
    assert _arrancar().status_code == 200


def test_si_falla_la_sincronizacion_del_conocimiento_el_agente_arranca(arranque, monkeypatch):
    def rompe(db):
        raise OSError("knowledge/ ilegible")

    monkeypatch.setattr(agent_main, "sincronizar_conocimiento_json", rompe)
    assert _arrancar().status_code == 200
    assert arranque["recuperadas"] == 1


def test_capabilities_declara_independencia_y_extension_opcional(arranque):
    with TestClient(agent_main.app) as cliente:
        cuerpo = cliente.get("/capabilities").json()
    assert cuerpo["component"] == "agent" and cuerpo["independent"] is True
    assert {"chat", "memory", "tasks", "subagents"} <= set(cuerpo["capabilities"])
    assert cuerpo["optional_extensions"] == ["sports-bot"]


def test_la_app_monta_el_router_del_agente():
    rutas = {ruta.path for ruta in agent_main.app.routes}
    assert {"/health", "/capabilities", "/dependencies/sports", "/api/v1/agent/chat"} <= rutas


def _cliente_http_falso(monkeypatch, manejador):
    real = httpx.AsyncClient

    def fabrica(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(manejador)
        return real(*args, **kwargs)

    monkeypatch.setattr(agent_main.httpx, "AsyncClient", fabrica)


def test_dependencia_deportiva_disponible(arranque, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_BACKEND_URL", "http://127.0.0.1:9001/")
    _cliente_http_falso(monkeypatch, lambda request: httpx.Response(200, json={"component": "sports"}))
    with TestClient(agent_main.app) as cliente:
        cuerpo = cliente.get("/dependencies/sports").json()
    assert cuerpo == {"available": True, "url": "http://127.0.0.1:9001", "capabilities": {"component": "sports"}}


@pytest.mark.parametrize("fallo,motivo", [
    (httpx.ConnectError("apagado"), "ConnectError"),
    (httpx.ReadTimeout("lento"), "ReadTimeout"),
])
def test_dependencia_deportiva_caida_se_informa_sin_romper(arranque, monkeypatch, fallo, motivo):
    def manejador(request):
        raise fallo

    _cliente_http_falso(monkeypatch, manejador)
    with TestClient(agent_main.app) as cliente:
        cuerpo = cliente.get("/dependencies/sports").json()
    assert cuerpo["available"] is False and cuerpo["reason"] == motivo


def test_dependencia_deportiva_con_error_http_cuenta_como_no_disponible(arranque, monkeypatch):
    _cliente_http_falso(monkeypatch, lambda request: httpx.Response(503))
    with TestClient(agent_main.app) as cliente:
        cuerpo = cliente.get("/dependencies/sports").json()
    assert cuerpo["available"] is False and cuerpo["reason"] == "HTTPStatusError"


# --------------------------------------------------------------------------------------------
# agent_worker
# --------------------------------------------------------------------------------------------

class _FinDelBucle(Exception):
    pass


def test_worker_reencola_y_duerme_2_segundos_en_cada_vuelta(monkeypatch):
    reencolados, pausas = [], []

    def reencolar():
        reencolados.append(1)
        return 0

    def dormir(segundos):
        pausas.append(segundos)
        if len(pausas) == 3:
            raise _FinDelBucle

    monkeypatch.setattr(agent_worker, "reencolar_tareas_pendientes", reencolar)
    monkeypatch.setattr(agent_worker.time, "sleep", dormir)
    with pytest.raises(_FinDelBucle):
        agent_worker.main()
    assert len(reencolados) == 3 and pausas == [2, 2, 2]


def test_worker_ejecutado_como_script_entra_al_bucle(monkeypatch):
    vueltas = []
    monkeypatch.setattr(task_orchestrator, "reencolar_tareas_pendientes", lambda: vueltas.append(1) or 0)

    def dormir(segundos):
        raise _FinDelBucle

    monkeypatch.setattr("time.sleep", dormir)
    with pytest.raises(_FinDelBucle):
        runpy.run_module("backend.api.agent_worker", run_name="__main__")
    assert vueltas == [1]
