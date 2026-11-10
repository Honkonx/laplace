"""models/auditoria.py — `historial_plan`, `intento_login_fallido` y `accion_admin_auditoria`:
señales que el sistema ya calcula hoy pero descartaba sin persistir.

Agregadas 2026-09-08, durante la auditoría de permisos/BD de esta ronda — ver
`.claude/rules/product-philosophy.md` (cualquier número que el sistema muestra debe poder
trazarse a su origen, no quedar opaco).

- `HistorialPlan`: `db/codigos_repo.py::activar_codigo` y `db/admin_repo.py::gestionar_usuario`
  (`accion='cambiar_plan'`/`'agregar'`) ya sobrescriben `Usuario.plan`/`activo_hasta` hoy — pero
  ninguna de las dos deja rastro de POR QUÉ cambió el plan (código canjeado por el propio
  usuario vs asignación manual de un admin). Sin esto, un admin no puede auditar "¿de dónde
  salió este plan pro?" más allá del valor actual.
- `IntentoLoginFallido`: `routers/auth.py::login` hoy solo devuelve 401 genérico (correcto,
  nunca debe revelar si falló el usuario o la clave) pero no deja ningún rastro del intento — un
  admin no puede ver patrones de fuerza bruta contra un username. Nunca guarda la contraseña
  (ver `.claude/rules/secrets-never-revealed.md`), solo el username intentado y el momento.
- `AccionAdminAuditoria`: agregada 2026-09-09, auditoría de esta sesión — `bot/laplace_bot.py
  ::cmd_generarcodigos` (genera códigos de acceso vendibles) no dejaba ningún rastro de quién
  lo ejecutó más allá de logs de proceso. No reutiliza `HistorialPlan` a propósito: esa tabla
  representa el cambio de plan de un `device_id` puntual (`device_id` es NOT NULL, es la clave
  del registro) — generar un lote de códigos no es un cambio de plan de ningún usuario todavía
  (el código puede no canjearse nunca), forzarlo ahí mezclaría dos eventos distintos bajo la
  misma columna `device_id` y rompería esa invariante para futuras auditorías. Pensada como
  tabla genérica para cualquier acción admin sensible sin device_id asociado, no solo
  `generar_codigos`.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class HistorialPlan(Base):
    __tablename__ = "historial_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plan_anterior: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_nuevo: Mapped[str] = mapped_column(String, nullable=False)
    medio: Mapped[str] = mapped_column(String, nullable=False)  # 'codigo' | 'admin'
    # Código canjeado (medio='codigo') o device_id/user_id del admin que hizo el cambio
    # (medio='admin', puede ser None si no se identificó al actor).
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class IntentoLoginFallido(Base):
    __tablename__ = "intento_login_fallido"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username_intentado: Mapped[str] = mapped_column(String, nullable=False, index=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)


class AccionAdminAuditoria(Base):
    """Auditoría genérica de acciones admin sensibles que no son un cambio de plan de un
    `device_id` puntual (ver `HistorialPlan` para eso) — ej. generación de códigos de acceso
    en lote. Ver docstring del módulo para por qué no se reusó `HistorialPlan`."""

    __tablename__ = "accion_admin_auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_admin_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    accion: Mapped[str] = mapped_column(String, nullable=False)  # ej. 'generar_codigos'
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
