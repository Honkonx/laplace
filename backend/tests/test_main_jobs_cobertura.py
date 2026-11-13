"""test_main_jobs_cobertura.py — cobertura de los trabajos del planificador `_job_*` de `main.py`, del
`lifespan` (arranque y cierre) y de los endpoints de salud. Cada job se ejecuta de verdad contra una BD en
memoria con sus dependencias externas sustituidas (sin red, sin Telegram, sin `.env` real) y se comprueba la
post-condición real: la fila en `scheduler_runs` y que el fallo de una fuente no tumbe el proceso."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api import main
from backend.api.db.session import Base
from backend.api.models.partidos import PartidoDia
from backend.api.models.scheduler import SchedulerRun
from backend.api.routers import scheduler as sch

FECHA_VIEJA = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")


@pytest.fixture()
def sesion(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "SessionLocal", fabrica)
    return fabrica


@pytest.fixture(autouse=True)
def _restaurar_estado_de_la_app():
    """El `lifespan` deja `http_client` cerrado y `ap_scheduler` apagado en el singleton `app`."""
    previo = {k: getattr(main.app.state, k) for k in ("http_client", "ap_scheduler") if hasattr(main.app.state, k)}
    yield
    for k in ("http_client", "ap_scheduler"):
        if k in previo:
            setattr(main.app.state, k, previo[k])
        elif hasattr(main.app.state, k):
            delattr(main.app.state, k)


def _runs(fabrica) -> list[SchedulerRun]:
    with fabrica() as db:
        return db.query(SchedulerRun).order_by(SchedulerRun.id).all()


def _correr(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------------ top picks
def test_job_top_picks_registra_publicado(sesion, monkeypatch):
    from backend.api.services import top_picks

    async def generar(db, client):
        return {"picks": [1]}

    async def publicar(db, client, resultado):
        return True

    monkeypatch.setattr(top_picks, "generar_top_picks_dia", generar)
    monkeypatch.setattr(top_picks, "publicar_top_picks", publicar)
    _correr(main._job_top_picks())
    run = _runs(sesion)[0]
    assert (run.job_name, run.ok, run.detalle) == (sch.JOB_TOP_PICKS, True, "publicado")


@pytest.mark.parametrize("resultado,prefijo", [
    ({"sin_candidatos": True}, "sin_candidatos:"),
    ({"sin_picks_validos": True}, "sin_picks_validos:"),
])
def test_job_top_picks_sin_publicar_deja_el_motivo(sesion, monkeypatch, resultado, prefijo):
    from backend.api.services import top_picks

    async def generar(db, client):
        return resultado

    async def publicar(db, client, res):
        return False

    monkeypatch.setattr(top_picks, "generar_top_picks_dia", generar)
    monkeypatch.setattr(top_picks, "publicar_top_picks", publicar)
    _correr(main._job_top_picks())
    run = _runs(sesion)[0]
    assert run.ok is False and run.detalle == f"{prefijo}ya_publicado_o_error_telegram"


def test_job_top_picks_excepcion_se_registra_y_se_propaga_al_planificador(sesion, monkeypatch):
    from backend.api.services import top_picks

    async def generar(db, client):
        raise RuntimeError("api caida")

    monkeypatch.setattr(top_picks, "generar_top_picks_dia", generar)
    with pytest.raises(RuntimeError):  # APScheduler la atrapa y sigue con los demás jobs
        _correr(main._job_top_picks())
    run = _runs(sesion)[0]
    assert (run.job_name, run.ok) == (sch.JOB_TOP_PICKS, False)


# ------------------------------------------------------------------------------ resultados
def test_job_resultados_ok_y_error(sesion, monkeypatch):
    from backend.api.services import resultados_scheduler as rs

    llamadas = []

    async def ciclo(db, client):
        llamadas.append(1)

    monkeypatch.setattr(rs, "ejecutar_ciclo_resultados", ciclo)
    _correr(main._job_resultados())
    assert [(r.job_name, r.ok) for r in _runs(sesion)] == [(sch.JOB_RESULTADOS, True)]

    async def roto(db, client):
        raise ValueError("boom")

    monkeypatch.setattr(rs, "ejecutar_ciclo_resultados", roto)
    with pytest.raises(ValueError):
        _correr(main._job_resultados())
    assert [(r.job_name, r.ok) for r in _runs(sesion)] == [(sch.JOB_RESULTADOS, True), (sch.JOB_RESULTADOS, False)]


# ------------------------------------------------------------------------------ fuentes
def _parchar_alertas(monkeypatch):
    from backend.api.services import alerting

    emitidas = []
    monkeypatch.setattr(alerting, "emitir_alerta", lambda evento, detalle: emitidas.append((evento, detalle)) or True)
    monkeypatch.setattr(main, "_alertar_creditos_odds", lambda db: None)
    return emitidas


def test_job_verificar_fuentes_todas_saludables_no_alerta(sesion, monkeypatch):
    from backend.api.services import source_health

    emitidas = _parchar_alertas(monkeypatch)

    async def verificar(db, client):
        return [{"fuente": "a", "configurada": True, "saludable": True},
                {"fuente": "b", "configurada": False, "saludable": False}]

    monkeypatch.setattr(source_health, "verificar_fuentes", verificar)
    _correr(main._job_verificar_fuentes())
    run = _runs(sesion)[0]
    assert run.ok is True and run.detalle == "1/1 fuentes configuradas saludables" and emitidas == []


def test_job_verificar_fuentes_degradada_emite_alerta_con_la_fallida(sesion, monkeypatch):
    from backend.api.services import source_health

    emitidas = _parchar_alertas(monkeypatch)

    async def verificar(db, client):
        return [{"fuente": "ok", "configurada": True, "saludable": True},
                {"fuente": "caida", "configurada": True, "saludable": False, "detalle": "HTTP 500"}]

    monkeypatch.setattr(source_health, "verificar_fuentes", verificar)
    _correr(main._job_verificar_fuentes())
    assert _runs(sesion)[0].ok is False
    evento, detalle = emitidas[0]
    assert evento == "fuentes_deportivas_degradadas" and detalle["fallidas"] == [{"fuente": "caida", "detalle": "HTTP 500"}]


def test_job_verificar_fuentes_excepcion_no_rompe(sesion, monkeypatch):
    from backend.api.services import source_health

    async def verificar(db, client):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(source_health, "verificar_fuentes", verificar)
    _correr(main._job_verificar_fuentes())  # no lanza
    run = _runs(sesion)[0]
    assert (run.job_name, run.ok) == (sch.JOB_FUENTES_DEPORTIVAS, False)


def test_alertar_creditos_odds_alerta_solo_si_corresponde(sesion, monkeypatch):
    from backend.api.services import alertas_cuota, alerting, odds_fetch

    emitidas = []
    monkeypatch.setattr(alerting, "emitir_alerta", lambda e, d: emitidas.append((e, d)) or True)
    monkeypatch.setattr(odds_fetch, "consumo_odds_hoy", lambda db: {"restante_api": 12})
    monkeypatch.setattr(alertas_cuota, "debe_alertar_creditos", lambda db, restante: restante < 50)
    with sesion() as db:
        main._alertar_creditos_odds(db)
    assert emitidas == [("odds_creditos_bajos", {"restante": 12})]

    emitidas.clear()
    monkeypatch.setattr(odds_fetch, "consumo_odds_hoy", lambda db: {"restante_api": 400})
    with sesion() as db:
        main._alertar_creditos_odds(db)
    assert emitidas == []


# ------------------------------------------------------------------------------ cuotas
def test_job_refresco_cuotas_ok_y_excepcion(sesion, monkeypatch):
    from backend.api.services import refresco_cuotas

    async def refresco(db, client):
        return {"ok": True, "peticiones": 3}

    monkeypatch.setattr(refresco_cuotas, "ejecutar_refresco_cuotas", refresco)
    monkeypatch.setattr(refresco_cuotas, "detalle_corto", lambda r: f"{r['peticiones']} peticiones")
    _correr(main._job_refresco_cuotas())

    async def roto(db, client):
        raise TimeoutError("lento")

    monkeypatch.setattr(refresco_cuotas, "ejecutar_refresco_cuotas", roto)
    _correr(main._job_refresco_cuotas())  # no lanza
    runs = _runs(sesion)
    assert [(r.job_name, r.ok) for r in runs] == [(sch.JOB_REFRESCO_CUOTAS, True), (sch.JOB_REFRESCO_CUOTAS, False)]
    assert runs[0].detalle == "3 peticiones"


# ------------------------------------------------------------------------------ colector
def test_job_colectar_resultados_desactivado_no_registra(sesion, monkeypatch):
    from backend.api.services import colector_resultados as col

    monkeypatch.setattr(col, "colector_activo", lambda: False)
    _correr(main._job_colectar_resultados())
    assert _runs(sesion) == []


def test_job_colectar_resultados_ok_exporta_y_trunca_detalle(sesion, monkeypatch):
    from backend.api.services import colector_resultados as col

    async def colectar(db, client):
        return {"ok": True}

    monkeypatch.setattr(col, "colector_activo", lambda: True)
    monkeypatch.setattr(col, "ejecutar_colector", colectar)
    monkeypatch.setattr(col, "detalle_corto", lambda r: "x" * 400)
    monkeypatch.setattr(col, "exportar_capa_vivo", lambda: {"ok": True, "detalle": "y" * 400})
    _correr(main._job_colectar_resultados())
    run = _runs(sesion)[0]
    assert run.ok is True and len(run.detalle) == 500


def test_job_colectar_resultados_exportacion_fallida_o_excepcion(sesion, monkeypatch):
    from backend.api.services import colector_resultados as col

    async def colectar(db, client):
        return {"ok": True}

    monkeypatch.setattr(col, "colector_activo", lambda: True)
    monkeypatch.setattr(col, "ejecutar_colector", colectar)
    monkeypatch.setattr(col, "detalle_corto", lambda r: "c")
    monkeypatch.setattr(col, "exportar_capa_vivo", lambda: {"ok": False, "detalle": "sin disco"})
    _correr(main._job_colectar_resultados())

    async def roto(db, client):
        raise OSError("disco")

    monkeypatch.setattr(col, "ejecutar_colector", roto)
    _correr(main._job_colectar_resultados())  # no lanza
    runs = _runs(sesion)
    assert [r.ok for r in runs] == [False, False]
    assert runs[0].detalle == "c; sin disco" and runs[1].detalle == "excepcion inesperada"


# ------------------------------------------------------------------------------ reajuste
def test_job_reajustar_modelos_variantes(sesion, monkeypatch):
    from backend.api.ml import job_reajuste as jr

    monkeypatch.setattr(jr, "reajuste_activo", lambda: False)
    _correr(main._job_reajustar_modelos())
    assert _runs(sesion) == []

    monkeypatch.setattr(jr, "reajuste_activo", lambda: True)
    monkeypatch.setattr(jr, "ejecutar_reajuste", lambda: {"ok": True, "detalle": "2 ligas reentrenadas"})
    _correr(main._job_reajustar_modelos())

    def roto():
        raise RuntimeError("sin numpy")

    monkeypatch.setattr(jr, "ejecutar_reajuste", roto)
    _correr(main._job_reajustar_modelos())  # no lanza
    runs = _runs(sesion)
    assert [(r.job_name, r.ok, r.detalle) for r in runs] == [
        (sch.JOB_REAJUSTE_MODELOS, True, "2 ligas reentrenadas"),
        (sch.JOB_REAJUSTE_MODELOS, False, "excepcion inesperada"),
    ]


# ------------------------------------------------------------------------------ mantenimiento
def test_job_reset_jobs_colgados_loguea_los_reseteados(sesion, monkeypatch, caplog):
    from backend.api.db import jobs_repo

    monkeypatch.setattr(jobs_repo, "reset_jobs_colgados",
                        lambda db, timeout_min: {"reseteados": 1, "detalle": [{"job_id": "jx"}]})
    with caplog.at_level(logging.WARNING, logger="laplace.main"):
        _correr(main._job_reset_jobs_colgados())
    assert "jx" in caplog.text


def test_job_purga_borra_solo_partidos_de_mas_de_90_dias(sesion):
    hoy = datetime.now().strftime("%Y-%m-%d")
    with sesion() as db:
        db.add_all([PartidoDia(fecha=FECHA_VIEJA, match_id="viejo"), PartidoDia(fecha=hoy, match_id="nuevo")])
        db.commit()
    _correr(main._job_purga_datos_viejos())
    with sesion() as db:
        assert [p.match_id for p in db.query(PartidoDia)] == ["nuevo"]


# ------------------------------------------------------------------------------ laplace-agents
def test_job_laplace_agents_apagado_no_registra(sesion, monkeypatch):
    monkeypatch.setattr(main.settings, "LAPLACE_AGENTS_ACTIVO", False)
    _correr(main._job_laplace_agents())
    assert _runs(sesion) == []


def test_job_laplace_agents_ok_y_error(sesion, monkeypatch):
    import laplace_agents

    monkeypatch.setattr(main.settings, "LAPLACE_AGENTS_ACTIVO", True)

    async def ciclo(db, client):
        return {"analizados": 3, "candidatos_liga_conocida": 5, "errores": 1}

    monkeypatch.setattr(laplace_agents, "ejecutar_ciclo_autoevaluacion", ciclo)
    _correr(main._job_laplace_agents())

    async def roto(db, client):
        raise RuntimeError("ia caida")

    monkeypatch.setattr(laplace_agents, "ejecutar_ciclo_autoevaluacion", roto)
    with pytest.raises(RuntimeError):
        _correr(main._job_laplace_agents())
    runs = _runs(sesion)
    assert [(r.job_name, r.ok) for r in runs] == [(sch.JOB_LAPLACE_AGENTS, True), (sch.JOB_LAPLACE_AGENTS, False)]
    assert runs[0].detalle == "3/5 analizados, 1 errores"


# ------------------------------------------------------------------------------ lifespan
JOBS_ESPERADOS = {
    "fuentes_deportivas_health", "laplace_agents_autoeval", "wfd_top_picks", "wfe_resultados_2h",
    "wfe_resultados_7am", "refresco_cuotas", "colector_resultados", "reajuste_modelos",
    "mantenimiento_jobs_colgados", "purga_datos_viejos", "modelo_laplace_sombra", "avisos_favoritos", "avisos_resultados", "resultados_actuales", "estado_vivo_modelo", "modelo_laplace_reentreno",
}


def _parchar_arranque(monkeypatch, sesion, token=""):
    from backend.api.services import agent_knowledge, task_orchestrator

    monkeypatch.setattr(main.settings, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(main, "validar_secretos_arranque", lambda cfg: [])
    monkeypatch.setattr(main, "configurar_logging", lambda: None)
    monkeypatch.setattr(task_orchestrator, "recuperar_tareas_interrumpidas", lambda: None)
    monkeypatch.setattr(agent_knowledge, "sincronizar_conocimiento_json", lambda db: None)


async def _arrancar_y_cerrar():
    visto = {}
    async with main.lifespan(main.app):
        visto["jobs"] = {j.id for j in main.app.state.ap_scheduler.get_jobs()}
        visto["corriendo"] = main.app.state.ap_scheduler.running
        scheduler = main.app.state.ap_scheduler
    visto["cerrado_cliente"] = main.app.state.http_client.is_closed
    return visto, scheduler


def test_lifespan_sin_token_registra_todos_los_jobs_y_cierra(sesion, monkeypatch):
    _parchar_arranque(monkeypatch, sesion)
    visto, _ = _correr(_arrancar_y_cerrar())
    assert visto["jobs"] == JOBS_ESPERADOS and visto["corriendo"] is True
    assert visto["cerrado_cliente"] is True


def test_lifespan_sigue_vivo_si_falla_la_sincronizacion_del_agente(sesion, monkeypatch):
    from backend.api.services import agent_knowledge

    _parchar_arranque(monkeypatch, sesion)

    def roto(db):
        raise RuntimeError("conocimiento corrupto")

    monkeypatch.setattr(agent_knowledge, "sincronizar_conocimiento_json", roto)
    visto, _ = _correr(_arrancar_y_cerrar())
    assert visto["jobs"] == JOBS_ESPERADOS


def test_lifespan_bot_que_no_arranca_no_tumba_la_api(sesion, monkeypatch):
    from backend.api.bot import laplace_bot

    _parchar_arranque(monkeypatch, sesion, token="token-de-prueba")

    def construir():
        raise ConnectionError("Telegram inalcanzable")

    monkeypatch.setattr(laplace_bot, "construir_app", construir)
    visto, _ = _correr(_arrancar_y_cerrar())
    assert visto["jobs"] == JOBS_ESPERADOS


def test_lifespan_con_bot_lo_inicia_y_lo_detiene(sesion, monkeypatch):
    from backend.api.bot import laplace_bot

    _parchar_arranque(monkeypatch, sesion, token="token-de-prueba")
    eventos = []

    class _Updater:
        async def start_polling(self):
            eventos.append("polling")

        async def stop(self):
            eventos.append("updater_stop")

    class _Bot:
        bot_data: dict = {}
        updater = _Updater()

        async def initialize(self):
            eventos.append("init")

        async def start(self):
            eventos.append("start")

        async def stop(self):
            eventos.append("stop")

        async def shutdown(self):
            eventos.append("shutdown")

    bot = _Bot()
    bot.bot_data = {}
    monkeypatch.setattr(laplace_bot, "construir_app", lambda: bot)
    _correr(_arrancar_y_cerrar())
    assert eventos == ["init", "start", "polling", "updater_stop", "stop", "shutdown"]
    assert "http_client" in bot.bot_data


# ------------------------------------------------------------------------------ endpoints de salud
def test_endpoints_de_salud_y_capacidades():
    cliente = TestClient(main.app)
    salud = cliente.get("/health").json()
    assert {k: salud[k] for k in ("status", "component", "version")} == {"status": "ok", "component": "sports-bot", "version": main.app.version} and salud["consenso"]["contrato"] == "consenso.v1"
    assert cliente.get("/api/v1/health").json() == {"status": "ok"}
    caps = cliente.get("/capabilities").json()
    assert caps["independent"] is True and "results" in caps["capabilities"]


def test_dependencia_agente_disponible_y_no_disponible(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"component": "agent"}

    class _Cliente:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if self.falla:
                raise httpx.ConnectError("no hay agente")
            return _Resp()

    monkeypatch.setattr(main.settings, "AGENT_URL", "http://agente.local/")
    monkeypatch.setattr(main.httpx, "AsyncClient", _Cliente)

    _Cliente.falla = False
    ok = _correr(main.agent_dependency())
    assert ok == {"available": True, "url": "http://agente.local/", "capabilities": {"component": "agent"}}

    _Cliente.falla = True
    caido = _correr(main.agent_dependency())
    assert caido["available"] is False and caido["reason"] == "ConnectError"
