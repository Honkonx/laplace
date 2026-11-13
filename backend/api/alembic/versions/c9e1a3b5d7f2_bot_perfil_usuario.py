"""Memoria tipada del usuario (`bot_perfil_usuario`): zona horaria, estilo de respuesta y mercados que mira (MS-6)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1a3b5d7f2"
down_revision: Union[str, None] = "b8d0f2a4c6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_perfil_usuario",
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("zona_horaria", sa.String(length=40), nullable=True),
        sa.Column("estilo", sa.String(length=12), nullable=True),
        sa.Column("mercados", sa.String(length=80), nullable=True),
        sa.Column("actualizado_en", sa.String(length=32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bot_perfil_usuario")
