"""Tablas del modelo propio de Laplace (ml_*)

Revision ID: a1b2c3d4e5f7
Revises: fe5a6b7c8d9e
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
down_revision = "fe5a6b7c8d9e"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Integer, primary_key=True, autoincrement=True)


def upgrade() -> None:
    op.create_table("ml_conjuntos_datos", _id(),
        sa.Column("nombre", sa.String(120), nullable=False), sa.Column("version", sa.String(40), nullable=False),
        sa.Column("hash_datos", sa.String(64)), sa.Column("procedencia", sa.String(12), nullable=False),
        sa.Column("desde", sa.String(10)), sa.Column("hasta", sa.String(10)),
        sa.Column("filas", sa.Integer, nullable=False), sa.Column("ruta", sa.Text), sa.Column("creado_en", sa.String(32), nullable=False))
    op.create_index("ix_ml_conjuntos_datos_nombre", "ml_conjuntos_datos", ["nombre"])
    op.create_table("ml_simulaciones", _id(),
        sa.Column("conjunto_id", sa.Integer), sa.Column("grupo", sa.String(120)), sa.Column("semilla", sa.Integer, nullable=False),
        sa.Column("parametros_json", sa.Text, nullable=False), sa.Column("tipo", sa.String(12), nullable=False),
        sa.Column("version_generador", sa.String(40), nullable=False), sa.Column("generada_en", sa.String(32), nullable=False))
    op.create_index("ix_ml_simulaciones_conjunto_id", "ml_simulaciones", ["conjunto_id"])
    op.create_index("ix_ml_simulaciones_grupo", "ml_simulaciones", ["grupo"])
    op.create_table("ml_muestras", _id(),
        sa.Column("conjunto_id", sa.Integer, nullable=False), sa.Column("simulacion_id", sa.Integer), sa.Column("partido_id", sa.String(64)),
        sa.Column("procedencia", sa.String(12), nullable=False), sa.Column("peso", sa.Float, nullable=False),
        sa.Column("fecha_evento", sa.String(10)), sa.Column("caracteristicas_json", sa.Text, nullable=False), sa.Column("etiqueta_json", sa.Text),
        sa.Column("hash_muestra", sa.String(64), nullable=False), sa.Column("creada_en", sa.String(32), nullable=False))
    op.create_index("ix_ml_muestras_conjunto_fecha", "ml_muestras", ["conjunto_id", "fecha_evento"])
    op.create_index("ix_ml_muestras_simulacion_id", "ml_muestras", ["simulacion_id"])
    op.create_table("ml_entrenamientos", _id(),
        sa.Column("conjunto_id", sa.Integer, nullable=False), sa.Column("familia", sa.String(40), nullable=False), sa.Column("semilla", sa.Integer, nullable=False),
        sa.Column("parametros_json", sa.Text, nullable=False), sa.Column("commit_codigo", sa.String(40)), sa.Column("estado", sa.String(12), nullable=False),
        sa.Column("error", sa.Text), sa.Column("inicio", sa.String(32)), sa.Column("fin", sa.String(32)))
    op.create_index("ix_ml_entrenamientos_conjunto_id", "ml_entrenamientos", ["conjunto_id"])
    op.create_index("ix_ml_entrenamientos_estado", "ml_entrenamientos", ["estado"])
    op.create_table("ml_modelos", _id(),
        sa.Column("nombre", sa.String(80), nullable=False), sa.Column("version", sa.String(60), nullable=False), sa.Column("familia", sa.String(40), nullable=False),
        sa.Column("tarea", sa.String(40), nullable=False), sa.Column("artefacto_ruta", sa.Text), sa.Column("artefacto_sha256", sa.String(64)),
        sa.Column("estado", sa.String(12), nullable=False), sa.Column("metricas_json", sa.Text), sa.Column("entrenamiento_id", sa.Integer),
        sa.Column("promovido_por", sa.String(80)), sa.Column("creado_en", sa.String(32), nullable=False))
    op.create_index("ux_ml_modelos_nombre_version", "ml_modelos", ["nombre", "version"], unique=True)
    op.create_index("ix_ml_modelos_estado", "ml_modelos", ["estado"])
    op.create_table("ml_predicciones", _id(),
        sa.Column("modelo_id", sa.Integer, nullable=False), sa.Column("partido_id", sa.String(64)), sa.Column("entrada_json", sa.Text, nullable=False),
        sa.Column("probabilidades_json", sa.Text, nullable=False), sa.Column("goles_json", sa.Text), sa.Column("confianza", sa.Float), sa.Column("latencia_ms", sa.Float),
        sa.Column("canal", sa.String(12), nullable=False), sa.Column("creada_en", sa.String(32), nullable=False))
    op.create_index("ix_ml_predicciones_modelo_fecha", "ml_predicciones", ["modelo_id", "creada_en"])
    op.create_index("ix_ml_predicciones_partido_id", "ml_predicciones", ["partido_id"])
    op.create_table("ml_evaluaciones", _id(),
        sa.Column("modelo_id", sa.Integer, nullable=False), sa.Column("ventana_desde", sa.String(10)), sa.Column("ventana_hasta", sa.String(10)),
        sa.Column("n", sa.Integer, nullable=False), sa.Column("log_loss", sa.Float), sa.Column("brier", sa.Float), sa.Column("rps", sa.Float),
        sa.Column("ece", sa.Float), sa.Column("cobertura", sa.Float), sa.Column("referencias_json", sa.Text),
        sa.Column("origen", sa.String(12), nullable=False), sa.Column("creada_en", sa.String(32), nullable=False))
    op.create_index("ix_ml_evaluaciones_modelo_id", "ml_evaluaciones", ["modelo_id"])


def downgrade() -> None:
    for tabla in ("ml_evaluaciones", "ml_predicciones", "ml_modelos", "ml_entrenamientos", "ml_muestras", "ml_simulaciones", "ml_conjuntos_datos"):
        op.drop_table(tabla)
