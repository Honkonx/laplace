"""models/push.py — push_tokens (Expo push notifications)."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class PushToken(Base):
    __tablename__ = "push_tokens"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    expo_push_token: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="android")
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    actualizado_en: Mapped[str] = mapped_column(Text, nullable=False)
