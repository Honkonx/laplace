"""Eventos, aprobaciones y versiones de políticas del agente."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4b9d2e3f015"
down_revision: Union[str, None] = "f3a8c1d2e904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("creado_en", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_events_user_id", "agent_events", ["user_id"])
    op.create_index("ix_agent_events_task_id", "agent_events", ["task_id"])
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("invocation_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_en", sa.String(length=32), nullable=False),
        sa.Column("decided_en", sa.String(length=32), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_approvals_invocation_id", "agent_approvals", ["invocation_id"])
    op.create_index("ix_agent_approvals_user_id", "agent_approvals", ["user_id"])
    op.create_index("ix_agent_approvals_status", "agent_approvals", ["status"])
    op.create_table(
        "agent_policy_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("topic_key", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("content_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_en", sa.String(length=32), nullable=False),
        sa.Column("activated_en", sa.String(length=32), nullable=True),
        sa.Column("deactivated_en", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_policy_versions_scope", "agent_policy_versions", ["scope"])
    op.create_index("ix_agent_policy_versions_topic_key", "agent_policy_versions", ["topic_key"])
    op.create_index("ix_agent_policy_versions_status", "agent_policy_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_policy_versions_status", table_name="agent_policy_versions")
    op.drop_index("ix_agent_policy_versions_topic_key", table_name="agent_policy_versions")
    op.drop_index("ix_agent_policy_versions_scope", table_name="agent_policy_versions")
    op.drop_table("agent_policy_versions")
    op.drop_index("ix_agent_approvals_status", table_name="agent_approvals")
    op.drop_index("ix_agent_approvals_user_id", table_name="agent_approvals")
    op.drop_index("ix_agent_approvals_invocation_id", table_name="agent_approvals")
    op.drop_table("agent_approvals")
    op.drop_index("ix_agent_events_event_type", table_name="agent_events")
    op.drop_index("ix_agent_events_run_id", table_name="agent_events")
    op.drop_index("ix_agent_events_task_id", table_name="agent_events")
    op.drop_index("ix_agent_events_user_id", table_name="agent_events")
    op.drop_table("agent_events")
