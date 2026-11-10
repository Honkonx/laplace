"""
models/usuarios.py — usuarios (Telegram), codigos_acceso, uso_diario_app, uso_diario_ia_app.

Columnas y nombres idénticos al schema real de db_query.py:init_db()
(CREATE TABLE base + todas las migraciones ALTER TABLE aplicadas) — no se renombra nada
todavía, para que la BD SQLite existente (si se reusa) siga siendo compatible mientras dura
la transición.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    activo: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free")
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    # v4 — LaplaceApp
    nickname: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo_hasta: Mapped[str | None] = mapped_column(Text, nullable=True)
    origen: Mapped[str] = mapped_column(String, nullable=False, default="telegram")
    # v5 — login usuario+clave (app/web, sin correo). Nullable: los usuarios de Telegram
    # siguen sin login, se identifican por device_id=chat_id como siempre. `username` es
    # único a nivel de BD desde 2026-09-09 (`unique=True` — migración 2597240e8e06 ->
    # <ver alembic/versions>, aplicada y verificada contra la BD real con
    # `PRAGMA index_list`). SQLite trata múltiples filas con `username IS NULL` como
    # no-conflictivas entre sí en una constraint UNIQUE estándar (comportamiento nativo,
    # no hace falta un índice parcial) — solo colisiona cuando dos filas tienen el MISMO
    # valor no-nulo, que es exactamente el caso que había que cerrar (TOCTOU real: el
    # router ya chequeaba antes del INSERT, pero sin constraint en BD dos registros
    # concurrentes con el mismo username podían colar ambos). El chequeo previo en
    # `routers/auth.py` se mantiene para dar un mensaje de error claro en el caso normal;
    # la constraint es la red de seguridad real para el caso concurrente (ver
    # `IntegrityError` capturado ahí).
    username: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v6 — favoritos de liga del bot Telegram (`/favoritos`, agregado 2026-09-08). Hasta 3
    # nombres de liga separados por "|" (ej. "LaLiga|Premier League") — texto libre tal cual
    # lo escribe el usuario (no hay catálogo fijo de ligas: vienen dinámicas de la cascada de
    # fixtures), comparado case-insensitive en usuarios_repo. Nullable: la mayoría de usuarios
    # no configura favoritos.
    favoritos_ligas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v7 — rol separado de plan (2026-09-10). Hasta acá "admin" vivía como un pseudo-valor de
    # `plan` (mezclado con el plan de suscripción free/pro/max, ver `core/auth_deps.py` y los
    # límites hardcodeados en `db/usuarios_repo.py`) — decisión del usuario: separar el
    # PERMISO (quién puede administrar/quién es el agente) del PLAN (qué tier de suscripción
    # paga). `rol` es la única fuente de verdad para permisos desde acá; `plan` vuelve a ser
    # 100% tier de suscripción. Valores: "usuario" (default) | "admin" | "agente" (identidad de
    # servicio de `laplace-agents`, ver `ROLES_VALIDOS` en `db/usuarios_repo.py`).
    rol: Mapped[str] = mapped_column(String, nullable=False, default="usuario")
    # Consentimiento explícito y versionado. El servicio guarda conversaciones solo tras aceptar
    # estos términos; no es una casilla visual que el backend pueda ignorar.
    terms_version: Mapped[str | None] = mapped_column(String, nullable=True)
    terms_accepted_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class CodigoAcceso(Base):
    __tablename__ = "codigos_acceso"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False)  # 'pro' | 'max'
    dias: Mapped[int] = mapped_column(Integer, nullable=False)
    usado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    device_id_asignado: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id_usado: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
    usado_en: Mapped[str | None] = mapped_column(Text, nullable=True)


class UsoDiarioApp(Base):
    """Contador freemium de análisis Python/estáticos por device_id — PK compuesta."""

    __tablename__ = "uso_diario_app"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    fecha: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM-DD
    predicciones_usadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UsoDiarioIaApp(Base):
    """Contador freemium de análisis con IA (Claude) por device_id — PK compuesta.

    Separado de UsoDiarioApp — free: 0/día, pro: 10/día (constante en services/, no aquí),
    max/admin: ilimitado.
    """

    __tablename__ = "uso_diario_ia_app"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    fecha: Mapped[str] = mapped_column(String, primary_key=True)
    usados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
