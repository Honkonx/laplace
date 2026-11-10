"""Auditar invocaciones de herramientas del agente."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3a8c1d2e904"
down_revision: Union[str, None] = "e2b7c9d0f103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_invocations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("creado_en", sa.String(length=32), nullable=False),
        sa.Column("terminado_en", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tool_invocations_user_id", "agent_tool_invocations", ["user_id"])
    op.create_index("ix_agent_tool_invocations_tool_name", "agent_tool_invocations", ["tool_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_invocations_tool_name", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_user_id", table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")
