"""models/metricas.py — métricas de costo/latencia por proveedor de IA (metricas_ia_proveedor).

Migración `e0b8b0bd13dd` aplicada y verificada contra la BD real 2026-09-10
(`.claude/rules/database-safety.md`). `services/ai_metrics.py::registrar_intento` escribe acá
una fila real por cada intento (éxito o fallo) a un proveedor de la cascada de IA, además del
log estructurado y el acumulador in-memory que ya tenía — ver el docstring de ese módulo.
"""
from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class MetricaIaProveedor(Base):
    """Una fila por intento (éxito o fallo) a un proveedor de la cascada de IA
    (Gemini → Groq → OpenRouter → Claude, ver `services/ai_client.py`) — instrumentación real de
    costo/latencia para poder responder con datos reales (no percepción) preguntas como "¿qué
    proveedor falla más?" o "¿cuál es más lento?" antes de decidir reordenar la cascada o
    agregar/quitar un proveedor."""

    __tablename__ = "metricas_ia_proveedor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proveedor: Mapped[str] = mapped_column(String, nullable=False, index=True)
    modelo: Mapped[str | None] = mapped_column(Text, nullable=True)
    exitoso: Mapped[int] = mapped_column(Integer, nullable=False)
    latencia_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(String, nullable=False, index=True)


class EstadoFuenteDeportiva(Base):
    """Última prueba operativa de cada proveedor deportivo, sin secretos."""
    __tablename__ = "estado_fuentes_deportivas"

    fuente: Mapped[str] = mapped_column(String(64), primary_key=True)
    configurada: Mapped[int] = mapped_column(Integer, nullable=False)
    saludable: Mapped[int] = mapped_column(Integer, nullable=False)
    status_http: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latencia_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cuota_restante: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    verificado_en: Mapped[str] = mapped_column(String, nullable=False, index=True)
