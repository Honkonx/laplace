"""models/verificacion.py — cola de verificación: cada pronóstico emitido queda aquí hasta conocer el resultado real del partido.

Una fila por partido (`partido_id`), sin importar cuántos canales lo pronosticaron (bot, agente, laboratorio, modelo). El verificador (`services/verificacion.py`)
la recorre cada pocos minutos, pregunta el resultado a partir de inicio + 140 min y, al cerrar, escribe `resultados_partidos` y califica todo lo enlazado.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class Verificacion(Base):
    __tablename__ = "verificaciones"

    partido_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fecha_partido: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)  # AAAA-MM-DD de Chile
    inicio_utc: Mapped[str | None] = mapped_column(String(24), nullable=True)                  # ISO UTC; None = no se conoce (se verifica por fecha)
    local: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    liga: Mapped[str | None] = mapped_column(Text, nullable=True)
    origen: Mapped[str] = mapped_column(String(24), nullable=False, default="bot")             # bot, agente, laboratorio, modelo, autopiloto
    # pendiente | en_juego | final | aplazado | sin_resultado
    estado: Mapped[str] = mapped_column(String(16), nullable=False, default="pendiente", index=True)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    proximo_intento: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)  # ISO UTC
    ultima_fuente: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    goles_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[str] = mapped_column(String(24), nullable=False)
    resuelto_en: Mapped[str | None] = mapped_column(String(24), nullable=True)
