"""Referencias humanas de laboratorio

Revision ID: fe5a6b7c8d9e
Revises: fd4e5f6a7b8c
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "fe5a6b7c8d9e"
down_revision = "fd4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "experimentos_pronostico",
            sa.column("codigo", sa.String), sa.column("nombre", sa.Text), sa.column("tipo", sa.String),
            sa.column("estado", sa.String), sa.column("version", sa.String), sa.column("permite_consenso", sa.Integer),
            sa.column("descripcion", sa.Text), sa.column("creado_en", sa.Text), sa.column("actualizado_en", sa.Text),
        ),
        [{
            "codigo": "human_reference", "nombre": "Referencia humana supervisada", "tipo": "web_referencia",
            "estado": "sombra", "version": "human-v1", "permite_consenso": 0,
            "descripcion": "Referencia atribuida por administrador; no participa en el consenso público.",
            "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z",
        }],
    )


def downgrade() -> None:
    op.execute("DELETE FROM experimentos_pronostico WHERE codigo = 'human_reference'")
