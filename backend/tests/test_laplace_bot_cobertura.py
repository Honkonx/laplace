"""Bot deportivo de Telegram (`laplace_bot.py`): comandos y callbacks no cubiertos por `test_laplace_bot.py`,
con actualizaciones simuladas (usuario normal y administrador). Sin red, sin el token real y con SQLite en memoria."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401
from backend.api.bot import laplace_bot
from backend.api.bot import laplace_bot_admin, laplace_bot_callbacks, laplace_bot_usuario

# `SessionLocal` ya no vive solo en `laplace_bot`: cada módulo que abre sesión tiene su propio nombre.
_MODULOS_CON_SESION = (laplace_bot_usuario, laplace_bot_callbacks, laplace_bot_admin)
from backend.api.core.config import settings
from backend.api.db.session import Base
from backend.api.models.auditoria import AccionAdminAuditoria
from backend.api.models.usuarios import Usuario

ADMIN_ID = "111"


@pytest.fixture()
def sesion_bot(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    for modulo in _MODULOS_CON_SESION:
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    return fabrica


@pytest.fixture(autouse=True)
def _admin_declarado(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", ADMIN_ID)


@pytest.fixture()
def responder_callback(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", mock)
    return mock


def _update(user_id: str = "123", first_name: str = "Jhos") -> MagicMock:
    update = MagicMock()
    update.effective_user.id = int(user_id)
    update.effective_user.first_name = first_name
    update.effective_chat.id = int(user_id)
    update.message.reply_html = AsyncMock()
    return update


def _callback(data: str, user_id: str = "900") -> MagicMock:
    update = _update(user_id)
    update.callback_query.id = "cbq"
    update.callback_query.data = data
    update.callback_query.message.reply_html = AsyncMock()
    return update


def _ctx(*args: str) -> MagicMock:
    context = MagicMock()
    context.args = list(args)
    context.application.bot_data = {"http_client": MagicMock()}
    return context


def _run(coro):
    async def runner():
        resultado = await coro
        pendientes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pendientes:
            await asyncio.gather(*pendientes, return_exceptions=True)
        return resultado

    return asyncio.run(runner())


def _texto(mock) -> str:
    return mock.call_args[0][0]


def _stages(*ligas):
    """ligas: (nombre, [(id, estado, local, visitante), ...])"""
    return [
        {"Snm": nombre, "Events": [{"Eid": eid, "Eps": estado, "T1": [{"Nm": local}], "T2": [{"Nm": visitante}]} for eid, estado, local, visitante in eventos]}
        for nombre, eventos in ligas
    ]


# --------------------------------------------------------------------------------------------
# Comandos informativos
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("plan,fragmento", [("free", "Solo estadístico"), ("pro", "6 análisis IA/día"), ("max", "Ilimitado")])
def test_start_muestra_el_plan_y_registra_al_usuario(sesion_bot, plan, fragmento):
    with sesion_bot() as db:
        db.add(Usuario(device_id="321", activo=1, plan=plan, creado_en="2026-01-01 00:00:00"))
        db.commit()
    update = _update("321", "Ana")
    _run(laplace_bot.cmd_start(update, _ctx()))
    texto = _texto(update.message.reply_html)
    assert "Ana" in texto and plan.upper() in texto and fragmento in texto


def test_start_de_un_usuario_nuevo_lo_crea_como_free(sesion_bot):
    update = _update("555")
    _run(laplace_bot.cmd_start(update, _ctx()))
    assert "FREE" in _texto(update.message.reply_html)
    with sesion_bot() as db:
        assert db.query(Usuario).filter(Usuario.device_id == "555").count() == 1


def test_ayuda_lista_los_comandos_y_no_previsualiza_enlaces():
    update = _update()
    _run(laplace_bot.cmd_ayuda(update, _ctx()))
    assert "/juegos" in _texto(update.message.reply_html) and update.message.reply_html.call_args.kwargs["disable_web_page_preview"] is True


def test_mi_id_devuelve_el_id_del_solicitante():
    update = _update("98765")
    _run(laplace_bot.cmd_mi_id(update, _ctx()))
    assert "<code>98765</code>" in _texto(update.message.reply_html)


def test_juegos_ofrece_hoy_y_manana():
    update = _update()
    _run(laplace_bot.cmd_juegos(update, _ctx()))
    botones = update.message.reply_html.call_args.kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in botones] == ["DAY_TODAY", "DAY_TOMORROW"]


def test_texto_hoy_sin_partidos_y_con_cobertura_parcial_escapando_html():
    assert "no hay partidos que pueda pronosticar" in laplace_bot._texto_hoy({"partidos": []})
    texto = laplace_bot._texto_hoy({"partidos": [
        {"liga": "Liga <X>", "hora_chile": "20:00", "local": "A & B", "visitante": "C", "cobertura": "completa"},
        {"liga": None, "hora_chile": None, "local": "D", "visitante": "E", "cobertura": "parcial"},
        {"liga": "Liga <X>", "hora_chile": "18:00", "local": None, "visitante": "G", "cobertura": "completa"},
    ]})
    assert "Liga &lt;X&gt;" in texto and "A &amp; B" in texto and "Otras ligas" in texto
    assert "~--:-- D vs E" in texto and "18:00  vs G" in texto
    assert texto.index("18:00") < texto.index("20:00")  # ordenados por hora dentro de la liga


def test_hoy_lee_los_pronosticables_del_dia_de_chile(sesion_bot, monkeypatch):
    from backend.api.services import pronosticables

    fechas = []

    def falso(db, fecha_bd):
        fechas.append(fecha_bd)
        return {"partidos": [{"liga": "Premier", "hora_chile": "10:00", "local": "A", "visitante": "B", "cobertura": "completa"}]}

    monkeypatch.setattr(pronosticables, "listar_pronosticables", falso)
    update = _update()
    _run(laplace_bot.cmd_hoy(update, _ctx()))
    assert len(fechas) == 1 and len(fechas[0]) == 10 and "A vs B" in _texto(update.message.reply_html)


def test_ligas_lista_el_catalogo_con_su_total():
    update = _update()
    _run(laplace_bot.cmd_ligas(update, _ctx()))
    texto = _texto(update.message.reply_html)
    assert "Ligas con cobertura" in texto and "Total de entradas" in texto


def test_stats_muestra_winrate_real_o_sin_datos(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_stats", lambda db: {"predicciones": {"alta": 4, "media": 3, "baja": 1}})
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_stats_aciertos", lambda db, dias: {"pick_final": {"winrate": 58.3, "aciertos": 7, "evaluados": 12}})
    con_datos = _update()
    _run(laplace_bot.cmd_stats(con_datos, _ctx()))
    texto = _texto(con_datos.message.reply_html)
    assert "58.3% (7/12)" in texto and "Alta: 4" in texto and "Media: 3" in texto and "Baja: 1" in texto
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_stats", lambda db: {})
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_stats_aciertos", lambda db, dias: {})
    sin_datos = _update()
    _run(laplace_bot.cmd_stats(sin_datos, _ctx()))
    assert "Sin datos" in _texto(sin_datos.message.reply_html) and "Alta: 0" in _texto(sin_datos.message.reply_html)


def test_top_sin_picks_explica_cuando_publica_el_canal(sesion_bot, monkeypatch):
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_top_picks_app", lambda db, usuario, fecha: {"canal": []})
    update = _update()
    _run(laplace_bot.cmd_top(update, _ctx()))
    assert "No hay Top Picks disponibles" in _texto(update.message.reply_html)


def test_top_muestra_como_maximo_tres_picks_con_medallas(sesion_bot, monkeypatch):
    picks = [
        {"local": f"L{i}", "visitante": f"V{i}", "liga": "Liga", "pick": "Local", "confianza": "ALTA" if i == 0 else None, "score": 77 if i == 0 else None, "hora": "15:00" if i == 0 else None}
        for i in range(5)
    ]
    monkeypatch.setattr(laplace_bot.analisis_repo, "leer_top_picks_app", lambda db, usuario, fecha: {"canal": picks})
    update = _update()
    _run(laplace_bot.cmd_top(update, _ctx()))
    texto = _texto(update.message.reply_html)
    assert "🥇" in texto and "🥉" in texto and "L2" in texto and "L3" not in texto
    assert "ALTA" in texto and "(77/100)" in texto and "15:00 (Chile)" in texto


# --------------------------------------------------------------------------------------------
# Callbacks del menú de ligas
# --------------------------------------------------------------------------------------------

def test_dia_hoy_ofrece_las_ligas_con_partidos_y_marca_las_cubiertas(sesion_bot, responder_callback, monkeypatch):
    stages = _stages(("Premier League", [("e1", "NS", "Arsenal", "Chelsea"), ("e2", "FT", "A", "B")]), ("Liga Distrital", [("e3", "NS", "C", "D")]))
    cascada = AsyncMock(return_value=(stages, "bd"))
    monkeypatch.setattr(laplace_bot.gateway, "obtener_fixtures_cascada", cascada)
    monkeypatch.setattr(laplace_bot.ligas_bot, "_evento_cubierto", lambda stage, ev: stage.get("Snm") == "Premier League")
    update = _callback("DAY_TODAY")
    _run(laplace_bot.callback_dia(update, _ctx()))
    texto, kwargs = update.callback_query.message.reply_html.call_args[0][0], update.callback_query.message.reply_html.call_args.kwargs
    botones = [b for fila in kwargs["reply_markup"].inline_keyboard for b in fila]
    assert "Hoy" in texto and len(botones) == 1  # la liga excluida no aparece
    assert botones[0].text.endswith("(1) ✅") and botones[0].callback_data.endswith("_premier-league")
    assert responder_callback.await_count == 1


def test_dia_manana_usa_la_fecha_siguiente_y_avisa_si_no_hay_ligas(sesion_bot, responder_callback, monkeypatch):
    fechas = []

    async def cascada(db, client, fecha):
        fechas.append(fecha)
        return [], "bd"

    monkeypatch.setattr(laplace_bot.gateway, "obtener_fixtures_cascada", cascada)
    hoy, manana = _callback("DAY_TODAY"), _callback("DAY_TOMORROW")
    _run(laplace_bot.callback_dia(hoy, _ctx()))
    _run(laplace_bot.callback_dia(manana, _ctx()))
    assert fechas[0] < fechas[1] and len(fechas[0]) == 8
    assert "No hay ligas con partidos para mañana" in _texto(manana.callback_query.message.reply_html)


def test_liga_lista_solo_los_no_iniciados_de_esa_liga_con_los_cubiertos_primero(sesion_bot, responder_callback, monkeypatch):
    stages = _stages(
        ("Premier League", [("e1", "NS", "Arsenal", "Chelsea"), ("e2", "FT", "Liverpool", "Everton"), ("e3", "NS", "Spurs", "Wolves")]),
        ("LaLiga", [("e4", "NS", "Real", "Sevilla")]),
    )
    monkeypatch.setattr(laplace_bot.gateway, "obtener_fixtures_cascada", AsyncMock(return_value=(stages, "bd")))
    monkeypatch.setattr(laplace_bot.ligas_bot, "_evento_cubierto", lambda stage, ev: ev.get("Eid") == "e3")
    update = _callback("LEAGUE_20261007_premier-league")
    _run(laplace_bot.callback_liga(update, _ctx()))
    botones = [b for fila in update.callback_query.message.reply_html.call_args.kwargs["reply_markup"].inline_keyboard for b in fila]
    assert [b.callback_data for b in botones] == ["PREDICT_20261007_e3", "PREDICT_20261007_e1"]
    assert botones[0].text.endswith("✅") and not botones[1].text.endswith("✅")


def test_liga_sin_partidos_avisa_y_vuelve_a_juegos(sesion_bot, responder_callback, monkeypatch):
    monkeypatch.setattr(laplace_bot.gateway, "obtener_fixtures_cascada", AsyncMock(return_value=(_stages(("LaLiga", [("e4", "NS", "R", "S")])), "bd")))
    update = _callback("LEAGUE_20261007_serie-z")
    _run(laplace_bot.callback_liga(update, _ctx()))
    assert "No se encontraron partidos para <b>serie-z</b>" in _texto(update.callback_query.message.reply_html)


def test_predict_con_cache_ofrece_recalcular_sin_crear_job(sesion_bot, responder_callback, monkeypatch):
    monkeypatch.setattr(laplace_bot.analisis_repo, "verificar_consenso_cache", lambda db, partido_id: {"cache_consenso_hit": True, "texto_consenso": "Resultado en caché"})
    crear = MagicMock()
    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", crear)
    update = _callback("PREDICT_20261007_m1")
    _run(laplace_bot.callback_predict(update, _ctx()))
    assert _texto(update.callback_query.message.reply_html) == "Resultado en caché"
    botones = update.callback_query.message.reply_html.call_args.kwargs["reply_markup"].inline_keyboard[0]
    assert botones[0].callback_data == "REFRESH_20261007_m1" and botones[1].callback_data == "DAY_TODAY"
    crear.assert_not_called()


def test_predict_de_un_plan_de_pago_anuncia_el_analisis_con_ia(sesion_bot, responder_callback, monkeypatch):
    with sesion_bot() as db:
        db.add(Usuario(device_id="900", activo=1, plan="pro", creado_en="2026-01-01 00:00:00"))
        db.commit()
    monkeypatch.setattr(laplace_bot.analisis_repo, "verificar_consenso_cache", lambda db, partido_id: {})
    monkeypatch.setattr(laplace_bot.usuarios_repo, "verificar_limite", lambda db, user_id, plan: {"puede": True, "usados": 0, "limite": 6})
    pedidos = {}

    def crear(db, **kwargs):
        pedidos.update(kwargs)
        return {"job_id": "j1"}

    monkeypatch.setattr(laplace_bot.jobs_repo, "crear_job", crear)
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", AsyncMock())
    update = _callback("PREDICT_20261007_m7", user_id="900")
    _run(laplace_bot.callback_predict(update, _ctx()))
    assert "Análisis IA" in _texto(update.callback_query.message.reply_html)
    assert pedidos["match_id"] == "m7" and pedidos["fecha"] == "20261007" and pedidos["plan"] == "pro" and pedidos["user_id"] == "900"


def test_el_trabajo_en_fondo_delega_en_analisis_completo(sesion_bot, monkeypatch):
    procesar = AsyncMock()
    monkeypatch.setattr(laplace_bot.analisis_completo, "procesar_job", procesar)
    cliente = MagicMock()
    _run(laplace_bot._procesar_job_en_fondo(cliente, "job-9"))
    assert procesar.await_args.args[1:] == (cliente, "job-9")


def test_voto_que_no_se_pudo_guardar_avisa_con_alerta(sesion_bot, responder_callback, monkeypatch):
    monkeypatch.setattr(laplace_bot.predicciones_usuario_repo, "registrar_voto", lambda db, **kwargs: {"ok": False})
    update = _callback("VOTE_m1_L")
    _run(laplace_bot.callback_voto(update, _ctx()))
    assert responder_callback.await_args.args[2] == "⚠️ No se pudo registrar el voto." and responder_callback.await_args.kwargs["show_alert"] is True
    update.callback_query.message.reply_html.assert_not_called()


def test_voto_con_formato_invalido_se_rechaza(sesion_bot, responder_callback):
    for dato in ("VOTE_L", "VOTE__L", "VOTE_m1_X"):
        update = _callback(dato)
        _run(laplace_bot.callback_voto(update, _ctx()))
        assert "Voto inválido" in responder_callback.await_args.args[2]


# --------------------------------------------------------------------------------------------
# Confirmación de Top Picks (botones pub_/nopub_)
# --------------------------------------------------------------------------------------------

def test_confirmar_picks_publica_o_descarta_segun_el_boton(sesion_bot, responder_callback, monkeypatch):
    fechas = []
    monkeypatch.setattr(laplace_bot.top_picks, "sacar_pendiente_confirmacion", lambda fecha: fechas.append(fecha) or {"picks": []})
    confirmar = AsyncMock(return_value="Mensaje de cierre")
    monkeypatch.setattr(laplace_bot.top_picks, "confirmar_publicacion", confirmar)
    publicar, descartar = _callback("pub_2026-10-07"), _callback("nopub_2026-10-07")
    _run(laplace_bot.callback_confirmar_picks(publicar, _ctx()))
    _run(laplace_bot.callback_confirmar_picks(descartar, _ctx()))
    assert fechas == ["2026-10-07", "2026-10-07"]
    assert [c.args[3] for c in confirmar.await_args_list] == [True, False]
    assert _texto(publicar.callback_query.message.reply_html) == "Mensaje de cierre"


def test_confirmar_picks_expirados_avisa_y_no_publica(sesion_bot, responder_callback, monkeypatch):
    monkeypatch.setattr(laplace_bot.top_picks, "sacar_pendiente_confirmacion", lambda fecha: None)
    confirmar = AsyncMock()
    monkeypatch.setattr(laplace_bot.top_picks, "confirmar_publicacion", confirmar)
    update = _callback("pub_2026-10-07")
    _run(laplace_bot.callback_confirmar_picks(update, _ctx()))
    assert "Ya no hay picks pendientes" in _texto(update.callback_query.message.reply_html)
    confirmar.assert_not_called()


# --------------------------------------------------------------------------------------------
# Administración: códigos y usuarios
# --------------------------------------------------------------------------------------------

def test_generar_codigos_valida_la_cantidad_de_argumentos_y_el_plan(sesion_bot):
    pocos = _update(ADMIN_ID)
    _run(laplace_bot.cmd_generarcodigos(pocos, _ctx("5", "pro")))
    assert "Uso: /generarcodigos" in _texto(pocos.message.reply_html)
    plan_malo = _update(ADMIN_ID)
    _run(laplace_bot.cmd_generarcodigos(plan_malo, _ctx("2", "oro", "30")))
    assert _texto(plan_malo.message.reply_html).startswith("⚠️")
    with sesion_bot() as db:
        assert db.query(AccionAdminAuditoria).count() == 0


def test_listar_codigos_exige_admin_y_distingue_vacio_de_con_codigos(sesion_bot):
    intruso = _update("999")
    _run(laplace_bot.cmd_listarcodigos(intruso, _ctx()))
    assert "No autorizado" in _texto(intruso.message.reply_html)
    vacio = _update(ADMIN_ID)
    _run(laplace_bot.cmd_listarcodigos(vacio, _ctx()))
    assert "No hay códigos (disponibles)" in _texto(vacio.message.reply_html)
    _run(laplace_bot.cmd_generarcodigos(_update(ADMIN_ID), _ctx("2", "max", "7")))
    lista = _update(ADMIN_ID)
    _run(laplace_bot.cmd_listarcodigos(lista, _ctx()))
    texto = _texto(lista.message.reply_html)
    assert "2 total" in texto and "MAX 7d" in texto
    usados = _update(ADMIN_ID)
    _run(laplace_bot.cmd_listarcodigos(usados, _ctx("usados")))
    assert "No hay códigos (usados)" in _texto(usados.message.reply_html)


def test_gestionar_usuario_valida_argumentos(sesion_bot):
    update = _update(ADMIN_ID)
    _run(laplace_bot.cmd_gestionarusuario(update, _ctx("solo-uno")))
    assert "Uso: /gestionarusuario" in _texto(update.message.reply_html)


def test_gestionar_usuario_asigna_rol_y_deja_rastro(sesion_bot):
    with sesion_bot() as db:
        db.add(Usuario(device_id="u_rol", activo=1, plan="free", creado_en="2026-01-01 00:00:00"))
        db.commit()
    update = _update(ADMIN_ID)
    _run(laplace_bot.cmd_gestionarusuario(update, _ctx("u_rol", "rol:agente")))
    assert _texto(update.message.reply_html).startswith("✅")
    with sesion_bot() as db:
        assert db.query(Usuario).filter(Usuario.device_id == "u_rol").one().rol == "agente"


def test_gestionar_usuario_rechaza_un_rol_invalido_o_un_usuario_inexistente(sesion_bot):
    with sesion_bot() as db:
        db.add(Usuario(device_id="u_rol2", activo=1, plan="free", creado_en="2026-01-01 00:00:00"))
        db.commit()
    invalido = _update(ADMIN_ID)
    _run(laplace_bot.cmd_gestionarusuario(invalido, _ctx("u_rol2", "rol:superheroe")))
    assert _texto(invalido.message.reply_html).startswith("⚠️")
    with sesion_bot() as db:
        assert db.query(Usuario).filter(Usuario.device_id == "u_rol2").one().rol != "superheroe"
    inexistente = _update(ADMIN_ID)
    _run(laplace_bot.cmd_gestionarusuario(inexistente, _ctx("nadie", "rol:admin")))
    assert _texto(inexistente.message.reply_html).startswith("⚠️")


def test_un_usuario_normal_no_puede_asignar_roles(sesion_bot):
    with sesion_bot() as db:
        db.add(Usuario(device_id="victima", activo=1, plan="free", creado_en="2026-01-01 00:00:00"))
        db.commit()
    intruso = _update("999")
    _run(laplace_bot.cmd_gestionarusuario(intruso, _ctx("victima", "rol:admin")))
    assert "No autorizado" in _texto(intruso.message.reply_html)
    with sesion_bot() as db:
        assert db.query(Usuario).filter(Usuario.device_id == "victima").one().rol != "admin"


# --------------------------------------------------------------------------------------------
# /vincular, /favoritos y fábrica
# --------------------------------------------------------------------------------------------

def test_vincular_sin_argumentos_explica_el_uso(sesion_bot):
    update = _update()
    _run(laplace_bot.cmd_vincular(update, _ctx("solo-usuario")))
    assert "Vincular cuenta Web / App" in _texto(update.message.reply_html)


def test_vincular_con_credenciales_malas_no_vincula_y_registra_el_intento(sesion_bot, monkeypatch):
    from backend.api.services.auth_password import hashear_password

    with sesion_bot() as db:
        laplace_bot.usuarios_repo.crear_usuario_credenciales(db, "cuentaweb", hashear_password("claveCorrecta1"), "web", "2026-09-25")
    intentos = []
    monkeypatch.setattr(laplace_bot.auditoria_repo, "registrar_intento_login_fallido", lambda db, username: intentos.append(username))
    for usuario, clave in (("cuentaweb", "claveIncorrecta"), ("noexiste", "cualquiera")):
        update = _update("4100")
        _run(laplace_bot.cmd_vincular(update, _ctx(usuario, clave)))
        assert "Usuario o contraseña incorrectos" in _texto(update.message.reply_html)
    assert intentos == ["cuentaweb", "noexiste"]
    with sesion_bot() as db:
        assert db.query(Usuario).filter(Usuario.device_id == "4100").one().plan == "free"


def test_favoritos_con_accion_invalida_muestra_el_uso(sesion_bot):
    for args in (("agregar",), ("borrar", "LaLiga")):
        update = _update("4200")
        _run(laplace_bot.cmd_favoritos(update, _ctx(*args)))
        assert "Uso:" in _texto(update.message.reply_html)


def test_construir_app_registra_comandos_callbacks_y_el_fallback_al_final(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:token-falso-de-prueba")
    app = laplace_bot.construir_app()
    handlers = app.handlers[0]
    comandos = {c for h in handlers for c in getattr(h, "commands", [])}
    assert {"start", "ayuda", "mi_id", "juegos", "ligas", "stats", "hoy", "top", "encuesta", "generarcodigos", "listarcodigos",
            "gestionarusuario", "misplanes", "favoritos", "vincular"} <= comandos
    patrones = {h.pattern.pattern for h in handlers if type(h).__name__ == "CallbackQueryHandler"}
    assert patrones == {r"^DAY_", r"^LEAGUE_", r"^(PREDICT|REFRESH)_", r"^VOTE_", r"^(pub|nopub)_"}
    assert type(handlers[-1]).__name__ == "MessageHandler"  # el fallback de comando desconocido va último


# ---------- memoria mínima del bot (MB-30…33): comandos y personalización ----------
def test_privacidad_equipos_y_olvidame_de_punta_a_punta(sesion_bot):
    from backend.api.db import bot_memoria_repo as memoria

    u = _update("7001")
    _run(laplace_bot.cmd_privacidad(u, _ctx()))
    assert "no aceptado" in _texto(u.message.reply_html) and "Nunca cambia un pronóstico" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_equipos(u, _ctx("agregar", "Arsenal")))
    assert "Escribe" in _texto(u.message.reply_html) or "privacidad" in _texto(u.message.reply_html).lower()  # sin consentimiento no guarda
    u = _update("7001")
    _run(laplace_bot.cmd_privacidad(u, _ctx("aceptar")))
    assert "Listo" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_equipos(u, _ctx("agregar", "Arsenal")))
    assert "agregado" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_equipos(u, _ctx()))
    assert "Arsenal" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_equipos(u, _ctx("quitar", "Arsenal")))
    assert "quitado" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_equipos(u, _ctx()))
    assert "No tienes equipos" in _texto(u.message.reply_html)
    u = _update("7001")
    _run(laplace_bot.cmd_olvidame(u, _ctx()))
    assert "confirmo" in _texto(u.message.reply_html)
    with sesion_bot() as db:
        assert memoria.tiene_consentimiento(db, "7001")  # sin «confirmo» no se borra nada
    u = _update("7001")
    _run(laplace_bot.cmd_olvidame(u, _ctx("confirmo")))
    assert "borré" in _texto(u.message.reply_html)
    with sesion_bot() as db:
        assert not memoria.tiene_consentimiento(db, "7001")
    u = _update("7001")
    _run(laplace_bot.cmd_privacidad(u, _ctx("revocar")))
    assert "retirado" in _texto(u.message.reply_html)


def test_la_personalizacion_ordena_ligas_y_partidos_solo_con_consentimiento(sesion_bot, monkeypatch):
    from backend.api.bot import laplace_bot_callbacks as cb
    from backend.api.db import bot_memoria_repo as memoria, usuarios_repo

    monkeypatch.setattr(cb, "SessionLocal", sesion_bot)
    ligas = [{"nombre": "Serie A", "partidos": 2}, {"nombre": "Premier League", "partidos": 5}]
    partidos = [{"local": "Betis", "visitante": "Sevilla"}, {"local": "Arsenal", "visitante": "Chelsea"}]
    u = _update("7002")
    assert cb._ordenar_ligas_favoritas(u, ligas) == ligas and cb._ordenar_partidos_favoritos(u, partidos) == partidos  # sin consentimiento, igual
    with sesion_bot() as db:
        db.add(Usuario(device_id="7002", activo=1, plan="free", creado_en="2026-11-01"))
        db.commit()
        memoria.aceptar(db, "7002")
        usuarios_repo.agregar_favorito_liga(db, "7002", "Premier League")
        memoria.agregar_equipo(db, "7002", "Chelsea")
    assert cb._ordenar_ligas_favoritas(u, ligas)[0]["nombre"] == "Premier League"
    assert cb._ordenar_partidos_favoritos(u, partidos)[0]["local"] == "Arsenal" and len(cb._ordenar_partidos_favoritos(u, partidos)) == 2


def test_si_la_base_falla_la_personalizacion_muestra_la_lista_normal(monkeypatch):
    from backend.api.bot import laplace_bot_callbacks as cb

    def rota():
        raise RuntimeError("base caída")

    monkeypatch.setattr(cb, "SessionLocal", rota)
    ligas = [{"nombre": "A"}, {"nombre": "B"}]
    assert cb._ordenar_ligas_favoritas(_update("7003"), ligas) == ligas
