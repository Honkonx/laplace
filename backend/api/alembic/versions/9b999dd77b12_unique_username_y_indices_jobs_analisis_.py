"""unique username y indices jobs analisis_comparativo

Revision ID: 9b999dd77b12
Revises: 2597240e8e06
Create Date: 2026-09-09 14:25:37.673980

Ajustado a mano respecto del autogenerate (ver .claude/rules/database-safety.md): SQLite no
soporta `ALTER TABLE ... ADD CONSTRAINT UNIQUE` directo (lo que generó `op.create_unique_constraint`
crudo habría fallado al aplicar) — requiere el patrón batch (`batch_alter_table`, que Alembic
resuelve como crear tabla nueva + copiar datos + dropear vieja + renombrar). La constraint se
nombra explícitamente (`uq_usuarios_username`) para que el downgrade pueda referenciarla — el
autogenerate la había dejado sin nombre (`None`), lo que rompe `drop_constraint` en SQLite.
Los `CREATE INDEX` sí son soportados nativos por SQLite, se dejan como los generó autogenerate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9b999dd77b12'
down_revision: Union[str, None] = '2597240e8e06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_analisis_comparativo_fecha', 'analisis_comparativo', ['fecha'], unique=False)
    op.create_index('ix_analisis_comparativo_partido_id', 'analisis_comparativo', ['partido_id'], unique=False)
    op.create_index('ix_jobs_device_id_app_status', 'jobs', ['device_id_app', 'status'], unique=False)
    op.create_index('ix_jobs_match_id', 'jobs', ['match_id'], unique=False)

    # SQLite: agregar UNIQUE a una columna existente requiere batch mode (recrea la tabla
    # completa preservando datos) — ver docstring del módulo.
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_usuarios_username', ['username'])


def downgrade() -> None:
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_constraint('uq_usuarios_username', type_='unique')

    op.drop_index('ix_jobs_match_id', table_name='jobs')
    op.drop_index('ix_jobs_device_id_app_status', table_name='jobs')
    op.drop_index('ix_analisis_comparativo_partido_id', table_name='analisis_comparativo')
    op.drop_index('ix_analisis_comparativo_fecha', table_name='analisis_comparativo')
