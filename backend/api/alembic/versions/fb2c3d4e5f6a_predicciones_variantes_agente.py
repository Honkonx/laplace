"""Variantes de predicción privadas del agente."""
from alembic import op
import sqlalchemy as sa

revision = "fb2c3d4e5f6a"
down_revision = "fa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "predicciones_variantes_agente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(length=64)),
        sa.Column("partido_id", sa.String()),
        sa.Column("fecha", sa.String(), nullable=False),
        sa.Column("liga", sa.Text()),
        sa.Column("local", sa.Text(), nullable=False),
        sa.Column("visitante", sa.Text(), nullable=False),
        sa.Column("via", sa.String(length=32), nullable=False),
        sa.Column("pick", sa.Text()), sa.Column("marcador_probable", sa.Text()), sa.Column("confianza", sa.Text()),
        sa.Column("proveedor", sa.String(length=64)), sa.Column("modelo", sa.String(length=255)),
        sa.Column("prompt_version", sa.String(length=64)), sa.Column("respuesta_cruda", sa.Text(), nullable=False),
        sa.Column("resultado_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("resultado_real", sa.Text()), sa.Column("pick_correcto", sa.Integer()), sa.Column("creado_en", sa.Text(), nullable=False),
    )
    for name, cols in (("ix_pred_var_user", ["user_id"]), ("ix_pred_var_session", ["session_id"]), ("ix_pred_var_match", ["partido_id"])):
        op.create_index(name, "predicciones_variantes_agente", cols)


def downgrade() -> None:
    for name in ("ix_pred_var_match", "ix_pred_var_session", "ix_pred_var_user"):
        op.drop_index(name, table_name="predicciones_variantes_agente")
    op.drop_table("predicciones_variantes_agente")
