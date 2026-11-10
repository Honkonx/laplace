"""Añade sensibilidad y expiración a la memoria del agente."""
from alembic import op
import sqlalchemy as sa

revision = "f5c0e3f10426"
down_revision = "f4b9d2e3f015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_memories", sa.Column("sensibilidad", sa.String(length=32), nullable=False, server_default="normal"))
    op.add_column("agent_memories", sa.Column("expira_en", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_memories", "expira_en")
    op.drop_column("agent_memories", "sensibilidad")
