"""alembic/env.py — importa el engine y los modelos reales de la app (patrón de PAGINA1),
en vez de leer `sqlalchemy.url` de alembic.ini como única fuente — así Alembic usa
SIEMPRE el mismo DATABASE_URL que la app real (Settings), no una copia que se puede
desincronizar."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importar los modelos explícitamente para que Base.metadata los conozca —
# sin esto, `alembic revision --autogenerate` no detecta tablas nuevas.
from backend.api.db.session import Base
from backend.api.core.config import settings
import backend.api.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
