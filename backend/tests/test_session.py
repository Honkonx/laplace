"""test_session.py — WAL + busy_timeout reales aplicados en cada conexión SQLite nueva.

Verificación empírica (no solo "el PRAGMA se ve bien en el código"): se registra el mismo
listener que usa el engine real (`session._registrar_pragmas_sqlite`) sobre un engine de
prueba apuntando a un archivo SQLite temporal (nunca contra `backend/db/bot_deportivo.db`
real, ver `.claude/rules/database-safety.md`), y se lee `PRAGMA journal_mode`/
`PRAGMA busy_timeout` de vuelta desde una conexión real — no se asume que quedó aplicado
solo por haber escrito el `@event.listens_for`.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from backend.api.db import session as session_module


def test_registrar_pragmas_sqlite_aplica_wal_y_busy_timeout(tmp_path: Path):
    """`connect_args={"timeout": 0}` neutraliza el default propio del driver `sqlite3`
    (`sqlite3.connect(..., timeout=5.0)` ya deja busy_timeout en 5000ms por su cuenta,
    aunque nuestro PRAGMA no exista — confirmado empíricamente antes de escribir este
    test). Con el default neutralizado en 0, un busy_timeout=5000 después de conectar solo
    puede venir de nuestro `PRAGMA busy_timeout=5000` real, no de una casualidad del driver."""
    db_path = tmp_path / "test_pragmas.db"
    engine_sin_pragma = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 0}
    )
    with engine_sin_pragma.connect() as conn:
        journal_mode_base = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout_base = conn.execute(text("PRAGMA busy_timeout")).scalar()
    engine_sin_pragma.dispose()
    assert journal_mode_base.lower() != "wal", "baseline ya venía en WAL — el test no probaría nada"
    assert busy_timeout_base == 0, "baseline ya traía busy_timeout != 0 — el test no probaría nada"

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 0})
    session_module._registrar_pragmas_sqlite(engine)

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()

    assert journal_mode is not None and journal_mode.lower() == "wal"
    assert busy_timeout == session_module.SQLITE_BUSY_TIMEOUT_MS

    engine.dispose()


def test_registrar_pragmas_sqlite_aplica_en_conexiones_nuevas_del_pool(tmp_path: Path):
    """El PRAGMA es por-conexión, no por-engine — una segunda conexión abierta después de
    la primera (ej. NullPool/QueuePool reciclando) también debe quedar en WAL, no solo la
    primera conexión que abrió el archivo."""
    db_path = tmp_path / "test_pragmas_pool.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_module._registrar_pragmas_sqlite(engine)

    with engine.connect() as conn1:
        conn1.execute(text("PRAGMA journal_mode")).scalar()

    with engine.connect() as conn2:
        journal_mode_2 = conn2.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout_2 = conn2.execute(text("PRAGMA busy_timeout")).scalar()

    assert journal_mode_2.lower() == "wal"
    assert busy_timeout_2 == session_module.SQLITE_BUSY_TIMEOUT_MS

    engine.dispose()


def test_build_engine_mas_registro_de_pragmas_reproduce_el_arranque_real(tmp_path: Path, monkeypatch):
    """Reproduce exactamente lo que hace el import de session.py (`_build_engine()` +
    `_registrar_pragmas_sqlite(engine)` si `settings.is_sqlite`), pero apuntando a un
    archivo SQLite temporal en vez de `backend/db/bot_deportivo.db` real — confirma que la
    integración completa (no solo la función aislada) deja WAL + busy_timeout aplicados."""
    db_path = tmp_path / "test_arranque.db"
    monkeypatch.setattr(session_module.settings, "DATABASE_URL", f"sqlite:///{db_path}")

    engine = session_module._build_engine()
    assert session_module.settings.is_sqlite
    session_module._registrar_pragmas_sqlite(engine)

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()

    assert journal_mode.lower() == "wal"
    assert busy_timeout == session_module.SQLITE_BUSY_TIMEOUT_MS

    engine.dispose()
