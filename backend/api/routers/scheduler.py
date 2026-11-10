"""routers/scheduler.py — Disparo manual de los reemplazos de WF-D y WF-E.

Decisión tomada por el hilo principal (ver el registro de decisiones del proyecto): estos mismos ciclos ya
están cableados a `AsyncIOScheduler` (APScheduler) en el `lifespan` de `main.py` — corren
automático mientras el proceso esté vivo, con la misma cadencia que tenían los cron triggers de
n8n (WF-D 9AM Chile, WF-E cada 2h + 07:00). Estos endpoints quedan además como disparo MANUAL —
útil para forzar una corrida fuera de horario, probar en un entorno donde el proceso no corre
24/7 todavía, o depurar un ciclo puntual sin esperar al próximo disparo automático.

2026-09-09 — CRÍTICO, hallazgo de auditoría: hasta esta ronda `POST /resultados` y
`POST /top-picks` no tenían NINGUNA protección — cualquiera con la URL podía forzar una
publicación real al canal de Telegram o gastar cuota de las APIs externas. Ahora exigen
`Depends(requerir_admin)` (mismo mecanismo que `routers/admin.py`, JWT de sesión + `plan ==
"admin"`) a nivel de router. Esto NO afecta al cron automático de `main.py::lifespan`
(`_job_top_picks`/`_job_resultados`) — esas funciones llaman directo a
`services/top_picks.py`/`services/resultados_scheduler.py`, nunca pasan por esta capa HTTP ni
por sus dependencies.

También agrega `GET /status` (mismo nivel de protección) — healthcheck real del scheduler:
si `AsyncIOScheduler` sigue corriendo (`app.state.ap_scheduler`, expuesto desde `main.py`) y la
hora del último run exitoso de cada job (`db/scheduler_repo.py`, tabla `scheduler_runs`)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

# `laplace-agents/` vive fuera de `backend/` a propósito (ver `laplace_agents/core.py` y su
# README) — guarda defensiva redundante con la de `main.py`, en caso de que este router se
# importe alguna vez sin pasar primero por `main.py` (ej. un test que solo importa el router).
_LAPLACE_AGENTS_DIR = Path(__file__).resolve().parents[3] / "backend" / "agents"
if str(_LAPLACE_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_LAPLACE_AGENTS_DIR))
import laplace_agents  # noqa: E402

from backend.api.core.auth_deps import requerir_admin  # noqa: E402
from backend.api.db import scheduler_repo  # noqa: E402
from backend.api.db.session import get_db  # noqa: E402
from backend.api.ml import job_reajuste  # noqa: E402
from backend.api.services import colector_resultados, refresco_cuotas, resultados_scheduler, top_picks  # noqa: E402

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"], dependencies=[Depends(requerir_admin)])

# Nombres lógicos de job usados en `scheduler_runs.job_name` — compartidos con `main.py`
# (donde el cron automático registra sus propias corridas). WF-E corre bajo dos ids de cron
# distintos (`wfe_resultados_2h`/`wfe_resultados_7am`) pero es la misma lógica, así que ambos
# se registran bajo `JOB_RESULTADOS`.
JOB_TOP_PICKS = "wfd_top_picks"
JOB_RESULTADOS = "wfe_resultados"
JOB_LAPLACE_AGENTS = "laplace_agents_autoeval"
JOB_FUENTES_DEPORTIVAS = "fuentes_deportivas_health"
JOB_REFRESCO_CUOTAS = "refresco_cuotas"
JOB_REAJUSTE_MODELOS = "reajuste_modelos"
JOB_COLECTOR_RESULTADOS = "colector_resultados"

# Ventanas de control, no cron nuevos. Si la API se reinicia o el scheduler deja de correr,
# `/status` debe mostrarlo aunque el proceso aún responda `/health`.
VENTANA_MINUTOS = {
    JOB_RESULTADOS: 180,
    JOB_TOP_PICKS: 1_560,
    JOB_LAPLACE_AGENTS: 1_560,
    JOB_FUENTES_DEPORTIVAS: 1_560,
    # Corre a las 07:15 y 15:15 Chile: el hueco más largo entre corridas es de 16h; 18h de margen.
    JOB_REFRESCO_CUOTAS: 1_080,
    # Corre a las 02:30 y 12:30 Chile: el hueco más largo es de 14h; 18h de margen.
    JOB_COLECTOR_RESULTADOS: 1_080,
    # Semanal (domingo 03:30 Chile): 7 días + 1 de margen.
    JOB_REAJUSTE_MODELOS: 11_520,
}


def _estado_run(ejecutado_en: str | None, ventana_minutos: int, ahora: datetime | None = None) -> dict:
    if not ejecutado_en:
        return {"estado": "nunca", "atrasado": True, "edad_minutos": None, "ventana_minutos": ventana_minutos}
    try:
        cuando = datetime.fromisoformat(ejecutado_en.replace("Z", "+00:00"))
        # scheduler_repo persiste UTC sin offset. Los valores antiguos sin zona se interpretan
        # como UTC para evitar que la hora local altere falsamente la salud del scheduler.
        cuando = cuando.replace(tzinfo=timezone.utc) if cuando.tzinfo is None else cuando.astimezone(timezone.utc)
    except ValueError:
        return {"estado": "fecha_invalida", "atrasado": True, "edad_minutos": None, "ventana_minutos": ventana_minutos}
    referencia = ahora or datetime.now(timezone.utc)
    referencia = referencia.replace(tzinfo=timezone.utc) if referencia.tzinfo is None else referencia.astimezone(timezone.utc)
    edad = max(0, int((referencia - cuando).total_seconds() // 60))
    return {"estado": "atrasado" if edad > ventana_minutos else "al_dia", "atrasado": edad > ventana_minutos,
            "edad_minutos": edad, "ventana_minutos": ventana_minutos}


@router.post("/resultados")
async def disparar_ciclo_resultados(db: Session = Depends(get_db)) -> dict:
    """Reemplaza el cron cada 2h + 07:00 de WF-E."""
    async with httpx.AsyncClient() as client:
        try:
            resultado = await resultados_scheduler.ejecutar_ciclo_resultados(db, client)
        except Exception as exc:
            scheduler_repo.registrar_run(db, JOB_RESULTADOS, ok=False, detalle=type(exc).__name__)
            raise
        scheduler_repo.registrar_run(db, JOB_RESULTADOS, ok=True, detalle="disparo_manual")
        return resultado


@router.post("/top-picks")
async def disparar_top_picks(publicar: bool = True, db: Session = Depends(get_db)) -> dict:
    """Reemplaza el cron 9AM Chile de WF-D. `publicar=false` genera el análisis sin enviarlo
    al canal (para revisar antes de publicar manualmente, o cuando el flujo de confianza baja
    del bot todavía no está conectado)."""
    async with httpx.AsyncClient() as client:
        try:
            resultado = await top_picks.generar_top_picks_dia(db, client)
            if publicar:
                resultado["publicado"] = await top_picks.publicar_top_picks(db, client, resultado)
        except Exception as exc:
            scheduler_repo.registrar_run(db, JOB_TOP_PICKS, ok=False, detalle=type(exc).__name__)
            raise
        scheduler_repo.registrar_run(db, JOB_TOP_PICKS, ok=True, detalle="disparo_manual")
        return resultado


@router.post("/laplace-agents")
async def disparar_laplace_agents(fecha: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Dispara a mano la auto-evaluación diaria (`services/laplace_agents.py`) — el sistema se
    analiza a sí mismo (ligas conocidas del día, sin IA) para no depender de que un usuario
    real pida algo. Corre automático a las 8am Chile (ver `main.py::lifespan`); este endpoint
    es para forzar una corrida fuera de horario o probar contra una `fecha` puntual
    (YYYY-MM-DD, default hoy).

    2026-09-10 — a propósito NO chequea `settings.LAPLACE_AGENTS_ACTIVO`: ese flag apaga el
    cron automático de las 8am (`main.py::_job_laplace_agents`), no la capacidad de un admin de
    forzar una corrida puntual — alguien que llega hasta acá (ya pasó `requerir_admin`) y
    dispara esto a mano expresa intención explícita de correrlo ahora, con flag apagado o no
    (mismo caso de uso que "probar el ciclo mientras está desactivado el automático"). Si algún
    día se necesita que el flag también bloquee el disparo manual, agregar el mismo chequeo de
    `_job_laplace_agents` acá — no asumido hoy."""
    async with httpx.AsyncClient() as client:
        try:
            resultado = await laplace_agents.ejecutar_ciclo_autoevaluacion(db, client, fecha=fecha)
        except Exception as exc:
            scheduler_repo.registrar_run(db, JOB_LAPLACE_AGENTS, ok=False, detalle=type(exc).__name__)
            raise
        scheduler_repo.registrar_run(
            db, JOB_LAPLACE_AGENTS, ok=True,
            detalle=f"disparo_manual {resultado['analizados']}/{resultado['candidatos_liga_conocida']}",
        )
        return resultado


@router.post("/refresco-cuotas")
async def disparar_refresco_cuotas(db: Session = Depends(get_db)) -> dict:
    """Dispara a mano el refresco de odds/standings de hoy y mañana (mismo código y mismo tope
    diario que el cron de `main.py`: gasta cuota real de The Odds API, hasta el tope)."""
    async with httpx.AsyncClient() as client:
        try:
            resumen = await refresco_cuotas.ejecutar_refresco_cuotas(db, client)
        except Exception as exc:
            scheduler_repo.registrar_run(db, JOB_REFRESCO_CUOTAS, ok=False, detalle=type(exc).__name__)
            raise
        scheduler_repo.registrar_run(
            db, JOB_REFRESCO_CUOTAS, ok=resumen["ok"], detalle="disparo_manual " + refresco_cuotas.detalle_corto(resumen)
        )
        return resumen


@router.post("/colectar-resultados")
async def disparar_colector_resultados(
    fechas: list[str] | None = Query(default=None, description="YYYY-MM-DD; por defecto hoy-3 a mañana"),
    exportar: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    """Dispara a mano el colector diario de resultados (mismo código y mismo tope diario de peticiones que
    el cron: gasta cuota real de LiveScore6, hasta el tope). Fechas inválidas o fuera de [hoy-7, hoy+2]
    se rechazan sin gastar cuota. Con `exportar=true` regenera la capa en vivo. Ignora
    `LAPLACE_COLECTOR_ACTIVO` (apaga solo el cron), como `/reajustar-modelos`."""
    async with httpx.AsyncClient() as client:
        try:
            resumen = await colector_resultados.ejecutar_colector(db, client, fechas=fechas)
        except Exception as exc:
            scheduler_repo.registrar_run(db, JOB_COLECTOR_RESULTADOS, ok=False, detalle=type(exc).__name__)
            raise
    resumen["exportacion"] = await asyncio.to_thread(colector_resultados.exportar_capa_vivo) if exportar else None
    exportacion_ok = resumen["exportacion"]["ok"] if resumen["exportacion"] else True
    scheduler_repo.registrar_run(
        db, JOB_COLECTOR_RESULTADOS, ok=resumen["ok"] and exportacion_ok,
        detalle="disparo_manual " + colector_resultados.detalle_corto(resumen),
    )
    return resumen


@router.post("/reajustar-modelos")
async def disparar_reajuste_modelos(db: Session = Depends(get_db)) -> dict:
    """Dispara a mano el reajuste de los Dixon-Coles con resultados en vivo (mismo código que el cron
    semanal: exporta, reentrena, valida y reemplaza el artefacto solo si la validación pasa). Corre en un
    subproceso con `LAPLACE_PYTHON_ML`; si faltan numpy/scipy responde `ok: false` con el motivo, sin
    error HTTP. Como `/laplace-agents`, ignora `LAPLACE_REAJUSTE_AUTOMATICO` (apaga solo el cron)."""
    resultado = await asyncio.to_thread(job_reajuste.ejecutar_reajuste)
    scheduler_repo.registrar_run(db, JOB_REAJUSTE_MODELOS, ok=resultado["ok"], detalle="disparo_manual " + resultado["detalle"])
    return resultado


@router.get("/status")
def estado_scheduler(request: Request, db: Session = Depends(get_db)) -> dict:
    """Healthcheck real: ¿sigue vivo `AsyncIOScheduler` en este proceso?, y ¿cuándo fue la
    última corrida exitosa (automática o manual) de cada job? Un `/health` en 200 no prueba
    nada de esto (ver `.claude/rules/deploy-safety.md`)."""
    ap_scheduler = getattr(request.app.state, "ap_scheduler", None)
    corriendo = ap_scheduler is not None and ap_scheduler.running

    jobs = {}
    for nombre in VENTANA_MINUTOS:
        ultimo_ok = scheduler_repo.ultimo_run_exitoso(db, nombre)
        ultimo = scheduler_repo.ultimo_run(db, nombre)
        jobs[nombre] = {
            "ultimo_exitoso_en": ultimo_ok.ejecutado_en if ultimo_ok else None,
            "ultima_corrida_en": ultimo.ejecutado_en if ultimo else None,
            "ultima_corrida_ok": ultimo.ok if ultimo else None,
            **_estado_run(ultimo_ok.ejecutado_en if ultimo_ok else None, VENTANA_MINUTOS[nombre]),
        }
        if nombre == JOB_REAJUSTE_MODELOS and not job_reajuste.reajuste_activo():
            # Apagado a propósito (LAPLACE_REAJUSTE_AUTOMATICO=0): no es un atraso ni vuelve insalubre el scheduler.
            jobs[nombre].update({"estado": "desactivado", "atrasado": False})
        if nombre == JOB_COLECTOR_RESULTADOS and not colector_resultados.colector_activo():
            jobs[nombre].update({"estado": "desactivado", "atrasado": False})

    return {"scheduler_corriendo": corriendo, "saludable": corriendo and not any(item["atrasado"] for item in jobs.values()), "jobs": jobs}
