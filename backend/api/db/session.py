"""
db/session.py — Engine, sesión, Base declarativa.

Patrón real tomado de db/session.py de otro proyecto del autor (proyecto de referencia en producción):
ramifica engine_kwargs según el dialecto detectado en DATABASE_URL, mismo código sirve
SQLite (dev) y Postgres (prod). Reemplaza el patrón "connect-per-call" de
db_query.py:conectar() (sqlite3.connect() nuevo en cada operación, sin pool).
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.api.core.config import settings

# busy_timeout: cuánto espera una conexión SQLite a que otra suelte el lock de escritura
# antes de lanzar "database is locked", en vez de fallar al instante. 5000ms — mismo valor
# que ya usaba el timeout=5 de sqlite3.connect() en db_query.py (patrón
# previo de este mismo proyecto), ahora aplicado como PRAGMA real en vez de un argumento
# del driver que WAL necesita reforzar de todas formas.
SQLITE_BUSY_TIMEOUT_MS = 5000


class Base(DeclarativeBase):
    pass


def _build_engine():
    kwargs: dict = {}
    if settings.is_sqlite:
        # check_same_thread=False: FastAPI puede usar la sesión desde distintos threads
        # (mismo motivo que PAGINA1) — la concurrencia real de escritura la sigue
        # arbitrando SQLite mismo (igual que hoy con timeout=5 en db_query.py).
        kwargs["connect_args"] = {"check_same_thread": False}
        # Crear el directorio de la BD si no existe (backend/db/ ya existe en el repo,
        # pero un venv nuevo en otra máquina podría no tenerlo).
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        if db_path not in (":memory:",):
            (settings.repo_root / db_path).parent.mkdir(parents=True, exist_ok=True)  # la ruta ya viene anclada a la raíz o es absoluta
    else:
        kwargs.update(pool_size=10, max_overflow=20, pool_recycle=3600, pool_pre_ping=True)
    return create_engine(settings.DATABASE_URL, **kwargs)


def _registrar_pragmas_sqlite(target_engine) -> None:
    """Registra un listener que aplica WAL + busy_timeout en CADA conexión nueva del pool
    de `target_engine` — no es algo que se aplique una sola vez al engine: son PRAGMA de
    conexión, así que sin este listener una conexión nueva abierta después del arranque
    quedaría en el modo journal por defecto (peor para escrituras concurrentes, sobre todo
    ahora que el single-flight de `services/gateway.py` permite que varias corutinas
    escriban seguido en `partidos_dia`). Función separada de `_build_engine` (en vez de
    quedar inline) para poder registrarla también sobre un engine de prueba en
    backend/tests/test_session.py — verificación empírica real vía `PRAGMA journal_mode`,
    no solo "el PRAGMA se ve bien en el código"."""

    @event.listens_for(target_engine, "connect")
    def _aplicar_pragmas_sqlite(dbapi_connection, connection_record) -> None:  # noqa: ANN001 — firma exigida por el hook de SQLAlchemy
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


engine = _build_engine()

if settings.is_sqlite:
    _registrar_pragmas_sqlite(engine)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
