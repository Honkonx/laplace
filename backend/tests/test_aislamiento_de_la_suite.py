"""La suite no puede tocar la base real: `conftest.py` fuerza SQLite en memoria antes de importar el backend."""
from __future__ import annotations

from backend.api.core.config import settings
from backend.api.db import session as sesion


def test_la_base_de_la_suite_es_en_memoria():
    assert settings.DATABASE_URL == "sqlite:///:memory:"
    assert "bot_deportivo.db" not in str(sesion.engine.url)


def test_el_sessionlocal_global_no_apunta_a_un_archivo():
    assert sesion.SessionLocal.kw["bind"].url.database in (None, "", ":memory:")
