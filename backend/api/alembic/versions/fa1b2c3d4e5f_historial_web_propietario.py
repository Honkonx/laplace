"""Historial web aislado por dueño autenticado."""
from alembic import op
import sqlalchemy as sa

revision = "fa1b2c3d4e5f"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("historial_predicciones_web", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.String(), nullable=False), sa.Column("partido_id", sa.String(), nullable=False), sa.Column("fecha", sa.String(), nullable=False), sa.Column("liga", sa.Text()), sa.Column("local", sa.Text()), sa.Column("visitante", sa.Text()), sa.Column("pick", sa.Text()), sa.Column("confianza", sa.Text()), sa.Column("resultado_json", sa.Text(), nullable=False), sa.Column("creado_en", sa.Text(), nullable=False))
    op.create_index("ix_historial_web_user", "historial_predicciones_web", ["user_id"])
    op.create_index("ix_historial_web_match", "historial_predicciones_web", ["partido_id"])

def downgrade() -> None:
    op.drop_index("ix_historial_web_match", table_name="historial_predicciones_web")
    op.drop_index("ix_historial_web_user", table_name="historial_predicciones_web")
    op.drop_table("historial_predicciones_web")
