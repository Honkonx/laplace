"""Memoria del modelo en la base: estado por equipo de cada liga, al día (`ml_estado_vivo`; ver ml/laplace/estado_vivo.py)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fb3e5a7c9d1f"
down_revision: Union[str, None] = "fa2c4e6a8b0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_estado_vivo",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("modelo_id", sa.Integer(), nullable=False),
        sa.Column("liga", sa.String(length=40), nullable=False),
        sa.Column("estado_json", sa.Text(), nullable=False),
        sa.Column("hasta_dia", sa.Integer(), nullable=False),
        sa.Column("partidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actualizado_en", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("modelo_id", "liga", name="uq_ml_estado_vivo_modelo_liga"),
    )
    op.create_index("ix_ml_estado_vivo_modelo_id", "ml_estado_vivo", ["modelo_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_estado_vivo_modelo_id", table_name="ml_estado_vivo")
    op.drop_table("ml_estado_vivo")
