"""Auditoría del modelo: memoria de errores (`ml_errores`) y cadena de sellos de los pronósticos (`ml_predicciones.hash_previo/hash_fila`); ver ml/laplace/auditoria.py."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1f3b5d2"
down_revision: Union[str, None] = "fb3e5a7c9d1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_errores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("modelo_id", sa.Integer(), nullable=False),
        sa.Column("partido_id", sa.String(length=64), nullable=False),
        sa.Column("liga", sa.String(length=120), nullable=False),
        sa.Column("fecha", sa.String(length=10), nullable=False),
        sa.Column("p_local", sa.Float(), nullable=False),
        sa.Column("p_empate", sa.Float(), nullable=False),
        sa.Column("p_visitante", sa.Float(), nullable=False),
        sa.Column("resultado", sa.String(length=1), nullable=False),
        sa.Column("rps", sa.Float(), nullable=False),
        sa.Column("log_loss", sa.Float(), nullable=False),
        sa.Column("tramo", sa.String(length=8), nullable=False),
        sa.Column("acierto", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("modelo_id", "partido_id", name="uq_ml_errores_modelo_partido"),
    )
    op.create_index("ix_ml_errores_modelo_id", "ml_errores", ["modelo_id"])
    op.add_column("ml_predicciones", sa.Column("hash_previo", sa.String(length=64), nullable=True))
    op.add_column("ml_predicciones", sa.Column("hash_fila", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_predicciones", "hash_fila")
    op.drop_column("ml_predicciones", "hash_previo")
    op.drop_index("ix_ml_errores_modelo_id", table_name="ml_errores")
    op.drop_table("ml_errores")
