"""
main.py — App FastAPI de Laplace.

Arranque: `uvicorn backend.api.main:app --reload` (correr desde la raíz del repo).

Fase 2 completa (Parte 1: motor + DB: Parte 2: WF-A/WF-A2/WF-B/WF-D/WF-E/WF-F migrados a
Python). El bot de Telegram corre embebido en el ciclo de vida de esta app (polling, no
webhook — más simple para un solo proceso) si `TELEGRAM_BOT_TOKEN` está configurado; si no,
la app arranca igual (útil para tests o para correr solo el gateway de la app/web).
`backend/python/` (n8n + scripts originales) se archivó en `backend/_archive_python/` el
2026-09-10 — nada en `backend/api/` lo invoca (confirmado por grep, ver
`el aviso de archivado de los scripts de Termux` y el registro de decisiones del proyecto); no se borró, solo se movió.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# `laplace-agents/` (2026-09-10) es un paquete propio en la raíz del repo, separado a propósito
# de `backend/` — el usuario pidió que sea una extensión real, no una carpeta más del backend
# (ver `laplace-agents/README.md`). Sys.path insertion ANTES de importar `routers.scheduler`
# (que hace `import laplace_agents`) — debe correr acá primero para que ese import resuelva.
_LAPLACE_AGENTS_DIR = Path(__file__).resolve().parents[2] / "backend" / "agents"
if str(_LAPLACE_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_LAPLACE_AGENTS_DIR))

# (E402 en los imports de abajo es intencional: dependen del sys.path de laplace-agents de arriba.)
from backend.api.core.config import settings, validar_secretos_arranque  # noqa: E402
from backend.api.core.logging_config import configurar_logging  # noqa: E402
from backend.api.core.rate_limit import limiter  # noqa: E402
from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.routers import admin, agent, app_gateway, auth, deportivo, partidos, prediccion_web, resultados, scheduler, simulador, track_record, web, web_catalog  # noqa: E402

log = logging.getLogger("laplace.main")

TZ_CHILE = ZoneInfo("America/Santiago")


async def _job_top_picks() -> None:
    """Calcula y publica el informe diario de Top Picks en el canal.

    Reemplaza el cron 9AM Chile de WF-D y publica el informe diario.

    Solo los picks que pasan el umbral estadístico llegan al canal. Si ningún partido lo pasa,
    el canal recibe el informe de transparencia correspondiente, nunca un pick inventado.

    2026-09-09 — registra cada corrida en `scheduler_runs` (ver `db/scheduler_repo.py` y
    `GET /api/v1/scheduler/status`), para poder confirmar que el cron sigue vivo sin ir a
    revisar logs a mano."""
    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_TOP_PICKS

    # Bug real encontrado 2026-09-09 (mientras se testeaba `_job_laplace_agents`, que copiaba
    # este mismo patrón): `async with httpx.AsyncClient() as client, SessionLocal() as db:`
    # combina un context manager ASYNC con uno SÍNCRONO en un solo `async with` — Python exige
    # que TODOS los items de un `async with a, b:` soporten `__aenter__`/`__aexit__`, y
    # `Session` (SQLAlchemy síncrono) no lo soporta (`TypeError: 'Session' object does not
    # support the asynchronous context manager protocol`, confirmado con un test real). Esto
    # significa que el cron automático de Top Picks (9am Chile) tiraba esa excepción en CADA
    # disparo desde que existe este código — nunca llegó a ejecutar nada real. Los disparos
    # MANUALES (`routers/scheduler.py`) nunca tuvieron este bug porque reciben `db` vía
    # `Depends(get_db)`, un camino totalmente distinto. Fix: `with SessionLocal() as db:`
    # (síncrono) anidado DENTRO del `async with` del cliente HTTP, nunca combinados en la
    # misma sentencia.
    async with httpx.AsyncClient() as client:
        from backend.api.services import top_picks

        with SessionLocal() as db:
            try:
                resultado = await top_picks.generar_top_picks_dia(db, client)
                publicado = await top_picks.publicar_top_picks(db, client, resultado)
                detalle = "publicado" if publicado else "ya_publicado_o_error_telegram"
                if resultado.get("sin_candidatos"):
                    detalle = f"sin_candidatos:{detalle}"
                elif resultado.get("sin_picks_validos"):
                    detalle = f"sin_picks_validos:{detalle}"
                scheduler_repo.registrar_run(db, JOB_TOP_PICKS, ok=publicado, detalle=detalle)
            except Exception:
                log.exception("Fallo _job_top_picks")
                scheduler_repo.registrar_run(db, JOB_TOP_PICKS, ok=False)
                raise


async def _job_resultados() -> None:
    """Verifica los resultados finales y califica los pronósticos pendientes y las observaciones del laboratorio.

    Reemplaza el cron cada 2h + 07:00 de WF-E. Registra cada corrida en `scheduler_runs`
    (ver docstring de `_job_top_picks`) — WF-E corre bajo dos ids de cron (`wfe_resultados_2h`/
    `wfe_resultados_7am`) que comparten la misma lógica, así que ambos se registran bajo el
    mismo `job_name` lógico (`JOB_RESULTADOS`)."""
    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_RESULTADOS

    # Mismo bug real y mismo fix que `_job_top_picks` — ver esa docstring/comentario.
    async with httpx.AsyncClient() as client:
        from backend.api.services import resultados_scheduler

        with SessionLocal() as db:
            try:
                await resultados_scheduler.ejecutar_ciclo_resultados(db, client)
            except Exception:
                log.exception("Fallo _job_resultados")
                scheduler_repo.registrar_run(db, JOB_RESULTADOS, ok=False)
                raise
            scheduler_repo.registrar_run(db, JOB_RESULTADOS, ok=True)


def _alertar_creditos_odds(db) -> None:
    """Avisa una vez al día si The Odds API tiene pocos créditos; sin dato (None) no alerta."""
    from backend.api.services.alerting import emitir_alerta
    from backend.api.services.alertas_cuota import debe_alertar_creditos
    from backend.api.services.odds_fetch import consumo_odds_hoy

    restante = consumo_odds_hoy(db).get("restante_api")
    if debe_alertar_creditos(db, restante):
        emitir_alerta("odds_creditos_bajos", {"restante": restante})


async def _job_verificar_fuentes() -> None:
    """Registra la salud de fuentes antes de los ciclos que consumen datos.

    Solo prueba proveedores gratuitos o de cuota diaria. La comprobación de The Odds API se
    mantiene manual porque una consulta de salud consume créditos mensuales.
    """
    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_FUENTES_DEPORTIVAS
    from backend.api.services.source_health import verificar_fuentes

    async with httpx.AsyncClient() as client:
        with SessionLocal() as db:
            try:
                fuentes = await verificar_fuentes(db, client)
                configuradas = [f for f in fuentes if f["configurada"]]
                saludables = [f for f in configuradas if f["saludable"]]
                ok_todas = len(configuradas) == len(saludables)
                scheduler_repo.registrar_run(
                    db,
                    JOB_FUENTES_DEPORTIVAS,
                    ok=ok_todas,
                    detalle=f"{len(saludables)}/{len(configuradas)} fuentes configuradas saludables",
                )
                if configuradas and not ok_todas:
                    from backend.api.services.alerting import emitir_alerta

                    fallidas = [
                        {"fuente": f["fuente"], "detalle": f.get("detalle")}
                        for f in configuradas
                        if not f["saludable"]
                    ]
                    emitir_alerta(
                        "fuentes_deportivas_degradadas",
                        {
                            "saludables": len(saludables),
                            "configuradas": len(configuradas),
                            "fallidas": fallidas,
                        },
                    )
                _alertar_creditos_odds(db)
            except Exception:
                log.exception("Fallo _job_verificar_fuentes")
                scheduler_repo.registrar_run(db, JOB_FUENTES_DEPORTIVAS, ok=False)


async def _job_refresco_cuotas() -> None:
    """Refresca las cuotas (The Odds API) y las tablas de posiciones (football-data) de los partidos de hoy y mañana, dentro de un tope diario.

    Refresca odds (The Odds API) y standings (football-data) de los partidos de hoy/mañana
    dentro de un tope diario de peticiones — ver `services/refresco_cuotas.py`. Antes nada
    renovaba esa caché fuera de un análisis de usuario: la auditoría 2026-10-06 encontró las 79
    odds y las 9 standings cacheadas expiradas (la última del 2026-09-28)."""
    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_REFRESCO_CUOTAS
    from backend.api.services import refresco_cuotas

    async with httpx.AsyncClient() as client:
        with SessionLocal() as db:
            try:
                resumen = await refresco_cuotas.ejecutar_refresco_cuotas(db, client)
                scheduler_repo.registrar_run(
                    db, JOB_REFRESCO_CUOTAS, ok=resumen["ok"], detalle=refresco_cuotas.detalle_corto(resumen)
                )
            except Exception:
                log.exception("Fallo _job_refresco_cuotas")
                scheduler_repo.registrar_run(db, JOB_REFRESCO_CUOTAS, ok=False)


async def _job_colectar_resultados() -> None:
    """Guarda los marcadores finales recientes y los partidos programados para que la capa en vivo de los modelos crezca sola.

    Colector diario de resultados (02:30 y 12:30 hora Chile), independiente del tráfico de usuarios:
    guarda los marcadores finales de los últimos 3 días y los programados de hoy/mañana para que la capa
    en vivo de los modelos hispanohablantes crezca sola — ver `services/colector_resultados.py`.

    Tope diario de peticiones (`LAPLACE_COLECTOR_MAX_PETICIONES_DIA`), apagable con
    `LAPLACE_COLECTOR_ACTIVO=0`. Tras colectar exporta la capa en vivo (solo librería estándar, sin
    numpy/scipy); el reentrenamiento queda en `_job_reajustar_modelos`. Nunca rompe el backend."""
    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_COLECTOR_RESULTADOS
    from backend.api.services import colector_resultados

    if not colector_resultados.colector_activo():
        log.info("_job_colectar_resultados desactivado (LAPLACE_COLECTOR_ACTIVO)")
        return
    async with httpx.AsyncClient() as client:
        with SessionLocal() as db:
            try:
                resumen = await colector_resultados.ejecutar_colector(db, client)
                exportacion = await asyncio.to_thread(colector_resultados.exportar_capa_vivo)
                scheduler_repo.registrar_run(
                    db, JOB_COLECTOR_RESULTADOS, ok=resumen["ok"] and exportacion["ok"],
                    detalle=f"{colector_resultados.detalle_corto(resumen)}; {exportacion['detalle']}"[:500],
                )
            except Exception:
                log.exception("Fallo _job_colectar_resultados")
                scheduler_repo.registrar_run(db, JOB_COLECTOR_RESULTADOS, ok=False, detalle="excepcion inesperada")


async def _job_reajustar_modelos() -> None:
    """Reajusta cada semana los modelos Dixon-Coles con los resultados verificados y reemplaza el artefacto solo si la validación pasa.

    Reajuste semanal de los Dixon-Coles con los resultados que el propio bot verifica (capa en vivo):
    exporta `resultados_partidos`/`partidos_dia` terminados, reentrena las ligas afectadas, VALIDA y
    reemplaza el artefacto de forma atómica solo si la validación pasa — ver `ml/reajuste.py`.

    Corre en un subproceso con el Python de `LAPLACE_PYTHON_ML` (el servidor no tiene numpy/scipy) y
    degrada con ok=False si faltan; nunca rompe el backend. `LAPLACE_REAJUSTE_AUTOMATICO=0` lo apaga.
    El `modelo_historico` en ejecución recoge el artefacto nuevo sin reiniciar (firma de archivos)."""
    from backend.api.db import scheduler_repo
    from backend.api.ml import job_reajuste
    from backend.api.routers.scheduler import JOB_REAJUSTE_MODELOS

    if not job_reajuste.reajuste_activo():
        log.info("_job_reajustar_modelos desactivado (LAPLACE_REAJUSTE_AUTOMATICO)")
        return
    with SessionLocal() as db:
        try:
            resultado = await asyncio.to_thread(job_reajuste.ejecutar_reajuste)
            scheduler_repo.registrar_run(db, JOB_REAJUSTE_MODELOS, ok=resultado["ok"], detalle=resultado["detalle"])
        except Exception:
            log.exception("Fallo _job_reajustar_modelos")
            scheduler_repo.registrar_run(db, JOB_REAJUSTE_MODELOS, ok=False, detalle="excepcion inesperada")


async def _job_reset_jobs_colgados() -> None:
    """Marca como error los análisis que quedaron en «procesando» porque el proceso murió a mitad.

    Recuperación de jobs huérfanos: si el proceso muere a mitad de un análisis (crash, OOM,
    redeploy) el job queda en 'procesando' para siempre — nada lo reintentaba ni lo marcaba
    como error. `db/jobs_repo.py::reset_jobs_colgados` ya existía pero ningún cron ni router la
    llamaba (hallazgo real de la auditoría 2026-09-09 — ver el registro de decisiones del proyecto). Corre
    cada 15 min."""
    from backend.api.db import jobs_repo

    with SessionLocal() as db:
        resultado = jobs_repo.reset_jobs_colgados(db, timeout_min=15)
        if resultado["reseteados"]:
            log.warning(
                "reset_jobs_colgados: %d job(s) huérfano(s) marcados como error: %s",
                resultado["reseteados"], [d["job_id"] for d in resultado["detalle"]],
            )


async def _job_purga_datos_viejos() -> None:
    """Purga `partidos_dia` de más de 90 días y la caché de estadísticas vencida.

    Purga `partidos_dia` > 90 días (`db/partidos_repo.py::limpiar_partidos_dia_viejos`) y
    `stats_cache` expirado (`db/cache.py::limpiar_stats_cache_expirado`) — ninguna de las dos
    corría automática desde que se migró de n8n (sin cron) a FastAPI: existían pero ningún
    router ni scheduler las llamaba (hallazgo real de la auditoría 2026-09-09, ver
    el registro de decisiones del proyecto, mismo patrón que `_job_reset_jobs_colgados`). Corre una vez al día
    de madrugada (hora Chile) para que las tablas no crezcan sin límite.

    Verificado contra la BD real antes de cablear este job (`.claude/rules/database-safety.md`):
    hoy `partidos_dia` solo tiene ~3 días de histórico (0 filas superan los 90 días) y
    `stats_cache` tiene 31 filas totales — no es una purga masiva sorpresiva la primera vez que
    corre."""
    from backend.api.db import cache, partidos_repo

    with SessionLocal() as db:
        n_partidos = partidos_repo.limpiar_partidos_dia_viejos(db)
        n_cache = cache.limpiar_stats_cache_expirado(db)
        log.info(
            "purga_datos_viejos: %d fila(s) de partidos_dia (>90 días) + %d fila(s) de "
            "stats_cache (expiradas) borradas",
            n_partidos, n_cache,
        )


async def _job_laplace_agents() -> None:
    """Auto-evaluación diaria del motor: el sistema se analiza a sí mismo sin depender del tráfico de usuarios.

    Auto-evaluación diaria (2026-09-09, reubicado 2026-09-10 a `laplace-agents/` — ver
    `laplace_agents/core.py` y su README): el sistema se analiza a sí mismo, sin depender de
    que un usuario real pida algo — antes de esto, la calibración del motor dependía 100% del
    tráfico de usuarios (hallazgo real de la auditoría, ver el registro de decisiones del proyecto). Corre a
    las 8am Chile, antes del cron de Top Picks (9am) — para cuando un usuario real pregunte por
    un partido de liga conocida más tarde en el día, la mayoría ya está pre-analizado y
    cacheado.

    2026-09-10 — respeta `settings.LAPLACE_AGENTS_ACTIVO` (default `True`, no cambia el
    comportamiento actual): si está en `False`, se saltea el ciclo real y solo loguea — no
    cuenta como error (no llama a `scheduler_repo.registrar_run`, para no ensuciar
    `GET /api/v1/scheduler/status` con corridas que nunca ocurrieron de verdad)."""
    if not settings.LAPLACE_AGENTS_ACTIVO:
        log.info("_job_laplace_agents: saltado — LAPLACE_AGENTS_ACTIVO=False en la config")
        return

    from backend.api.db import scheduler_repo
    from backend.api.routers.scheduler import JOB_LAPLACE_AGENTS

    import laplace_agents

    # Mismo bug real y mismo fix que `_job_top_picks` — ver esa docstring/comentario.
    async with httpx.AsyncClient() as client:
        with SessionLocal() as db:
            try:
                resumen = await laplace_agents.ejecutar_ciclo_autoevaluacion(db, client)
                scheduler_repo.registrar_run(
                    db, JOB_LAPLACE_AGENTS, ok=True,
                    detalle=f"{resumen['analizados']}/{resumen['candidatos_liga_conocida']} analizados, {resumen['errores']} errores",
                )
            except Exception:
                log.exception("Fallo _job_laplace_agents")
                scheduler_repo.registrar_run(db, JOB_LAPLACE_AGENTS, ok=False)
                raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    configurar_logging()
    validar_secretos_arranque(settings)
    app.state.http_client = httpx.AsyncClient()

    # Sincronización inicial del agente embebido (main.py expone `agent.router` además de
    # `agent_main.py`). Envuelto en try/except para que nunca sea dependencia dura del bot deportivo.
    try:
        from backend.api.services.agent_knowledge import sincronizar_conocimiento_json
        from backend.api.services.task_orchestrator import recuperar_tareas_interrumpidas

        recuperar_tareas_interrumpidas()
        with SessionLocal() as db:
            sincronizar_conocimiento_json(db)
    except Exception:
        log.exception("No se pudo inicializar el estado del agente al arrancar; main.py continúa")

    # Bug real encontrado 2026-09-10 (Telegram inalcanzable en la red real durante una
    # verificación de rutina): si `bot_app.updater.start_polling()` falla (red, DNS, Telegram
    # caído), la excepción se propagaba sin atrapar y el `lifespan` entero fallaba —
    # `ERROR: Application startup failed. Exiting.`, tumbando TODA la API HTTP (web, app,
    # admin, scheduler) por un problema de un componente que debería ser una extensión, no una
    # dependencia dura (mismo principio que ya se verificó para el motor/IA — ver
    # el registro de decisiones del proyecto 2026-09-09/10). Envuelto en try/except: si el bot no puede
    # arrancar, se loguea el error real y la API sigue viva sin el bot — igual que ya pasa
    # cuando falta `TELEGRAM_BOT_TOKEN`.
    bot_app = None
    if settings.TELEGRAM_BOT_TOKEN:
        from backend.api.bot.laplace_bot import construir_app

        try:
            bot_app = construir_app()
            bot_app.bot_data["http_client"] = app.state.http_client
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling()
        except Exception:
            log.exception(
                "El bot de Telegram no pudo arrancar (red/Telegram inalcanzable) — la API "
                "HTTP sigue corriendo sin el bot, no es una dependencia dura"
            )
            bot_app = None
    else:
        log.warning("TELEGRAM_BOT_TOKEN no configurado — el bot de Telegram no arranca")

    # APScheduler reemplaza los cron triggers de n8n (WF-D 9AM Chile, WF-E cada 2h + 07:00) —
    # antes solo invocables a mano vía routers/scheduler.py; ahora corren automáticos, igual
    # que en producción hoy con n8n.
    ap_scheduler = AsyncIOScheduler(timezone=TZ_CHILE)
    ap_scheduler.add_job(_job_verificar_fuentes, CronTrigger(hour=7, minute=30, timezone=TZ_CHILE), id="fuentes_deportivas_health")
    # Auto-evaluación diaria (laplace-agents) — corre ANTES de Top Picks (9am) para que la
    # mayoría de los partidos de liga conocida del día ya estén analizados/cacheados cuando
    # arranca el resto del día. Ver `_job_laplace_agents` arriba.
    ap_scheduler.add_job(_job_laplace_agents, CronTrigger(hour=8, minute=0, timezone=TZ_CHILE), id="laplace_agents_autoeval")
    ap_scheduler.add_job(_job_top_picks, CronTrigger(hour=9, minute=0, timezone=TZ_CHILE), id="wfd_top_picks")
    ap_scheduler.add_job(_job_resultados, CronTrigger(hour="*/2", minute=0, timezone=TZ_CHILE), id="wfe_resultados_2h")
    ap_scheduler.add_job(_job_resultados, CronTrigger(hour=7, minute=0, timezone=TZ_CHILE), id="wfe_resultados_7am")
    # Refresco de cuotas/tablas de hoy y mañana, con tope diario de peticiones (ver
    # `_job_refresco_cuotas`). Dos pasadas al día: antes de Top Picks/auto-evaluación no hace falta
    # (la caché de liga dura 2h), por eso 07:15 y 15:15 y no más — el tope protege la cuota mensual.
    ap_scheduler.add_job(_job_refresco_cuotas, CronTrigger(hour="7,15", minute=15, timezone=TZ_CHILE), id="refresco_cuotas")
    # Colector diario de resultados (ver `_job_colectar_resultados`): 02:30 captura la jornada completa
    # de ayer (incluida la de América) y 12:30 la de la mañana en Asia/Europa; no choca con los demás.
    ap_scheduler.add_job(_job_colectar_resultados, CronTrigger(hour="2,12", minute=30, timezone=TZ_CHILE), id="colector_resultados")
    # Reajuste semanal de modelos con la capa de resultados en vivo (domingo de madrugada, hora
    # Chile, cuando casi no hay partidos ni tráfico). Ver `_job_reajustar_modelos`.
    ap_scheduler.add_job(_job_reajustar_modelos, CronTrigger(day_of_week="sun", hour=3, minute=30, timezone=TZ_CHILE), id="reajuste_modelos")
    # Mantenimiento: recupera jobs huérfanos colgados en 'procesando' — ver
    # `_job_reset_jobs_colgados` arriba (hallazgo real de la auditoría 2026-09-09).
    ap_scheduler.add_job(_job_reset_jobs_colgados, CronTrigger(minute="*/15", timezone=TZ_CHILE), id="mantenimiento_jobs_colgados")
    # Purga de datos viejos (partidos_dia > 90 días + stats_cache expirado) — ver
    # `_job_purga_datos_viejos` arriba (hallazgo real de la auditoría 2026-09-09). Corre a las
    # 4am hora Chile, madrugada de baja actividad.
    ap_scheduler.add_job(_job_purga_datos_viejos, CronTrigger(hour=4, minute=0, timezone=TZ_CHILE), id="purga_datos_viejos")
    ap_scheduler.start()
    # Expuesto en app.state para que GET /api/v1/scheduler/status pueda confirmar en vivo si
    # sigue corriendo (healthcheck real, ver routers/scheduler.py) — antes no era accesible
    # fuera de este scope de función.
    app.state.ap_scheduler = ap_scheduler

    try:
        yield
    finally:
        ap_scheduler.shutdown(wait=False)
        if bot_app is not None:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        await app.state.http_client.aclose()


app = FastAPI(
    title="Laplace API",
    description="Motor de predicciones deportivas + bot Telegram + gateway app — backend FastAPI",
    version="0.2.0",
    lifespan=lifespan,
)

# Rate limiting (slowapi) — ver backend/api/core/rate_limit.py para el límite elegido y por
# qué. `app.state.limiter` + el exception handler son el wiring que pide slowapi para que
# `RateLimitExceeded` se traduzca a un 429 real en vez de propagar como error 500.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — sin este middleware, un navegador bloquea cualquier llamada de `frontend/` (Astro)
# a esta API si algún endpoint se llega a llamar directo desde el cliente. Origen(es)
# permitidos vía `CORS_ORIGINS` (backend/api/core/config.py) — si está vacío (default), no
# se agrega el middleware y el comportamiento por default de FastAPI/Starlette (sin headers
# CORS) queda como está: restrictivo, ningún origen cross-site puede leer la respuesta.
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Sin esto el navegador no puede leer `Retry-After` de un 429 y la interfaz no sabe cuánto esperar.
        expose_headers=["Retry-After", "X-RateLimit-Remaining"],
    )

app.include_router(deportivo.router)
app.include_router(partidos.router)
app.include_router(resultados.router)
app.include_router(scheduler.router)
app.include_router(app_gateway.router)
app.include_router(auth.router)
app.include_router(simulador.router)
app.include_router(web.router)
app.include_router(prediccion_web.router)
app.include_router(admin.router)
app.include_router(track_record.router)
app.include_router(agent.router)
app.include_router(web_catalog.router)

# Alias de compatibilidad — la app Android instalada hoy (LaplaceApi.kt) llama a
# `POST /webhook/kairos-app`, el path real del webhook de WF-A2 en n8n. `app_gateway.deportivo`
# ya expone la misma lógica en `/api/v1/deportivo` (path nuevo, consistente con el resto de la
# API) — se registra la MISMA función acá también para no depender de actualizar la app ya
# instalada antes de que el backend nuevo esté detrás del túnel. Encontrado 2026-09-08 auditando
# la conexión app↔backend — ver el registro de decisiones del proyecto.
app.add_api_route("/webhook/kairos-app", app_gateway.deportivo, methods=["POST"])


@app.get("/health")
def health() -> dict:
    """Healthcheck mínimo del backend deportivo, independiente de Telegram y del agente."""
    return {"status": "ok", "component": "sports-bot", "version": app.version}


@app.get("/api/v1/health")
def health_v1() -> dict:
    return {"status": "ok"}


@app.get("/capabilities")
def capabilities() -> dict:
    return {"component": "sports-bot", "independent": True, "capabilities": ["football", "fixtures", "predictions", "odds", "results", "top-picks", "telegram-sports"], "optional_extensions": ["agent"]}


@app.get("/dependencies/agent")
async def agent_dependency() -> dict:
    """Detecta el agente sin convertirlo en requisito del bot deportivo."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.AGENT_URL.rstrip('/')}/capabilities")
            response.raise_for_status()
            return {"available": True, "url": settings.AGENT_URL, "capabilities": response.json()}
    except Exception as exc:
        return {"available": False, "url": settings.AGENT_URL, "reason": type(exc).__name__}


# La web compilada (frontend/dist), si existe, se entrega desde este mismo puerto: instalación portable sin Node.
from backend.api.web_estatico import montar_web  # noqa: E402

montar_web(app, settings.repo_root)
