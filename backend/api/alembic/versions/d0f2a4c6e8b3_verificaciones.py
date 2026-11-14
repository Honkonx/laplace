"""Cola de verificación (`verificaciones`): cada pronóstico emitido se verifica solo a la hora del partido (AU-2)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0f2a4c6e8b3"
down_revision: Union[str, None] = "c9e1a3b5d7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verificaciones",
        sa.Column("partido_id", sa.String(length=64), primary_key=True),
        sa.Column("fecha_partido", sa.String(length=16), nullable=True),
        sa.Column("inicio_utc", sa.String(length=24), nullable=True),
        sa.Column("local", sa.Text(), nullable=True),
        sa.Column("visitante", sa.Text(), nullable=True),
        sa.Column("liga", sa.Text(), nullable=True),
        sa.Column("origen", sa.String(length=24), nullable=False, server_default="bot"),
        sa.Column("estado", sa.String(length=16), nullable=False, server_default="pendiente"),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proximo_intento", sa.String(length=24), nullable=True),
        sa.Column("ultima_fuente", sa.String(length=24), nullable=True),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("goles_local", sa.Integer(), nullable=True),
        sa.Column("goles_visitante", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.String(length=24), nullable=False),
        sa.Column("resuelto_en", sa.String(length=24), nullable=True),
    )
    op.create_index("ix_verificaciones_fecha_partido", "verificaciones", ["fecha_partido"])
    op.create_index("ix_verificaciones_estado", "verificaciones", ["estado"])
    op.create_index("ix_verificaciones_proximo_intento", "verificaciones", ["proximo_intento"])


def downgrade() -> None:
    op.drop_table("verificaciones")
