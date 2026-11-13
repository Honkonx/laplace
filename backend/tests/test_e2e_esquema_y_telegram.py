"""Pruebas de punta a punta del esquema y del botón de Telegram, como las vive una persona (incidente del 2026-11-11).

Lo que NO hacen: parchear los repositorios. La base se construye con las MIGRACIONES REALES de Alembic (no con `create_all`, que es lo que ocultó el defecto), se simula el clic
con los manejadores reales y solo se falsea el límite con el exterior (Telegram y el análisis en segundo plano). Cubren una matriz de estados: esquema al día / atrasado, con y sin
consentimiento, plan free / pro, con y sin análisis en caché, analizar / recalcular.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401
from backend.api.bot import laplace_bot, laplace_bot_callbacks, laplace_bot_usuario
from backend.api.core import esquema
from backend.api.core.config import settings
from backend.api.db import bot_memoria_repo as memoria
from backend.api.db.session import Base

REVISION_ANTERIOR = "a1b2c3d4e5f7"  # una base local anterior a la migración de 2026-11-11 estaba en esta revisión


def _migrar(ruta, revision, monkeypatch):
    # el env.py de Alembic llama a logging.config.fileConfig, que deshabilita los loggers ya creados (rompería caplog en otras pruebas)
    estado = {n: lg.disabled for n, lg in logging.root.manager.loggerDict.items() if isinstance(lg, logging.Logger)}
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{ruta.as_posix()}")
    try:
        command.upgrade(Config("backend/api/alembic.ini"), revision)
    finally:
        for nombre, desactivado in estado.items():
            logging.getLogger(nombre).disabled = desactivado


# ---------------------------------------------------------------- esquema
def test_el_esquema_de_las_migraciones_es_el_de_los_modelos(tmp_path, monkeypatch):
    """Si alguien cambia un modelo y olvida la migración (o al revés), esta prueba falla: `create_all` ya no puede ocultarlo."""
    ruta = tmp_path / "m.db"
    _migrar(ruta, "head", monkeypatch)
    real = inspect(create_engine(f"sqlite:///{ruta.as_posix()}"))
    tablas_real = {t for t in real.get_table_names() if t != "alembic_version" and not t.startswith("agent_search_fts")}
    tablas_modelo = {t.name for t in Base.metadata.sorted_tables}
    assert tablas_real == tablas_modelo, f"sin migración: {tablas_modelo - tablas_real}; sin modelo: {tablas_real - tablas_modelo}"
    for tabla in Base.metadata.sorted_tables:
        columnas_real = {c["name"] for c in real.get_columns(tabla.name)}
        faltan = {c.name for c in tabla.columns} - columnas_real
        assert not faltan, f"{tabla.name}: columnas del modelo sin migrar: {faltan}"


def test_estado_y_arranque_actualizan_una_base_atrasada(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    _migrar(ruta, REVISION_ANTERIOR, monkeypatch)
    url = f"sqlite:///{ruta.as_posix()}"
    antes = esquema.estado_esquema(url)
    assert antes["al_dia"] is False and antes["actual"] == REVISION_ANTERIOR and antes["cabeza"] != REVISION_ANTERIOR
    assert esquema.asegurar_esquema(url, automatico=False)["al_dia"] is False  # solo avisa
    assert esquema.asegurar_esquema(url, automatico=True)["al_dia"] is True
    con = sqlite3.connect(ruta)
    assert {"bot_consentimientos", "bot_preferencias", "agent_uso_diario"} <= {r[0] for r in con.execute("select name from sqlite_master")}
    con.close()


def test_en_otro_motor_solo_se_avisa_y_no_se_toca_nada(monkeypatch):
    monkeypatch.setattr(esquema, "estado_esquema", lambda url=None: {"actual": "x", "cabeza": "y", "al_dia": False})
    llamado = MagicMock()
    monkeypatch.setattr("alembic.command.upgrade", llamado)
    assert esquema.asegurar_esquema("postgresql://u:p@h/db", automatico=True)["al_dia"] is False
    llamado.assert_not_called()


def test_si_no_se_puede_leer_el_esquema_no_se_rompe_el_arranque():
    r = esquema.estado_esquema("sqlite:////ruta/que/no/existe/x.db")
    assert r["al_dia"] is False


# ---------------------------------------------------------------- botón de Telegram
def _update(user_id="900"):
    u = MagicMock()
    u.effective_user.id = int(user_id)
    u.effective_user.first_name = "Ana"
    u.effective_chat.id = int(user_id)
    u.callback_query.id = "cbq"
    u.callback_query.message.reply_html = AsyncMock()
    return u


def _ctx():
    c = MagicMock()
    c.application.bot_data = {"http_client": MagicMock()}
    return c


MATRIZ = list(itertools.product(["al_dia", "atrasado"], [False, True], ["free", "pro"], [False, True], ["PREDICT", "REFRESH"]))


@pytest.mark.parametrize("estado_esquema,consentimiento,plan,en_cache,accion", MATRIZ, ids=lambda v: str(v))
def test_el_clic_en_analizar_siempre_responde_y_crea_el_trabajo(tmp_path, monkeypatch, estado_esquema, consentimiento, plan, en_cache, accion):
    if consentimiento and estado_esquema == "atrasado":
        pytest.skip("sin las tablas de memoria no se puede dar consentimiento")
    ruta = tmp_path / "e2e.db"
    _migrar(ruta, "head" if estado_esquema == "al_dia" else REVISION_ANTERIOR, monkeypatch)
    fabrica = sessionmaker(bind=create_engine(f"sqlite:///{ruta.as_posix()}", connect_args={"check_same_thread": False}))
    for modulo in (laplace_bot_callbacks, laplace_bot_usuario):
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", AsyncMock())
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    from backend.api.models.usuarios import Usuario

    with fabrica() as db:
        db.add(Usuario(device_id="900", activo=1, plan=plan, creado_en="2026-11-11 10:00:00"))
        db.commit()
        if consentimiento:
            memoria.aceptar(db, "900")
    if en_cache:
        from backend.api.models.predicciones import CacheConsenso

        with fabrica() as db:
            db.add(CacheConsenso(partido_id="m1", pick_consenso="Local", texto_consenso="Resultado en caché", total_analisis=1, usos=0, max_usos=5, expira_en="2099-01-01 00:00:00", creado_en="2026-11-11 10:00:00"))
            db.commit()
    update = _update()
    update.callback_query.data = f"{accion}_20261111_m1"
    asyncio.run(laplace_bot_callbacks.callback_predict(update, _ctx()))
    respuestas = [c.args[0] for c in update.callback_query.message.reply_html.call_args_list]
    assert respuestas, "el usuario no recibió ninguna respuesta"
    with fabrica() as db:
        n_jobs = db.execute(text("select count(*) from jobs where match_id='m1'")).scalar()
    if en_cache and accion == "PREDICT":
        assert "Resultado en caché" in respuestas[0] and n_jobs == 0
    else:
        assert "Analizando partido" in respuestas[0] and n_jobs == 1
        if estado_esquema == "al_dia" and consentimiento:
            with fabrica() as db:
                assert memoria.historial(db, "900")[0]["partido_id"] == "m1"


def test_migrar_al_arrancar_no_apaga_los_registros_de_la_aplicacion(tmp_path, monkeypatch):
    """Antes de la corrección, `alembic` reconfiguraba el logging y la aplicación quedaba sin registros tras el arranque."""
    ruta = tmp_path / "log.db"
    _migrar(ruta, REVISION_ANTERIOR, monkeypatch)
    log = logging.getLogger("laplace.prueba_e2e")
    nivel_raiz, manejadores = logging.getLogger().level, list(logging.getLogger().handlers)
    assert esquema.asegurar_esquema(f"sqlite:///{ruta.as_posix()}", automatico=True)["al_dia"] is True
    assert log.disabled is False and logging.getLogger().level == nivel_raiz and logging.getLogger().handlers == manejadores
