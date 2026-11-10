"""Agregar tareas persistentes del orquestador del agente."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8e2d4f901ab"
down_revision: Union[str, None] = "b7f1a2c9d401"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("parent_id", sa.String(64)),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_json", sa.Text, nullable=False),
        sa.Column("output_json", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("creado_en", sa.String(32), nullable=False),
        sa.Column("iniciado_en", sa.String(32)),
        sa.Column("terminado_en", sa.String(32)),
    )
    op.create_index("ix_agent_tasks_parent_id", "agent_tasks", ["parent_id"])
    op.create_index("ix_agent_tasks_user_id", "agent_tasks", ["user_id"])


def downgrade() -> None:
    op.drop_table("agent_tasks")
