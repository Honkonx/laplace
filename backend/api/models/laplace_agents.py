"""models/laplace_agents.py — memoria propia del agente Laplace-Agents (paquete `laplace-agents/`
en la raíz del repo, separado del backend, ver su `README.md`), distinta de las tablas
compartidas que ya escribe (`analisis_comparativo`, vía `USUARIO_SISTEMA` en
`laplace_agents/core.py`).

Agregado 2026-09-10 (roadmap del paquete: memoria SQL propia + detector de deriva entre
corridas). La BD sigue siendo la misma SQLite compartida del backend — el modelo vive acá
siguiendo el patrón real ya establecido (`laplace_agents/core.py` ya importa
`backend.api.models`/`backend.api.db`), aunque el paquete que lo USA
(`laplace_agents/memoria.py`) viva físicamente fuera de `backend/`.

MIGRACIÓN PENDIENTE: esta ronda de trabajo tiene explícitamente prohibido correr
`alembic revision`/tocar `backend/api/alembic/versions/` (dos agentes más en paralelo también
pueden necesitar modelos nuevos en la misma ronda — generar migraciones Alembic a la vez rompe
la cadena de autogenerate). La tabla existe hoy solo para los tests
(`Base.metadata.create_all()` en `conftest.py`, tanto de `laplace-agents/tests/` como de
`backend/tests/`, que arman el esquema a partir de los modelos) — falta correr
`alembic revision --autogenerate` real (una próxima ronda) antes de que esta tabla exista en
`backend/db/bot_deportivo.db`."""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.db.session import Base


class LaplaceAgentMemoria(Base):
    """Un evento por fila. `tipo_evento` es texto libre ('ciclo_diario', 'deriva_detectada', y
    lo que se agregue a futuro sin requerir una migración de esquema nueva por cada tipo nuevo
    de evento). `resumen` viaja como JSON serializado en una columna Text — mismo patrón que
    `bloque_claude_json`/`pick_externo_detalle` en `AnalisisComparativo`
    (`models/predicciones.py`) — no se modela columna a columna porque el contenido varía según
    `tipo_evento` y esta tabla es de auditoría/trazabilidad del propio agente, no de consulta
    estructurada por el resto del sistema.

    `fecha` es el día de negocio al que corresponde el evento (ej. el día de fixtures que
    procesó esa corrida) — distinto de `creado_en` (timestamp real UTC de cuándo se escribió la
    fila), mismo criterio que ya separa `AnalisisComparativo.fecha` de `.creado_en`."""

    __tablename__ = "laplace_agent_memoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tipo_evento: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resumen: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[str] = mapped_column(Text, nullable=False)
