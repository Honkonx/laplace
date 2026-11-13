"""Memoria mínima del bot: preferencias, historial de consultas y consentimiento (MB-30)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fa7b8c9d0e1f"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_preferencias",
        sa.Column("user_id", sa.String(64), primary_key=True), sa.Column("equipos_favoritos", sa.Text()),
        sa.Column("idioma", sa.String(8), nullable=False), sa.Column("personalizar", sa.Integer(), nullable=False),
        sa.Column("actualizado_en", sa.String(32), nullable=False),
    )
    op.create_table(
        "bot_historial_consultas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("partido_id", sa.String(64), nullable=False), sa.Column("fecha_partido", sa.String(16)),
        sa.Column("creado_en", sa.String(32), nullable=False),
    )
    op.create_index("ix_bot_historial_consultas_user_id", "bot_historial_consultas", ["user_id"])
    op.create_table(
        "bot_consentimientos",
        sa.Column("user_id", sa.String(64), primary_key=True), sa.Column("version", sa.String(16), nullable=False),
        sa.Column("aceptado_en", sa.String(32), nullable=False), sa.Column("revocado_en", sa.String(32)),
    )


def downgrade() -> None:
    op.drop_table("bot_consentimientos")
    op.drop_index("ix_bot_historial_consultas_user_id", table_name="bot_historial_consultas")
    op.drop_table("bot_historial_consultas")
    op.drop_table("bot_preferencias")
