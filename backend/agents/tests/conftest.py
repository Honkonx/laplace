"""conftest.py — fixtures compartidas para los tests de laplace-agents. BD en memoria por
test, nunca toca `backend/db/bot_deportivo.db` real. Mismo patrón que
`backend/tests/conftest.py` — duplicado a propósito acá (no importado cruzado) porque
`laplace-agents` es un proyecto separado del backend, no una subcarpeta suya."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("CORS_ORIGINS", "http://localhost:4321")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend" / "agents"))

from backend.api.db.session import Base  # noqa: E402
import backend.api.models  # noqa: E402,F401  (registra todos los modelos en Base.metadata)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
