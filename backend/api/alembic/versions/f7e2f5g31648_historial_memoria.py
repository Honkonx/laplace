"""Añade historial append-only de memoria."""
from alembic import op
import sqlalchemy as sa

revision = "f7e2f5g31648"
down_revision = "f6d1e4f20537"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column("creado_en", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_agent_memory_history_memory_id", "agent_memory_history", ["memory_id"])
    op.create_index("ix_agent_memory_history_owner_id", "agent_memory_history", ["owner_id"])


def downgrade() -> None:
    op.drop_table("agent_memory_history")
