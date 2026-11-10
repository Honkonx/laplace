"""Añadir índice FTS5 para búsqueda del agente cuando la base es SQLite."""
from typing import Sequence, Union

from alembic import op

revision: str = "e2b7c9d0f103"
down_revision: Union[str, None] = "e1a6b7c8d902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS agent_search_fts USING fts5(" 
        "kind, ref_id UNINDEXED, owner_id UNINDEXED, scope UNINDEXED, content, topic_key)"
    )
    bind.exec_driver_sql(
        "INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key) "
        "SELECT 'message', CAST(id AS TEXT), user_id, '', content, '' FROM agent_messages"
    )
    bind.exec_driver_sql(
        "INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key) "
        "SELECT 'memory', CAST(id AS TEXT), COALESCE(owner_id, ''), scope, content, topic_key "
        "FROM agent_memories WHERE activo = 1"
    )
    bind.exec_driver_sql(
        "INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key) "
        "SELECT 'knowledge', CAST(id AS TEXT), '', 'global', content, topic_key FROM agent_knowledge"
    )
    bind.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS agent_messages_fts_ai AFTER INSERT ON agent_messages BEGIN
          INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key)
          VALUES ('message', CAST(new.id AS TEXT), new.user_id, '', new.content, '');
        END
    """)
    bind.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS agent_memories_fts_ai AFTER INSERT ON agent_memories WHEN new.activo = 1 BEGIN
          INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key)
          VALUES ('memory', CAST(new.id AS TEXT), COALESCE(new.owner_id, ''), new.scope, new.content, new.topic_key);
        END
    """)
    bind.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS agent_knowledge_fts_ai AFTER INSERT ON agent_knowledge BEGIN
          INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key)
          VALUES ('knowledge', CAST(new.id AS TEXT), '', 'global', new.content, new.topic_key);
        END
    """)
    bind.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS agent_memories_fts_au AFTER UPDATE OF content, topic_key, activo ON agent_memories BEGIN
          DELETE FROM agent_search_fts WHERE kind = 'memory' AND ref_id = CAST(old.id AS TEXT);
          INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key)
          SELECT 'memory', CAST(new.id AS TEXT), COALESCE(new.owner_id, ''), new.scope, new.content, new.topic_key WHERE new.activo = 1;
        END
    """)
    bind.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS agent_knowledge_fts_au AFTER UPDATE OF content, topic_key ON agent_knowledge BEGIN
          DELETE FROM agent_search_fts WHERE kind = 'knowledge' AND ref_id = CAST(old.id AS TEXT);
          INSERT INTO agent_search_fts(kind, ref_id, owner_id, scope, content, topic_key)
          VALUES ('knowledge', CAST(new.id AS TEXT), '', 'global', new.content, new.topic_key);
        END
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    for trigger in ("agent_messages_fts_ai", "agent_memories_fts_ai", "agent_knowledge_fts_ai", "agent_memories_fts_au", "agent_knowledge_fts_au"):
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
    bind.exec_driver_sql("DROP TABLE IF EXISTS agent_search_fts")
