"""Añade reintentos, timeout e idempotencia al orquestador."""
from alembic import op
import sqlalchemy as sa

revision = "f6d1e4f20537"
down_revision = "f5c0e3f10426"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_tasks", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("agent_tasks", sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"))
    op.add_column("agent_tasks", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.create_index("ix_agent_tasks_idempotency_key", "agent_tasks", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_idempotency_key", table_name="agent_tasks")
    op.drop_column("agent_tasks", "idempotency_key")
    op.drop_column("agent_tasks", "timeout_seconds")
    op.drop_column("agent_tasks", "max_attempts")
    op.drop_column("agent_tasks", "attempt_count")
