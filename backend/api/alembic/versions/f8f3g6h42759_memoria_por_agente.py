"""Añade partición lógica de memoria por agente."""
from alembic import op
import sqlalchemy as sa

revision = "f8f3g6h42759"
down_revision = "f7e2f5g31648"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_memories", sa.Column("agent_id", sa.String(length=100), nullable=False, server_default="laplace"))
    op.create_index("ix_agent_memories_agent_id", "agent_memories", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_memories_agent_id", table_name="agent_memories")
    op.drop_column("agent_memories", "agent_id")
