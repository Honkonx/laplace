"""Avisos ya enviados por el bot (`bot_avisos_enviados`): un aviso por partido y tipo (previo / resultado), con el pronóstico que se mandó (MS-4)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e1"
down_revision: Union[str, None] = "a7c9e1f3b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_avisos_enviados",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("partido_id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("pronostico_json", sa.Text(), nullable=True),
        sa.Column("enviado_en", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("user_id", "partido_id", "tipo", name="uq_bot_avisos_enviados"),
    )
    op.create_index("ix_bot_avisos_enviados_user_id", "bot_avisos_enviados", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_avisos_enviados_user_id", table_name="bot_avisos_enviados")
    op.drop_table("bot_avisos_enviados")
