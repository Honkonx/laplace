"""Contadores diarios de uso del agente que sobreviven a los reinicios (MA-51)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fb8c9d0e1f2a"
down_revision: Union[str, None] = "fa7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_uso_diario",
        sa.Column("clave", sa.String(255), primary_key=True), sa.Column("dia", sa.String(10), primary_key=True), sa.Column("usos", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_uso_diario")
