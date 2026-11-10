"""models/tokens.py — `token_revocado`: lista de negación de JWT de sesión cerrados con logout.

Agregado 2026-09-08. El JWT que emite `routers/auth.py::_emitir_token` vive
`WEB_JWT_EXPIRA_HORAS` (30 días) sin ninguna forma de invalidarlo antes de su expiración natural
— si se filtra, sirve el resto de esos 30 días completos. Esta tabla NO es una lista de tokens
activos (eso requeriría guardar todos los `jti` emitidos) — es una lista de negación: cualquier
`jti` que aparezca acá queda inválido aunque su firma/expiración sigan siendo válidas (ver
`core/auth_deps.py::obtener_usuario_actual`). Tokens emitidos ANTES de este cambio no tienen
claim `jti` — se dejan pasar sin chequeo de revocación, se auto-resuelven solos cuando expiren
naturalmente (máximo 30 días desde el despliegue de este cambio).
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class TokenRevocado(Base):
    __tablename__ = "token_revocado"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    revocado_en: Mapped[str] = mapped_column(Text, nullable=False)
