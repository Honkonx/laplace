"""laboratorio de evaluación comparativa de pronósticos

Revision ID: fd4e5f6a7b8c
Revises: fc3d4e5f6a7b
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "fd4e5f6a7b8c"
down_revision = "fc3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experimentos_pronostico",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("codigo", sa.String(length=96), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column("estado", sa.String(length=32), nullable=False, server_default="sombra"),
        sa.Column("version", sa.String(length=96), nullable=False),
        sa.Column("permite_consenso", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("descripcion", sa.Text()),
        sa.Column("creado_en", sa.Text(), nullable=False),
        sa.Column("actualizado_en", sa.Text(), nullable=False),
        sa.UniqueConstraint("codigo", name="uq_experimento_pronostico_codigo"),
    )
    op.create_index("ix_experimento_pronostico_codigo", "experimentos_pronostico", ["codigo"])
    op.bulk_insert(
        sa.table(
            "experimentos_pronostico",
            sa.column("codigo", sa.String), sa.column("nombre", sa.Text), sa.column("tipo", sa.String),
            sa.column("estado", sa.String), sa.column("version", sa.String), sa.column("permite_consenso", sa.Integer),
            sa.column("descripcion", sa.Text), sa.column("creado_en", sa.Text), sa.column("actualizado_en", sa.Text),
        ),
        [
            {"codigo": "python_baseline", "nombre": "Motor estadístico Python", "tipo": "propio", "estado": "sombra", "version": "poisson-dixon-coles-v1", "permite_consenso": 0, "descripcion": "Comparador interno; no participa en el consenso público.", "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z"},
            {"codigo": "python_plus_ia", "nombre": "Motor estadístico con contraste IA", "tipo": "ia", "estado": "sombra", "version": "consenso-ia-v1", "permite_consenso": 0, "descripcion": "Comparador interno; no participa en el consenso público.", "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z"},
            {"codigo": "ia_simple", "nombre": "Hipótesis conversacional solo IA", "tipo": "ia", "estado": "sombra", "version": "ai-scout-v1", "permite_consenso": 0, "descripcion": "Comparador interno; no participa en el consenso público.", "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z"},
            {"codigo": "api_football_prediction", "nombre": "Referencia API Football", "tipo": "api", "estado": "sombra", "version": "api-football-v1", "permite_consenso": 0, "descripcion": "Comparador interno; no participa en el consenso público.", "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z"},
            {"codigo": "bsd_catboost", "nombre": "Referencia BSD CatBoost", "tipo": "api", "estado": "sombra", "version": "bsd-catboost-v1", "permite_consenso": 0, "descripcion": "Comparador interno; no participa en el consenso público.", "creado_en": "2026-09-27T00:00:00Z", "actualizado_en": "2026-09-27T00:00:00Z"},
        ],
    )
    op.create_table(
        "pronosticos_experimentales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("experimento_codigo", sa.String(length=96), nullable=False),
        sa.Column("partido_id", sa.String(), nullable=False),
        sa.Column("fecha_partido", sa.String(), nullable=False),
        sa.Column("hora_kickoff", sa.Text()), sa.Column("liga", sa.Text()),
        sa.Column("local", sa.Text(), nullable=False), sa.Column("visitante", sa.Text(), nullable=False),
        sa.Column("fuente", sa.String(length=96), nullable=False), sa.Column("variante", sa.String(length=96), nullable=False),
        sa.Column("modelo_version", sa.String(length=255)), sa.Column("prompt_version", sa.String(length=96)),
        sa.Column("corte_datos_en", sa.Text(), nullable=False), sa.Column("input_hash", sa.String(length=128)),
        sa.Column("datos_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("respuesta_cruda", sa.Text()),
        sa.Column("pick", sa.Text()), sa.Column("prob_local", sa.Float()), sa.Column("prob_empate", sa.Float()), sa.Column("prob_visitante", sa.Float()),
        sa.Column("marcador_probable", sa.Text()), sa.Column("goles_local_esperados", sa.Float()), sa.Column("goles_visitante_esperados", sa.Float()),
        sa.Column("rango_goles_total", sa.Text()), sa.Column("prob_empate_90", sa.Float()),
        sa.Column("resultado_real", sa.Text()), sa.Column("goles_local_real", sa.Integer()), sa.Column("goles_visitante_real", sa.Integer()),
        sa.Column("pick_correcto", sa.Integer()), sa.Column("brier_score", sa.Float()), sa.Column("log_loss", sa.Float()), sa.Column("rps", sa.Float()),
        sa.Column("creado_en", sa.Text(), nullable=False),
        sa.UniqueConstraint("partido_id", "variante", "corte_datos_en", name="uq_pronostico_experimental_corte"),
    )
    for name, cols in (
        ("ix_pron_exp_experimento", ["experimento_codigo"]), ("ix_pron_exp_partido", ["partido_id"]),
        ("ix_pron_exp_fecha", ["fecha_partido"]), ("ix_pron_exp_liga", ["liga"]),
        ("ix_pron_exp_fuente", ["fuente"]), ("ix_pron_exp_variante", ["variante"]),
        ("ix_pron_exp_corte", ["corte_datos_en"]),
    ):
        op.create_index(name, "pronosticos_experimentales", cols)


def downgrade() -> None:
    for name in ("ix_pron_exp_corte", "ix_pron_exp_variante", "ix_pron_exp_fuente", "ix_pron_exp_liga", "ix_pron_exp_fecha", "ix_pron_exp_partido", "ix_pron_exp_experimento"):
        op.drop_index(name, table_name="pronosticos_experimentales")
    op.drop_table("pronosticos_experimentales")
    op.drop_index("ix_experimento_pronostico_codigo", table_name="experimentos_pronostico")
    op.drop_table("experimentos_pronostico")
