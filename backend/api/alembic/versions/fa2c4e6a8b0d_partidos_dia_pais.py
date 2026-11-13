"""País de la competición en `partidos_dia`: dos ligas con el mismo nombre en países distintos dejan de mezclarse (ver services/ligas_ident.py)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fa2c4e6a8b0d"
down_revision: Union[str, None] = "fc9d0e1f2a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("partidos_dia", sa.Column("liga_pais", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("partidos_dia", "liga_pais")
