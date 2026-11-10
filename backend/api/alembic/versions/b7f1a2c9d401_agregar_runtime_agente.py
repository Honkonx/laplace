"""Agregar sesiones, memoria, conocimiento y runs del agente general."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7f1a2c9d401"
down_revision: Union[str, None] = "e0b8b0bd13dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tabla(nombre: str, columnas: list[sa.Column]) -> None:
    op.create_table(nombre, *columnas)


def upgrade() -> None:
    _tabla("agent_sessions", [
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False), sa.Column("title", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("creado_en", sa.String(32), nullable=False),
        sa.Column("actualizado_en", sa.String(32), nullable=False),
    ])
    _tabla("agent_messages", [
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False), sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False), sa.Column("modo", sa.String(32), nullable=False),
        sa.Column("herramienta", sa.String(100)), sa.Column("creado_en", sa.String(32), nullable=False),
    ])
    _tabla("agent_memories", [
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(255)), sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("topic_key", sa.String(255), nullable=False), sa.Column("content", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False), sa.Column("source", sa.String(255), nullable=False),
        sa.Column("metadata_json", sa.Text, nullable=False), sa.Column("activo", sa.Integer, nullable=False),
        sa.Column("creado_en", sa.String(32), nullable=False), sa.Column("actualizado_en", sa.String(32), nullable=False),
    ])
    _tabla("agent_knowledge", [
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("topic_key", sa.String(255), nullable=False), sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(255), nullable=False), sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("creado_en", sa.String(32), nullable=False), sa.Column("actualizado_en", sa.String(32), nullable=False),
    ])
    _tabla("agent_runs", [
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("session_id", sa.String(64)),
        sa.Column("user_id", sa.String(255), nullable=False), sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("input_json", sa.Text, nullable=False),
        sa.Column("output_json", sa.Text, nullable=False), sa.Column("creado_en", sa.String(32), nullable=False),
        sa.Column("terminado_en", sa.String(32)),
    ])
    for table, columns in {"agent_sessions": ["user_id"], "agent_messages": ["session_id", "user_id"], "agent_memories": ["scope", "owner_id", "topic_key"], "agent_knowledge": ["namespace", "topic_key"], "agent_runs": ["session_id", "user_id"]}.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in ("agent_runs", "agent_knowledge", "agent_memories", "agent_messages", "agent_sessions"):
        op.drop_table(table)
