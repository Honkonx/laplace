"""Estado operativo de proveedores deportivos."""
from alembic import op
import sqlalchemy as sa

revision = "fc3d4e5f6a7b"
down_revision = "fb2c3d4e5f6a"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("estado_fuentes_deportivas", sa.Column("fuente", sa.String(length=64), primary_key=True), sa.Column("configurada", sa.Integer(), nullable=False), sa.Column("saludable", sa.Integer(), nullable=False), sa.Column("status_http", sa.Integer()), sa.Column("latencia_ms", sa.Float()), sa.Column("cuota_restante", sa.String(length=64)), sa.Column("detalle", sa.Text()), sa.Column("verificado_en", sa.String(), nullable=False))
    op.create_index("ix_estado_fuentes_verificado", "estado_fuentes_deportivas", ["verificado_en"])

def downgrade() -> None:
    op.drop_index("ix_estado_fuentes_verificado", table_name="estado_fuentes_deportivas")
    op.drop_table("estado_fuentes_deportivas")
