"""models/jobs.py — jobs (cola de análisis, Telegram + app)."""
from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class Job(Base):
    __tablename__ = "jobs"
    # Índices agregados 2026-09-09 (auditoría real de queries — confirmado leyendo
    # db/jobs_repo.py, db/analisis_repo.py, db/push_repo.py, db/usuarios_repo.py):
    # - match_id: WHERE frecuente (verificar_job_activo en jobs_repo.py/analisis_repo.py,
    #   leer_match_subscriptores en push_repo.py, join en usuarios_repo.leer_racha).
    # - (device_id_app, status): combinados en el mismo WHERE en analisis_repo.py
    #   (leer_historial_app, leer_top_picks_app, verificar_partido_completo).
    __table_args__ = (
        Index("ix_jobs_device_id_app_status", "device_id_app", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    match_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    fecha_partido: Mapped[str] = mapped_column(String, nullable=False)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    origen: Mapped[str] = mapped_column(String, nullable=False, default="telegram")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    completado_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    # migraciones
    user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    device_id_app: Mapped[str | None] = mapped_column(Text, nullable=True)
    resultado_app: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_app: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante_app: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga_app: Mapped[str | None] = mapped_column(Text, nullable=True)
