"""models/bot_memoria.py — memoria mínima del bot de Telegram (MB-30): preferencias, historial de consultas y consentimiento.

Tres tablas, todas por `user_id` (el chat de Telegram). Sin mensajes libres (eso es del agente). Todo se borra con `/olvidame` (`db/bot_memoria_repo.olvidar`); una prueba falla si aparece
una tabla `bot_*` que ese borrado no cubra.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class BotPreferencias(Base):
    __tablename__ = "bot_preferencias"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    equipos_favoritos: Mapped[str | None] = mapped_column(Text, nullable=True)  # nombres separados por "|", hasta 5
    idioma: Mapped[str] = mapped_column(String(8), nullable=False, default="es")
    personalizar: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 0 = no ordenar nada por favoritos
    avisos: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # 1 = quiere el aviso diario de sus favoritos (MB-34)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class BotHistorialConsulta(Base):
    __tablename__ = "bot_historial_consultas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    partido_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fecha_partido: Mapped[str | None] = mapped_column(String(16), nullable=True)
    creado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class BotConsentimiento(Base):
    __tablename__ = "bot_consentimientos"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    aceptado_en: Mapped[str] = mapped_column(String(32), nullable=False)
    revocado_en: Mapped[str | None] = mapped_column(String(32), nullable=True)


class BotAvisoEnviado(Base):
    """Un aviso ya enviado (MS-4): `previo` (hoy juega, con el pronóstico del modelo que se mandó) o `resultado` (el final). La clave única es lo que garantiza UN aviso por partido y tipo."""

    __tablename__ = "bot_avisos_enviados"
    __table_args__ = (UniqueConstraint("user_id", "partido_id", "tipo", name="uq_bot_avisos_enviados"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    partido_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # previo | resultado
    pronostico_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # {"local","empate","visitante"} que se mandó en el aviso previo; None si el modelo no cubría el partido
    enviado_en: Mapped[str] = mapped_column(String(32), nullable=False)


class BotPerfilUsuario(Base):
    """Memoria TIPADA del usuario (MS-6): zona horaria, estilo de respuesta y mercados que mira. Campos con tope duro (nunca se trunca en silencio), solo con consentimiento, y la borra `/olvidame`."""

    __tablename__ = "bot_perfil_usuario"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    zona_horaria: Mapped[str | None] = mapped_column(String(40), nullable=True)  # nombre IANA, p. ej. America/Santiago
    estilo: Mapped[str | None] = mapped_column(String(12), nullable=True)  # corto | normal | tecnico
    mercados: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 1x2|goles|ambos marcan|mas de 2,5 (hasta 4)
    actualizado_en: Mapped[str] = mapped_column(String(32), nullable=False)
