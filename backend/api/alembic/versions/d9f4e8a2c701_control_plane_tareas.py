"""Añadir cancelación cooperativa al control plane de tareas."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9f4e8a2c701"
down_revision: Union[str, None] = "c8e2d4f901ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("agent_tasks", "cancel_requested")
