"""separar rol de plan en usuarios

Revision ID: a55c5f3b84d2
Revises: 56d90d86def1
Create Date: 2026-09-10 13:17:05.046789

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a55c5f3b84d2'
down_revision: Union[str, None] = '56d90d86def1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default requerido: SQLite exige un default para agregar una columna NOT NULL a
    # una tabla con filas existentes. Se retira el server_default después del backfill (mismo
    # patrón que otras migraciones de este proyecto) para que el default real viva solo en el
    # modelo Python (`models/usuarios.py`), no duplicado en el esquema de BD.
    op.add_column('usuarios', sa.Column('rol', sa.String(), nullable=False, server_default='usuario'))

    # Backfill: cualquier fila que hoy use el pseudo-valor plan='admin' (mezcla histórica de
    # permiso+tier, ver models/usuarios.py) pasa su permiso real a `rol` y su `plan` vuelve a
    # ser un tier de suscripción real ('max', el más alto existente) — a partir de acá `plan`
    # es 100% tier, `rol` es 100% permiso. Verificado 2026-09-10 contra la BD real: 0 filas
    # tenían plan='admin' hoy (el mecanismo de admin de Telegram usa `settings.admin_ids`,
    # nunca tocó esta columna) — este UPDATE es defensivo para cualquier otro entorno/BD.
    op.execute("UPDATE usuarios SET rol = 'admin', plan = 'max' WHERE plan = 'admin'")

    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.alter_column('rol', server_default=None)


def downgrade() -> None:
    op.drop_column('usuarios', 'rol')
