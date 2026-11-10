"""Añadir feedback y propuestas de aprendizaje revisables."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1a6b7c8d902"
down_revision: Union[str, None] = "d9f4e8a2c701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64)),
        sa.Column("comment", sa.Text),
        sa.Column("creado_en", sa.String(32), nullable=False),
    )
    op.create_index("ix_agent_feedback_user_id", "agent_feedback", ["user_id"])
    op.create_index("ix_agent_feedback_run_id", "agent_feedback", ["run_id"])
    op.create_table(
        "agent_learning_proposals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("topic_key", sa.String(255), nullable=False),
        sa.Column("proposal_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("review_note", sa.Text),
        sa.Column("creado_en", sa.String(32), nullable=False),
        sa.Column("revisado_en", sa.String(32)),
    )


def downgrade() -> None:
    op.drop_table("agent_learning_proposals")
    op.drop_index("ix_agent_feedback_run_id", table_name="agent_feedback")
    op.drop_index("ix_agent_feedback_user_id", table_name="agent_feedback")
    op.drop_table("agent_feedback")
