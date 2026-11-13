"""core/esquema.py — ¿la base está en la versión de esquema que el código espera?

Incidente real del 2026-11-11: el código nuevo consultaba `bot_consentimientos` pero la base real seguía en la migración anterior (`a1b2c3d4e5f7`), porque el arranque no aplicaba migraciones
(solo el instalador y `start-laplace.*` lo hacían); el botón de Telegram falló con «no such table» y el análisis nunca llegó. Dos defensas: (1) `asegurar_esquema` aplica las migraciones
pendientes al arrancar en SQLite local (aditivas, reversibles) y solo AVISA en otros motores; (2) `estado_esquema` lo muestra en `/health`.
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from backend.api.core.config import settings

log = logging.getLogger("laplace.esquema")
RAIZ = Path(__file__).resolve().parents[3]
ALEMBIC_INI = RAIZ / "backend" / "api" / "alembic.ini"


@contextlib.contextmanager
def _conservar_logging():
    """El `env.py` de Alembic llama a `logging.config.fileConfig`, que reemplaza los manejadores del logger raíz y APAGA los loggers ya creados: tras migrar al arrancar, la aplicación
    se quedaba sin registros. Se guarda y se restaura el estado completo del logging alrededor de la migración."""
    raiz = logging.getLogger()
    nivel, manejadores = raiz.level, list(raiz.handlers)
    estado = {n: (lg.disabled, lg.level, lg.propagate, list(lg.handlers)) for n, lg in logging.root.manager.loggerDict.items() if isinstance(lg, logging.Logger)}
    try:
        yield
    finally:
        raiz.setLevel(nivel)
        raiz.handlers[:] = manejadores
        for n, (desactivado, nv, propaga, hs) in estado.items():
            lg = logging.getLogger(n)
            lg.disabled, lg.propagate = desactivado, propaga
            lg.setLevel(nv)
            lg.handlers[:] = hs


def _config():
    from alembic.config import Config

    return Config(str(ALEMBIC_INI))


def estado_esquema(url: str | None = None) -> dict:
    """{actual, cabeza, al_dia}; `error` si no se pudo leer. No modifica nada."""
    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        cabeza = ScriptDirectory.from_config(_config()).get_current_head()
        engine = create_engine(url or settings.DATABASE_URL)
        try:
            with engine.connect() as con:
                actual = MigrationContext.configure(con).get_current_revision()
        finally:
            engine.dispose()
        return {"actual": actual, "cabeza": cabeza, "al_dia": actual == cabeza}
    except Exception as exc:  # noqa: BLE001 — diagnosticar nunca debe tumbar el arranque
        return {"actual": None, "cabeza": None, "al_dia": False, "error": type(exc).__name__}


def asegurar_esquema(url: str | None = None, automatico: bool | None = None) -> dict:
    """Aplica `alembic upgrade head` si la base está atrasada y es SQLite local; en otros motores solo registra el aviso. Devuelve el estado final."""
    url = url or settings.DATABASE_URL
    if ":memory:" in url:
        return {"actual": None, "cabeza": None, "al_dia": True, "omitido": "base en memoria"}
    estado = estado_esquema(url)
    if estado.get("al_dia") or "error" in estado:
        return estado
    auto = settings.ESQUEMA_AUTOMATICO if automatico is None else automatico
    if not auto or not url.startswith("sqlite"):
        log.warning("la base está en la migración %s y el código espera %s: aplica `alembic upgrade head`", estado["actual"], estado["cabeza"])
        return estado
    try:
        from alembic import command

        original = settings.DATABASE_URL
        settings.DATABASE_URL = url  # el env.py de Alembic lee la URL de `settings`, no del .ini
        try:
            with _conservar_logging():
                command.upgrade(_config(), "head")
        finally:
            settings.DATABASE_URL = original
        log.warning("esquema actualizado automáticamente: %s → %s", estado["actual"], estado["cabeza"])
    except Exception:  # noqa: BLE001
        log.exception("no se pudo aplicar las migraciones al arrancar")
    return estado_esquema(url)
