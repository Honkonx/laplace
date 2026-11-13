"""test_laplace_bot.py — Tests reales para `backend/api/bot/laplace_bot.py` (cero cobertura hasta
esta ronda). No hay `pytest-asyncio` instalado en el venv del proyecto — los handlers async se
corren con `asyncio.run()` dentro de tests sync (ver `_run` abajo), mismo patrón que
`_usuario_desde_update`/`callback_predict` esperan (una corrida completa del event loop,
incluyendo las tareas de fondo que `callback_predict` lanza con `asyncio.create_task`).

Cubre:
  - `_es_admin` (con y sin permiso)
  - `cmd_generarcodigos` (caso exitoso + caso sin ser admin)
  - `cmd_gestionarusuario` (cambia plan de un usuario existente + rechazo sin admin +
    usuario inexistente)
  - Flujo de verificación de límite antes de un análisis — SÍ vive en este archivo
    (`callback_predict`, que llama `usuarios_repo.verificar_limite` antes de crear el job) —
    se testea bloqueo y paso.
  - Los 3 comandos nuevos de UX de esta ronda: fallback de comando desconocido, `/misplanes`,
    `/favoritos` (agregar/quitar/límite de 3/listar).

Nunca toca `backend/db/bot_deportivo.db` real — cada test usa una BD SQLite en memoria propia
inyectada en `laplace_bot.SessionLocal` (el nombre importado a nivel de módulo, no el
`sessionmaker` real de `backend/api/db/session.py`).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api.bot import laplace_bot
from backend.api.bot import laplace_bot_admin, laplace_bot_callbacks, laplace_bot_usuario

# `SessionLocal` ya no vive solo en `laplace_bot`: cada módulo que abre sesión tiene su propio nombre.
_MODULOS_CON_SESION = (laplace_bot_usuario, laplace_bot_callbacks, laplace_bot_admin)
from backend.api.core.config import settings
from backend.api.db.session import Base
from backend.api.models.auditoria import AccionAdminAuditoria
from backend.api.models.predicciones import PrediccionUsuario
from backend.api.models.usuarios import CodigoAcceso, Usuario


@pytest.fixture()
def sesion_bot(monkeypatch):
    """Reemplaza `laplace_bot.SessionLocal` (el nombre importado a nivel de módulo desde
    `backend/api/db/session.py`) por un sessionmaker propio en memoria — los comandos del bot
    hacen `with SessionLocal() as db:`, así que basta con parchear el atributo del módulo para
    que usen la BD de test en vez de `backend/db/bot_deportivo.db`."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    for modulo in _MODULOS_CON_SESION:
        monkeypatch.setattr(modulo, "SessionLocal", testing_session_local)
    return testing_session_local


@pytest.fixture(autouse=True)
def sin_admins_por_defecto(monkeypatch):
    """Cada test que necesite un admin lo declara explícitamente con
    `monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "...")` — sin esto, un admin_id que
    quedó seteado en el `.env` real del entorno de desarrollo podría colar un test como "admin"
    sin que el test lo pida."""
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")


def _update(user_id: str = "123", first_name: str = "Jhos", chat_id: str | None = None) -> MagicMock:
    """Mock mínimo de `telegram.Update` para comandos de texto (`update.message.reply_html`)."""
    update = MagicMock()
    update.effective_user.id = int(user_id)
    update.effective_user.first_name = first_name
    update.effective_chat.id = int(chat_id if chat_id is not None else user_id)
    update.message.reply_html = AsyncMock()
    return update


def _update_callback(data: str, user_id: str = "900", callback_id: str = "cbq1") -> MagicMock:
    """Mock mínimo de `telegram.Update` para un `CallbackQueryHandler` (`update.callback_query`)."""
    update = MagicMock()
    update.effective_user.id = int(user_id)
    update.effective_user.first_name = "Test"
    update.effective_chat.id = int(user_id)
    update.callback_query.id = callback_id
    update.callback_query.data = data
    update.callback_query.message.reply_html = AsyncMock()
    return update


def _context(args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = args or []
    context.application.bot_data = {"http_client": MagicMock()}
    return context


def _run(coro):
    """`asyncio.run()` + drena cualquier tarea de fondo creada con `asyncio.create_task`
    (ej. `callback_predict` -> `_procesar_job_en_fondo`) antes de cerrar el loop — sin esto,
    un mock async pendiente queda destruido a mitad de ejecución con un warning ruidoso."""
    async def runner():
        resultado = await coro
        pendientes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pendientes:
            await asyncio.gather(*pendientes, return_exceptions=True)
        return resultado

    return asyncio.run(runner())


def _texto_respuesta(mock_reply_html: AsyncMock) -> str:
    return mock_reply_html.call_args[0][0]


# ---------------------------------------------------------------------------------------------
# _es_admin
# ---------------------------------------------------------------------------------------------

def test_es_admin_reconoce_id_en_settings(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111,222")
    assert laplace_bot._es_admin(_update(user_id="111")) is True
    assert laplace_bot._es_admin(_update(user_id="222")) is True


def test_es_admin_rechaza_id_no_listado(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    assert laplace_bot._es_admin(_update(user_id="999")) is False


def test_es_admin_lista_vacia_nadie_es_admin(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")
    assert laplace_bot._es_admin(_update(user_id="111")) is False


# ---------------------------------------------------------------------------------------------
# cmd_generarcodigos
# ---------------------------------------------------------------------------------------------

def test_cmd_generarcodigos_sin_ser_admin_rechaza(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="999")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["5", "pro", "30"])))

    assert "No autorizado" in _texto_respuesta(update.message.reply_html)
    with sesion_bot() as db:
        assert db.query(CodigoAcceso).count() == 0


def test_cmd_generarcodigos_exitoso_genera_codigos_reales_en_bd(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="111")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["3", "pro", "30"])))

    texto = _texto_respuesta(update.message.reply_html)
    assert "3 códigos PRO" in texto
    # Post-condición real en la BD, no solo el texto de respuesta al usuario (empirical-verification-before-fix.md).
    with sesion_bot() as db:
        codigos = db.query(CodigoAcceso).all()
        assert len(codigos) == 3
        assert all(c.plan == "pro" and c.dias == 30 and c.usado == 0 for c in codigos)


def test_cmd_generarcodigos_argumentos_invalidos_no_genera_nada(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="111")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["cinco", "pro", "30"])))

    assert "números" in _texto_respuesta(update.message.reply_html)
    with sesion_bot() as db:
        assert db.query(CodigoAcceso).count() == 0


def test_cmd_generarcodigos_exitoso_deja_rastro_de_auditoria(sesion_bot, monkeypatch):
    """Hallazgo real de la auditoría 2026-09-09: este comando no dejaba ningún rastro de quién
    lo ejecutó más allá de logs de proceso. Verifica la post-condición real en
    `accion_admin_auditoria`, no solo que el comando haya respondido con éxito."""
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="111")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["3", "pro", "30"])))

    with sesion_bot() as db:
        registros = db.query(AccionAdminAuditoria).all()
        assert len(registros) == 1
        assert registros[0].actor_admin_id == "111"
        assert registros[0].accion == "generar_codigos"
        assert "3 codigos pro" in registros[0].detalle


def test_cmd_generarcodigos_sin_ser_admin_no_deja_rastro_de_auditoria(sesion_bot, monkeypatch):
    """El rechazo por permisos ocurre antes de tocar la BD — no debe crear un registro de
    auditoría de una acción que nunca se ejecutó."""
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="999")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["5", "pro", "30"])))

    with sesion_bot() as db:
        assert db.query(AccionAdminAuditoria).count() == 0


def test_cmd_generarcodigos_argumentos_invalidos_no_deja_rastro_de_auditoria(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="111")
    _run(laplace_bot.cmd_generarcodigos(update, _context(["cinco", "pro", "30"])))

    with sesion_bot() as db:
        assert db.query(AccionAdminAuditoria).count() == 0


# ---------------------------------------------------------------------------------------------
# cmd_gestionarusuario
# ---------------------------------------------------------------------------------------------

def test_cmd_gestionarusuario_sin_ser_admin_rechaza(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="999")
    _run(laplace_bot.cmd_gestionarusuario(update, _context(["u1", "activar"])))
    assert "No autorizado" in _texto_respuesta(update.message.reply_html)


def test_cmd_gestionarusuario_cambia_plan_de_usuario_existente(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    with sesion_bot() as db:
        db.add(Usuario(device_id="u_test", activo=1, plan="free", creado_en="2026-01-01 00:00:00"))
        db.commit()

    update = _update(user_id="111")
    _run(laplace_bot.cmd_gestionarusuario(update, _context(["u_test", "plan:pro"])))

    assert "plan_actualizado" in _texto_respuesta(update.message.reply_html)
    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "u_test").first()
        assert usuario.plan == "pro"


def test_cmd_gestionarusuario_desactiva_usuario_existente(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    with sesion_bot() as db:
        db.add(Usuario(device_id="u_desact", activo=1, plan="free", creado_en="2026-01-01 00:00:00"))
        db.commit()

    update = _update(user_id="111")
    _run(laplace_bot.cmd_gestionarusuario(update, _context(["u_desact", "desactivar"])))

    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "u_desact").first()
        assert usuario.activo == 0


def test_cmd_gestionarusuario_usuario_inexistente_devuelve_error(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111")
    update = _update(user_id="111")
    _run(laplace_bot.cmd_gestionarusuario(update, _context(["no_existe", "activar"])))
    assert "no encontrado" in _texto_respuesta(update.message.reply_html)


# ---------------------------------------------------------------------------------------------
# Flujo de verificación de límite antes de un análisis — vive en `callback_predict`
# (usuarios_repo.verificar_limite se llama ANTES de jobs_repo.crear_job).
# ---------------------------------------------------------------------------------------------

def test_callback_predict_bloquea_analisis_si_limite_ia_alcanzado(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.analisis_repo, "verificar_consenso_cache",
        lambda db, partido_id: {"cache_consenso_hit": False, "job_en_vuelo": False},
    )
    monkeypatch.setattr(
        laplace_bot.usuarios_repo, "verificar_limite",
        lambda db, user_id, plan: {"puede": False, "usados": 10, "limite": 10},
    )
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    crear_job_mock = MagicMock()
    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", crear_job_mock)

    update = _update_callback("PREDICT_20260101_m1", user_id="900")
    _run(laplace_bot.callback_predict(update, _context()))

    texto = _texto_respuesta(update.callback_query.message.reply_html)
    assert "Límite IA diario alcanzado" in texto
    crear_job_mock.assert_not_called()


def test_callback_predict_bajo_limite_crea_job_y_lanza_analisis_en_fondo(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.analisis_repo, "verificar_consenso_cache",
        lambda db, partido_id: {"cache_consenso_hit": False, "job_en_vuelo": False},
    )
    monkeypatch.setattr(
        laplace_bot.usuarios_repo, "verificar_limite",
        lambda db, user_id, plan: {"puede": True, "usados": 2, "limite": 10},
    )
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", lambda db, **kwargs: {"job_id": "job123"})
    fondo_mock = AsyncMock()
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", fondo_mock)

    update = _update_callback("PREDICT_20260101_m2", user_id="901")
    _run(laplace_bot.callback_predict(update, _context()))

    texto = _texto_respuesta(update.callback_query.message.reply_html)
    assert "Analizando partido" in texto
    fondo_mock.assert_awaited_once()


def test_callback_predict_no_crea_job_si_ya_hay_uno_en_vuelo(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.analisis_repo, "verificar_consenso_cache",
        lambda db, partido_id: {"cache_consenso_hit": False, "job_en_vuelo": True},
    )
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    crear_job_mock = MagicMock()
    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", crear_job_mock)
    limite_mock = MagicMock(return_value={"puede": True, "usados": 0, "limite": 6})
    monkeypatch.setattr(laplace_bot.usuarios_repo, "verificar_limite", limite_mock)

    update = _update_callback("PREDICT_20260101_m3", user_id="902")
    _run(laplace_bot.callback_predict(update, _context()))

    texto = _texto_respuesta(update.callback_query.message.reply_html)
    assert "Análisis en progreso" in texto
    crear_job_mock.assert_not_called()
    # el límite se revisa ANTES de anotar la espera (revisión de seguridad 2026-11-11): quien no tiene derecho no entra a la cola
    limite_mock.assert_called_once()


# ---------------------------------------------------------------------------------------------
# UX 1 — comando desconocido (fallback)
# ---------------------------------------------------------------------------------------------

def test_cmd_desconocido_responde_algo_util_en_vez_de_silencio():
    update = _update(user_id="1")
    _run(laplace_bot.cmd_desconocido(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert texto  # antes: silencio total, ningún handler respondía
    assert "/ayuda" in texto


# ---------------------------------------------------------------------------------------------
# UX 2 — /misplanes
# ---------------------------------------------------------------------------------------------

def test_cmd_misplanes_usuario_free_nuevo_sin_vencimiento(sesion_bot):
    update = _update(user_id="500")
    _run(laplace_bot.cmd_misplanes(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert "FREE" in texto
    assert "Sin vencimiento" in texto


def test_cmd_misplanes_usuario_con_plan_activo_muestra_fecha_de_vencimiento(sesion_bot):
    with sesion_bot() as db:
        db.add(Usuario(device_id="600", activo=1, plan="pro", activo_hasta="2099-01-01",
                        origen="telegram", creado_en="2026-01-01 00:00:00"))
        db.commit()

    update = _update(user_id="600")
    _run(laplace_bot.cmd_misplanes(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert "PRO" in texto
    assert "2099-01-01" in texto


def test_cmd_misplanes_admin_muestra_mensaje_especial_sin_vencimiento(sesion_bot, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "700")
    update = _update(user_id="700")
    _run(laplace_bot.cmd_misplanes(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert "ADMIN" in texto


# ---------------------------------------------------------------------------------------------
# UX 3 — /favoritos (guardar hasta 3 ligas)
# ---------------------------------------------------------------------------------------------

def test_cmd_favoritos_sin_argumentos_y_sin_guardados_muestra_ayuda(sesion_bot):
    update = _update(user_id="800")
    _run(laplace_bot.cmd_favoritos(update, _context()))

    assert "No tienes ninguna" in _texto_respuesta(update.message.reply_html)


def test_cmd_favoritos_agregar_y_luego_listar(sesion_bot):
    update1 = _update(user_id="801")
    _run(laplace_bot.cmd_favoritos(update1, _context(["agregar", "LaLiga"])))
    assert "agregada" in _texto_respuesta(update1.message.reply_html)

    update2 = _update(user_id="801")
    _run(laplace_bot.cmd_favoritos(update2, _context()))
    assert "LaLiga" in _texto_respuesta(update2.message.reply_html)

    # Post-condición real en la BD.
    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "801").first()
        assert usuario.favoritos_ligas == "LaLiga"


def test_cmd_favoritos_no_duplica_la_misma_liga(sesion_bot):
    for _ in range(2):
        update = _update(user_id="804")
        _run(laplace_bot.cmd_favoritos(update, _context(["agregar", "LaLiga"])))

    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "804").first()
        assert usuario.favoritos_ligas == "LaLiga"


def test_cmd_favoritos_respeta_limite_maximo_de_tres(sesion_bot):
    update0 = _update(user_id="802")
    _run(laplace_bot.cmd_favoritos(update0, _context(["agregar", "LaLiga"])))   # esto registra a la persona (plan free: 1 liga)
    with sesion_bot() as db:
        db.query(Usuario).filter(Usuario.device_id == "802").update({"plan": "pro"})  # MS-11: el tope de 3 ligas es el del plan pro
        db.commit()
    for liga in ("Premier League", "Serie A"):
        update = _update(user_id="802")
        _run(laplace_bot.cmd_favoritos(update, _context(["agregar", liga])))

    update4 = _update(user_id="802")
    _run(laplace_bot.cmd_favoritos(update4, _context(["agregar", "Bundesliga"])))
    texto = _texto_respuesta(update4.message.reply_html)
    assert "máximo" in texto.lower() or "3 ligas" in texto

    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "802").first()
        assert usuario.favoritos_ligas.count("|") == 2  # 3 ligas guardadas, no 4


def test_cmd_favoritos_quitar_una_guardada(sesion_bot):
    update1 = _update(user_id="803")
    _run(laplace_bot.cmd_favoritos(update1, _context(["agregar", "LaLiga"])))

    update2 = _update(user_id="803")
    _run(laplace_bot.cmd_favoritos(update2, _context(["quitar", "LaLiga"])))
    assert "quitada" in _texto_respuesta(update2.message.reply_html)

    with sesion_bot() as db:
        usuario = db.query(Usuario).filter(Usuario.device_id == "803").first()
        assert usuario.favoritos_ligas is None


def test_cmd_favoritos_quitar_liga_no_guardada_avisa_sin_romper(sesion_bot):
    update = _update(user_id="805")
    _run(laplace_bot.cmd_favoritos(update, _context(["quitar", "LaLiga"])))
    texto = _texto_respuesta(update.message.reply_html)
    assert "no estaba" in texto


# ---------------------------------------------------------------------------------------------
# /encuesta + callback_voto — primer paso real de "Laplace-Agents le pregunta a los usuarios,
# tipo encuestas" (captura del voto, ver backend/api/db/predicciones_usuario_repo.py).
# ---------------------------------------------------------------------------------------------

_STAGES_UN_PARTIDO_HOY = [
    {
        "Snm": "Premier League",
        "Events": [
            {"Eid": "ev1", "Eps": "NS", "T1": [{"Nm": "Arsenal"}], "T2": [{"Nm": "Chelsea"}]},
            {"Eid": "ev2", "Eps": "FT", "T1": [{"Nm": "Liverpool"}], "T2": [{"Nm": "Everton"}]},
        ],
    },
]


def test_cmd_encuesta_muestra_primer_partido_con_tres_botones_de_voto(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.gateway, "obtener_fixtures_cascada",
        AsyncMock(return_value=(_STAGES_UN_PARTIDO_HOY, "bd")),
    )
    update = _update(user_id="1000")
    _run(laplace_bot.cmd_encuesta(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert "Arsenal" in texto and "Chelsea" in texto

    teclado = update.message.reply_html.call_args.kwargs["reply_markup"]
    botones = teclado.inline_keyboard[0]
    assert len(botones) == 3
    callbacks = {b.callback_data for b in botones}
    assert callbacks == {"VOTE_ev1_L", "VOTE_ev1_E", "VOTE_ev1_V"}
    # El partido FT (ya iniciado) nunca debería quedar seleccionable — confirmado por el Eid.
    assert all("ev2" not in cb for cb in callbacks)


def test_cmd_encuesta_sin_partidos_hoy_avisa_sin_romper(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.gateway, "obtener_fixtures_cascada",
        AsyncMock(return_value=([], "bd")),
    )
    update = _update(user_id="1001")
    _run(laplace_bot.cmd_encuesta(update, _context()))

    texto = _texto_respuesta(update.message.reply_html)
    assert "No hay partidos disponibles" in texto


def test_callback_voto_guarda_voto_real_en_bd(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    update = _update_callback("VOTE_partidoX_L", user_id="2000")
    _run(laplace_bot.callback_voto(update, _context()))

    texto = _texto_respuesta(update.callback_query.message.reply_html)
    assert "Local" in texto
    # Post-condición real en la BD (empirical-verification-before-fix.md), no solo el texto.
    with sesion_bot() as db:
        fila = db.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "partidoX").first()
        assert fila is not None
        assert fila.telegram_user_id == "2000"
        assert fila.pick == "local"


def test_callback_voto_empate_y_visitante_guardan_el_pick_correcto(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())

    _run(laplace_bot.callback_voto(_update_callback("VOTE_partidoY_E", user_id="2001"), _context()))
    _run(laplace_bot.callback_voto(_update_callback("VOTE_partidoY_V", user_id="2002"), _context()))

    with sesion_bot() as db:
        picks = {
            f.telegram_user_id: f.pick
            for f in db.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "partidoY").all()
        }
        assert picks == {"2001": "empate", "2002": "visitante"}


def test_callback_voto_codigo_no_reconocido_no_guarda_nada(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    update = _update_callback("VOTE_partidoZ_Q", user_id="2003")
    _run(laplace_bot.callback_voto(update, _context()))

    with sesion_bot() as db:
        assert db.query(PrediccionUsuario).count() == 0


def test_callback_voto_mismo_usuario_cambia_de_opinion_actualiza_en_vez_de_duplicar(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())

    _run(laplace_bot.callback_voto(_update_callback("VOTE_partidoW_L", user_id="2004"), _context()))
    segundo_update = _update_callback("VOTE_partidoW_V", user_id="2004")
    _run(laplace_bot.callback_voto(segundo_update, _context()))

    texto = _texto_respuesta(segundo_update.callback_query.message.reply_html)
    assert "actualizado" in texto
    with sesion_bot() as db:
        filas = db.query(PrediccionUsuario).filter(
            PrediccionUsuario.match_id == "partidoW", PrediccionUsuario.telegram_user_id == "2004",
        ).all()
        assert len(filas) == 1
        assert filas[0].pick == "visitante"


def test_leer_agregado_refleja_los_votos_reales_guardados_por_el_bot(sesion_bot, monkeypatch):
    """Integra `callback_voto` (escritura, vía el bot) con
    `predicciones_usuario_repo.leer_agregado` (lectura, función de agregación de esta ronda) —
    confirma que lo que el bot guarda es lo mismo que la función de lectura reporta."""
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    for user_id, codigo in (("3001", "L"), ("3002", "L"), ("3003", "E")):
        _run(laplace_bot.callback_voto(_update_callback(f"VOTE_partidoV_{codigo}", user_id=user_id), _context()))

    with sesion_bot() as db:
        agregado = laplace_bot.predicciones_usuario_repo.leer_agregado(db, "partidoV")
        assert agregado == {"local": 2, "empate": 1, "visitante": 0, "total": 3}


# ---------------------------------------------------------------------------------------------
# /vincular — sincronización de plan entre cuenta Web/App y Telegram
# ---------------------------------------------------------------------------------------------

def test_cmd_vincular_sincroniza_plan_pro_de_cuenta_web_a_telegram(sesion_bot):
    from backend.api.services.auth_password import hashear_password

    with sesion_bot() as db:
        u_web = laplace_bot.usuarios_repo.crear_usuario_credenciales(
            db, "usuariowebpro", hashear_password("claveCorrecta1"), "web", "2026-09-25"
        )
        u_web.plan = "pro"
        u_web.activo_hasta = "2099-12-31"
        db.commit()

    update = _update(user_id="4001")
    _run(laplace_bot.cmd_vincular(update, _context(["usuariowebpro", "claveCorrecta1"])))

    texto = _texto_respuesta(update.message.reply_html)
    assert "PRO" in texto
    with sesion_bot() as db:
        fila_tg = db.query(Usuario).filter(Usuario.device_id == "4001").first()
        assert fila_tg is not None
        assert fila_tg.plan == "pro"
        assert fila_tg.activo_hasta == "2099-12-31"


def test_callback_predict_refresh_ignora_cache_consenso_y_crea_job(sesion_bot, monkeypatch):
    monkeypatch.setattr(
        laplace_bot.analisis_repo, "verificar_consenso_cache",
        lambda db, partido_id: {"cache_consenso_hit": True, "texto_consenso": "En cache", "job_en_vuelo": False},
    )
    monkeypatch.setattr(
        laplace_bot.usuarios_repo, "verificar_limite",
        lambda db, user_id, plan: {"puede": True, "usados": 0, "limite": 10},
    )
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", lambda db, **kwargs: {"job_id": "job_ref"})
    fondo_mock = AsyncMock()
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", fondo_mock)

    update = _update_callback("REFRESH_20260101_m9", user_id="909")
    _run(laplace_bot.callback_predict(update, _context()))

    texto = _texto_respuesta(update.callback_query.message.reply_html)
    assert "Analizando partido" in texto
    fondo_mock.assert_awaited_once()
