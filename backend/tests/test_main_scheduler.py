"""test_main_scheduler.py — Cobertura real para `main.py::_job_reset_jobs_colgados` y su
cableado al `AsyncIOScheduler` del `lifespan`.

Auditoría 2026-09-09: `db/jobs_repo.py::reset_jobs_colgados` ya existía pero ningún cron ni
router la llamaba — un job podía quedar huérfano en 'procesando' para siempre si el proceso
moría a mitad de un análisis. El fix agrega un job periódico (`mantenimiento_jobs_colgados`,
cada 15 min) al `lifespan` de `main.py`.

No se ejercita el `lifespan` completo acá a propósito — mismo motivo documentado en
`test_app_gateway.py`: dispararía el arranque real del bot de Telegram (polling real si
`TELEGRAM_BOT_TOKEN` está seteado en el entorno) y un `httpx.AsyncClient` real. En su lugar:
  1. Se prueba `_job_reset_jobs_colgados` de forma aislada (BD real en memoria, monkeypatch de
     `main.SessionLocal`) — la función que el scheduler termina invocando.
  2. Se verifica por código fuente que `lifespan` la registra en `ap_scheduler` con el id y el
     trigger esperados — sin instanciar el scheduler real ni arrancar el proceso completo.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api import main
from backend.api.db.session import Base
from backend.api.models.jobs import Job
from backend.api.models.partidos import PartidoDia, StatsCache


def _sesion_memoria():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def test_job_reset_jobs_colgados_marca_error_a_job_huerfano(monkeypatch):
    """Ejercita la función real que el scheduler invoca cada 15 min — no un mock."""
    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    with testing_session_local() as db:
        # `creado_en` en UTC (ver `db/jobs_repo.py::_now_str`, normalizado 2026-09-09) —
        # escribirlo en hora local acá desalinearía la comparación contra el cutoff UTC real
        # de `reset_jobs_colgados` en cualquier máquina que no corra en UTC (bug real
        # encontrado con este mismo test, ver test siguiente).
        db.add(Job(job_id="job_huerfano", match_id="m1", fecha_partido="20260101", chat_id="c1",
                    user_id="u1", plan="free", origen="telegram", status="procesando", intentos=0,
                    creado_en=(datetime.utcnow() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

    asyncio.run(main._job_reset_jobs_colgados())

    # Post-condición real en la BD (empirical-verification-before-fix.md), no solo que la
    # corrutina no haya lanzado una excepción.
    with testing_session_local() as db:
        job = db.query(Job).filter(Job.job_id == "job_huerfano").first()
        assert job.status == "error"
        assert job.completado_en is not None


def test_job_reset_jobs_colgados_no_toca_jobs_recientes(monkeypatch):
    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    with testing_session_local() as db:
        # Bug real encontrado en esta auditoría (2026-09-09): antes de normalizar
        # `jobs_repo._now_str`/`reset_jobs_colgados` a UTC, este test pasaba SOLO porque la
        # máquina de test y el cutoff comparaban ambos en hora local — con `creado_en` en hora
        # local (`datetime.now()`) y el cutoff ya en UTC, este job "reciente" quedaba marcado
        # `error` en cualquier máquina con offset UTC negativo (Chile incluido), porque su
        # `creado_en` local aparecía más "viejo" que el cutoff UTC. Ver
        # `test_job_reset_jobs_colgados_marca_error_a_job_huerfano` arriba para el caso
        # simétrico.
        db.add(Job(job_id="job_reciente", match_id="m2", fecha_partido="20260101", chat_id="c1",
                    user_id="u1", plan="free", origen="telegram", status="procesando", intentos=0,
                    creado_en=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

    asyncio.run(main._job_reset_jobs_colgados())

    with testing_session_local() as db:
        assert db.query(Job).filter(Job.job_id == "job_reciente").first().status == "procesando"


def test_lifespan_registra_el_job_de_mantenimiento_de_jobs_colgados():
    """Verifica por código fuente que el job periódico queda cableado al scheduler — evita
    correr el `lifespan` completo (ver docstring del módulo)."""
    fuente = inspect.getsource(main.lifespan)
    assert "_job_reset_jobs_colgados" in fuente
    assert 'id="mantenimiento_jobs_colgados"' in fuente
    assert 'minute="*/15"' in fuente


def test_job_purga_datos_viejos_borra_partido_viejo_y_cache_expirado(monkeypatch):
    """Ejercita `_job_purga_datos_viejos` real (no un mock) contra una BD en memoria — confirma
    la post-condición real (filas borradas de verdad), no solo que la corrutina no lance
    excepción (`.claude/rules/empirical-verification-before-fix.md`).

    Auditoría 2026-09-09: `partidos_repo.limpiar_partidos_dia_viejos` y
    `cache.limpiar_stats_cache_expirado` ya existían pero ningún cron ni router las llamaba."""
    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    hace_100_dias = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    hoy = datetime.now().strftime("%Y-%m-%d")
    ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hace_1_hora = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    en_1_hora = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    with testing_session_local() as db:
        db.add(PartidoDia(fecha=hace_100_dias, match_id="viejo_1", status="finished"))
        db.add(PartidoDia(fecha=hoy, match_id="reciente_1", status="scheduled"))
        db.add(StatsCache(cache_key="expirado_1", tipo="team_stats", datos_json="{}",
                            creado_en=ahora_str, expira_en=hace_1_hora))
        db.add(StatsCache(cache_key="vigente_1", tipo="team_stats", datos_json="{}",
                            creado_en=ahora_str, expira_en=en_1_hora))
        db.commit()

    asyncio.run(main._job_purga_datos_viejos())

    with testing_session_local() as db:
        partidos_restantes = {p.match_id for p in db.query(PartidoDia).all()}
        assert partidos_restantes == {"reciente_1"}

        cache_restante = {c.cache_key for c in db.query(StatsCache).all()}
        assert cache_restante == {"vigente_1"}


def test_lifespan_registra_el_job_de_purga_de_datos_viejos():
    """Mismo patrón que el test de `mantenimiento_jobs_colgados` arriba — verifica por código
    fuente que el job de purga diario queda cableado, sin arrancar el `lifespan` completo."""
    fuente = inspect.getsource(main.lifespan)
    assert "_job_purga_datos_viejos" in fuente
    assert 'id="purga_datos_viejos"' in fuente
    assert "hour=4" in fuente


# ─── laplace-agents: auto-evaluación diaria (2026-09-09) ───────────────────────────────────


def test_job_laplace_agents_registra_run_exitoso(monkeypatch):
    """Ejercita `_job_laplace_agents` real (no un mock del job en sí) — solo se mockea
    `ejecutar_ciclo_autoevaluacion` (evita red real) para confirmar la post-condición real:
    queda un run registrado en `scheduler_runs` (`db/scheduler_repo.py`)."""
    from backend.api.db import scheduler_repo
    import laplace_agents  # noqa: E402 (main.py ya agregó laplace-agents/ a sys.path al importarse)

    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    async def _fake_ciclo(db, client, fecha=None):
        return {"fecha": "2026-09-09", "fuente_fixtures": "test", "candidatos_liga_conocida": 2,
                "ya_existian": 0, "nuevos_capados_a": 2, "analizados": 2, "errores": 0, "detalle": []}

    monkeypatch.setattr(laplace_agents, "ejecutar_ciclo_autoevaluacion", _fake_ciclo)

    asyncio.run(main._job_laplace_agents())

    with testing_session_local() as db:
        ultimo = scheduler_repo.ultimo_run_exitoso(db, "laplace_agents_autoeval")
        assert ultimo is not None
        assert "2/2" in (ultimo.detalle or "")


def test_lifespan_registra_el_job_de_laplace_agents():
    """Mismo patrón que los tests de cableado de arriba — verifica por código fuente que el
    job de auto-evaluación diaria queda registrado, sin arrancar el `lifespan` completo."""
    fuente = inspect.getsource(main.lifespan)
    assert "_job_laplace_agents" in fuente
    assert 'id="laplace_agents_autoeval"' in fuente
    assert "hour=8" in fuente


# ─── settings.LAPLACE_AGENTS_ACTIVO (2026-09-10) — interruptor del ciclo diario ────────────


def test_job_laplace_agents_no_ejecuta_ciclo_real_si_flag_desactivado(monkeypatch):
    """Con el flag en `False`, `_job_laplace_agents` debe saltarse el ciclo real (ni llamar a
    `ejecutar_ciclo_autoevaluacion` ni registrar un run en `scheduler_runs` — un salto
    deliberado no es una corrida, no debería aparecer como tal en `GET /scheduler/status`)."""
    from backend.api.core.config import settings
    from backend.api.db import scheduler_repo
    import laplace_agents

    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)
    monkeypatch.setattr(settings, "LAPLACE_AGENTS_ACTIVO", False)

    llamado = {"si": False}

    async def _no_deberia_llamarse(db, client, fecha=None):
        llamado["si"] = True
        return {}

    monkeypatch.setattr(laplace_agents, "ejecutar_ciclo_autoevaluacion", _no_deberia_llamarse)

    asyncio.run(main._job_laplace_agents())

    assert llamado["si"] is False
    with testing_session_local() as db:
        assert scheduler_repo.ultimo_run(db, "laplace_agents_autoeval") is None


def test_job_laplace_agents_ejecuta_ciclo_real_si_flag_activado_default(monkeypatch):
    """Con el flag default (`True`, sin tocarlo) el comportamiento sigue siendo el de antes de
    este cambio — mismo caso que `test_job_laplace_agents_registra_run_exitoso` arriba, pero
    confirmando explícitamente el valor default del flag."""
    from backend.api.core.config import settings
    from backend.api.db import scheduler_repo
    import laplace_agents

    assert settings.LAPLACE_AGENTS_ACTIVO is True  # default real, no se tocó en este test

    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    llamado = {"si": False}

    async def _fake_ciclo(db, client, fecha=None):
        llamado["si"] = True
        return {"fecha": "2026-09-10", "fuente_fixtures": "test", "candidatos_liga_conocida": 1,
                "ya_existian": 0, "nuevos_capados_a": 1, "analizados": 1, "errores": 0, "detalle": []}

    monkeypatch.setattr(laplace_agents, "ejecutar_ciclo_autoevaluacion", _fake_ciclo)

    asyncio.run(main._job_laplace_agents())

    assert llamado["si"] is True
    with testing_session_local() as db:
        assert scheduler_repo.ultimo_run_exitoso(db, "laplace_agents_autoeval") is not None


# ─── Bug real encontrado 2026-09-09: async with httpx.AsyncClient() as client, SessionLocal()
# as db: combina un context manager async con uno síncrono — TypeError garantizado en CADA
# disparo del cron (nunca detectado porque _job_top_picks/_job_resultados no tenían ningún
# test directo hasta ahora). Arreglado con `with SessionLocal() as db:` anidado dentro del
# `async with` del cliente HTTP. Estos tests ejercitan las funciones REALES (no un mock del
# job en sí) para confirmar que ahora sí corren de punta a punta.


def test_job_top_picks_corre_sin_typeerror_y_registra_run(monkeypatch):
    from backend.api.db import scheduler_repo
    from backend.api.services import top_picks

    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    async def _fake_generar(db, client):
        return {"sin_candidatos": True, "fecha_display": "01/06/2026", "fecha_db": "20260601"}

    async def _fake_publicar(db, client, resultado):
        return True

    monkeypatch.setattr(top_picks, "generar_top_picks_dia", _fake_generar)
    monkeypatch.setattr(top_picks, "publicar_top_picks", _fake_publicar)

    asyncio.run(main._job_top_picks())  # antes del fix: TypeError acá mismo

    with testing_session_local() as db:
        ultimo = scheduler_repo.ultimo_run_exitoso(db, "wfd_top_picks")
        assert ultimo is not None
        assert ultimo.detalle.startswith("sin_candidatos:")


def test_job_resultados_corre_sin_typeerror_y_registra_run(monkeypatch):
    from backend.api.db import scheduler_repo
    from backend.api.services import resultados_scheduler

    testing_session_local = _sesion_memoria()
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)

    async def _fake_ciclo(db, client):
        return {"sin_pendientes": True}

    monkeypatch.setattr(resultados_scheduler, "ejecutar_ciclo_resultados", _fake_ciclo)

    asyncio.run(main._job_resultados())  # antes del fix: TypeError acá mismo

    with testing_session_local() as db:
        ultimo = scheduler_repo.ultimo_run_exitoso(db, "wfe_resultados")
        assert ultimo is not None


# ─── Bug real 2026-09-10: el bot de Telegram no debe ser una dependencia dura de la API ─────


def test_lifespan_no_deja_que_un_fallo_del_bot_tumbe_toda_la_api():
    """Verifica por código fuente que el arranque del bot está envuelto en try/except — si
    Telegram es inalcanzable (confirmado real: la red de esta sesión no pudo resolver
    api.telegram.org), el fallo no debe propagarse y tumbar el `lifespan` completo (lo que
    tumbaría TODA la API HTTP: web, app, admin, scheduler — por un componente que debería ser
    una extensión, no una dependencia dura)."""
    fuente = inspect.getsource(main.lifespan)
    assert "start_polling" in fuente
    # El try debe envolver el arranque real del bot, y el except no debe re-lanzar (sin
    # `raise` dentro del bloque except de esta sección específica).
    inicio = fuente.index("if settings.TELEGRAM_BOT_TOKEN:")
    fin = fuente.index("else:", inicio)
    seccion_bot = fuente[inicio:fin]
    assert "try:" in seccion_bot
    assert "except Exception:" in seccion_bot
    assert "bot_app = None" in seccion_bot  # limpieza real tras el fallo, no un estado a medias
