"""Registra el consentimiento versionado de usuarios web y app."""
from alembic import op
import sqlalchemy as sa

revision = "f9a0b1c2d3e4"
down_revision = "f8f3g6h42759"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("terms_version", sa.String(length=32), nullable=True))
    op.add_column("usuarios", sa.Column("terms_accepted_at", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("usuarios", "terms_accepted_at")
    op.drop_column("usuarios", "terms_version")
