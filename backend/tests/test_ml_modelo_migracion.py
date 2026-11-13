"""Las 7 tablas `ml_*`: el modelo SQLAlchemy y la migración Alembic deben coincidir, y se pueden subir y bajar sin tocar lo demás."""
from __future__ import annotations

import logging
import sqlite3

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from backend.api.db.session import Base
import backend.api.models  # noqa: F401 — registra los modelos

TABLAS = {"ml_conjuntos_datos", "ml_simulaciones", "ml_muestras", "ml_entrenamientos", "ml_modelos", "ml_predicciones", "ml_evaluaciones"}


def test_el_modelo_declara_las_siete_tablas():
    assert TABLAS <= set(Base.metadata.tables)


def test_toda_tabla_ml_guarda_fechas_como_texto_y_sin_default_de_sqlite():
    for nombre in TABLAS:
        tabla = Base.metadata.tables[nombre]
        for col in tabla.columns:
            assert col.server_default is None, f"{nombre}.{col.name} usa DEFAULT del servidor"
            if col.name.endswith("_en") or col.name in {"inicio", "fin"}:
                assert isinstance(col.type, sa.String), f"{nombre}.{col.name} debe ser texto ISO"


def test_las_muestras_llevan_procedencia_obligatoria():
    assert Base.metadata.tables["ml_muestras"].c.procedencia.nullable is False


def test_la_migracion_sube_y_baja_en_una_base_temporal(tmp_path, monkeypatch):
    # el env.py de Alembic llama a `logging.config.fileConfig`, que deshabilita los loggers ya creados (rompería `caplog` en otras pruebas)
    estado = {n: lg.disabled for n, lg in logging.root.manager.loggerDict.items() if isinstance(lg, logging.Logger)}
    try:
        _subir_y_bajar(tmp_path, monkeypatch)
    finally:
        for nombre, desactivado in estado.items():
            logging.getLogger(nombre).disabled = desactivado


def _subir_y_bajar(tmp_path, monkeypatch):
    ruta = tmp_path / "migracion.db"
    monkeypatch.setattr("backend.api.core.config.settings.DATABASE_URL", f"sqlite:///{ruta.as_posix()}")
    cfg = Config("backend/api/alembic.ini")
    command.upgrade(cfg, "head")
    con = sqlite3.connect(ruta)
    assert TABLAS <= {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    command.downgrade(cfg, "fe5a6b7c8d9e")  # padre de la migración del modelo propio: baja también lo posterior (p. ej. la memoria del bot)
    con = sqlite3.connect(ruta)
    assert not (TABLAS & {r[0] for r in con.execute("select name from sqlite_master where type='table'")})
    con.close()
