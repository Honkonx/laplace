"""Aviso diario de partidos de los favoritos: columna de aceptación (MB-34)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fc9d0e1f2a3b"
down_revision: Union[str, None] = "fb8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bot_preferencias", sa.Column("avisos", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("bot_preferencias", "avisos")
