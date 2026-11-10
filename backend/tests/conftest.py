"""conftest.py — fixtures compartidas. BD en memoria por test, nunca toca
backend/db/bot_deportivo.db real."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# CORS_ORIGINS debe estar en el entorno ANTES de que `backend.api.core.config` (y por lo
# tanto `backend.api.main`, un singleton importado por varios módulos de test) se importe
# por primera vez en la sesión de pytest — CORSMiddleware queda "horneado" con la lista de
# orígenes al momento en que `main.py` arma la app, no se puede cambiar después. Se usa
# `setdefault` para no pisar un CORS_ORIGINS real si el entorno de CI ya lo trae seteado.
# Ver test_security_ops.py::test_cors_header_presente_para_origen_permitido.
os.environ.setdefault("CORS_ORIGINS", "http://localhost:4321")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# `pytest.ini` fija `--basetemp=.qa/pytest` y `.qa/` está gitignorada: en un checkout limpio (CI) la
# carpeta padre no existe y pytest falla al crear su temporal (FileNotFoundError en TODOS los tests).
(REPO_ROOT / ".qa").mkdir(exist_ok=True)

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


@pytest.fixture(autouse=True)
def _sin_claves_de_ia_reales(monkeypatch):
    """Ningún test usa claves de IA reales del `.env` (gastarían cuota o harían llamadas de red por accidente y
    cambiarían el resultado según la máquina). Los tests que necesitan un proveedor lo configuran ellos mismos."""
    from backend.api.core.config import settings

    for nombre in ("GROQ_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_API_KEY"):
        if hasattr(settings, nombre):
            monkeypatch.setattr(settings, nombre, "")
    # El orden de la cascada también sale del `.env` (AI_ROUTING_*): sin vaciarlo, los tests dependen de la máquina
    # (2026-11-09: poner Ollama Cloud primero en el `.env` rompió un test que espera el orden por defecto).
    for rol in ("BOT", "CANAL", "AGENTE", "LABORATORIO"):
        monkeypatch.setattr(settings, f"AI_ROUTING_{rol}", "")
    # Canal y grupo de Telegram también salen del `.env` (sin valor por defecto desde 2026-11-09, repo público): los tests usan los suyos.
    monkeypatch.setattr(settings, "TELEGRAM_CANAL_ID", "@canal_de_prueba")
    monkeypatch.setattr(settings, "TELEGRAM_GRUPO_URL", "https://t.me/grupo_de_prueba")
    monkeypatch.setattr(settings, "TELEGRAM_GRUPO_NOMBRE", "Grupo de la comunidad")


@pytest.fixture(autouse=True)
def _artefactos_ml_aislados(tmp_path, monkeypatch):
    """Los tests nunca dependen de `ml/artefactos/` ni de `knowledge/` reales: se regeneran con
    cada evaluación y harían que un partido de prueba (ej. River-Boca en "Liga Profesional")
    sumara o no el módulo `historico` según cuándo se corrió el último entrenamiento. Los tests
    de `modelo_historico` pisan estas rutas con sus propios artefactos sintéticos."""
    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "DIR_ARTEFACTOS", tmp_path / "sin_artefactos")
    monkeypatch.setattr(modelo_historico, "RUTA_TASAS", tmp_path / "sin_tasas.json")
    modelo_historico._artefactos.cache_clear()
    modelo_historico._tasas_por_liga.cache_clear()
    yield
    modelo_historico._artefactos.cache_clear()
    modelo_historico._tasas_por_liga.cache_clear()


@pytest.fixture(autouse=True)
def _resetear_estado_global_entre_tests(monkeypatch):
    """`services/circuit_breaker.py` y `services/ai_metrics.py` guardan estado in-memory en un
    dict a nivel de módulo (mismo criterio que `gateway._fixtures_locks`) — sin este reset, un
    test que abre un circuit breaker (o acumula métricas de IA) contaminaría el siguiente test
    que reusa el mismo nombre de fuente/proveedor, incluso sin relación entre ambos tests.

    También parchea `ai_metrics.SessionLocal` (2026-09-10, ver `models/metricas.py` — el INSERT
    real de `registrar_intento` abre su propia sesión corta vía `SessionLocal`, en vez de recibir
    `db` como parámetro, para no threadear una sesión a través de las 4 funciones de proveedor de
    `ai_client.py` y todos sus callers) hacia un engine en memoria dedicado — el docstring de
    este archivo promete "nunca toca backend/db/bot_deportivo.db real", y sin este parche
    cualquier test que dispare `ai_client.generar_texto_ia` (incluida la cascada real, mockeada
    o no) insertaría filas reales en la BD de producción."""
    from backend.api.services import _http_retry, ai_metrics, circuit_breaker, gateway

    engine_metricas = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine_metricas)
    monkeypatch.setattr(ai_metrics, "SessionLocal", sessionmaker(bind=engine_metricas))

    circuit_breaker.resetear_todos()
    ai_metrics.resetear()
    gateway._fixtures_apif_dia.clear()  # caché en memoria de los partidos del día de api-football
    _http_retry._ventana_api_football.clear()
    from backend.api.services import team_stats_fetch
    team_stats_fetch._temporadas_sin_acceso.clear()
    monkeypatch.setattr(_http_retry, "LIMITE_API_FOOTBALL_POR_MINUTO", 10_000)  # los tests no esperan el límite real
    yield
    circuit_breaker.resetear_todos()
    ai_metrics.resetear()
