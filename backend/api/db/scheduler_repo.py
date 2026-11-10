"""db/scheduler_repo.py — Registro y lectura de corridas de los jobs de APScheduler.

Ver docstring de `models/scheduler.py`. `registrar_run` nunca lanza — un fallo al escribir el
propio registro de auditoría no debería tumbar el job real que lo llama (mismo criterio que
`services/telegram_client.py::enviar_mensaje`: nunca se traga el error en silencio, pero
tampoco propaga uno que no es el del job en sí)."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.scheduler import SchedulerRun

log = logging.getLogger("laplace.scheduler_repo")


def _now_str() -> str:
    """`ejecutado_en` — normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`).
    Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def registrar_run(db: Session, job_name: str, ok: bool, detalle: str | None = None) -> None:
    try:
        db.add(SchedulerRun(job_name=job_name, ejecutado_en=_now_str(), ok=ok, detalle=detalle))
        db.commit()
    except Exception:
        log.warning("Fallo registrando corrida de scheduler job_name=%s", job_name, exc_info=True)
        db.rollback()


def ultimo_run_exitoso(db: Session, job_name: str) -> SchedulerRun | None:
    return (
        db.query(SchedulerRun)
        .filter(SchedulerRun.job_name == job_name, SchedulerRun.ok.is_(True))
        .order_by(SchedulerRun.id.desc())
        .first()
    )


def ultimo_run(db: Session, job_name: str) -> SchedulerRun | None:
    """Última corrida (exitosa o no) — útil para distinguir "nunca corrió" de "corrió y falló"."""
    return (
        db.query(SchedulerRun)
        .filter(SchedulerRun.job_name == job_name)
        .order_by(SchedulerRun.id.desc())
        .first()
    )
