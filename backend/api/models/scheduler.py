"""models/scheduler.py — `scheduler_runs`: rastro real de cada corrida de los jobs de
APScheduler (WF-D top-picks, WF-E resultados), tanto automáticas (cron en `main.py::lifespan`)
como manuales (`routers/scheduler.py`).

Agregado 2026-09-09 — antes no había forma de saber si el scheduler seguía vivo o si un job
llevaba días sin correr sin ir a revisar logs a mano. Ver `GET /api/v1/scheduler/status`
(`routers/scheduler.py`), que lee la última fila `ok=True` por `job_name` acá."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 'wfd_top_picks' | 'wfe_resultados' — nombre lógico del job, no el id interno de
    # APScheduler (que para resultados tiene dos ids de cron distintos, `wfe_resultados_2h` y
    # `wfe_resultados_7am`, corriendo la misma lógica — se registran bajo el mismo job_name).
    job_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ejecutado_en: Mapped[str] = mapped_column(Text, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Motivo corto en corridas ok=True sin acción visible (ej. 'sin_candidatos'), o el tipo de
    # excepción en ok=False — nunca el stack trace completo (eso ya va al log real).
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
