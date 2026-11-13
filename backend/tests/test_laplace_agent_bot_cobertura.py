"""Bot de Telegram del agente (`laplace_agent_bot.py`): cada comando con actualizaciones simuladas, como
usuario normal y como administrador. Sin red, sin el token real de Telegram y sin la BD real."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401
from backend.api.bot import laplace_agent_bot as bot
from backend.api.bot import laplace_agent_bot_admin, laplace_agent_bot_comandos, laplace_agent_bot_nucleo as nucleo

# `SessionLocal` vive ahora en cada módulo que abre sesión.
_MODULOS_CON_SESION = (nucleo, laplace_agent_bot_comandos, laplace_agent_bot_admin)
from backend.api.core.config import settings
from backend.api.db.session import Base
from backend.api.models.agent_runtime import AgentMemory, AgentTask
from backend.api.services import agent_guard
from backend.api.services.agent_approvals import crear_aprobacion
from backend.api.services.agent_guard import LimiteExcedido

ADMIN_ID, USUARIO_ID = 1, 42
_CLIENTE_REAL = httpx.AsyncClient


def _update(user_id: int = USUARIO_ID, texto: str = "hola", *, sin_chat: bool = False, falla_al_responder: bool = False):
    respuestas: list[str] = []

    async def reply_text(mensaje):
        if falla_al_responder:
            raise RuntimeError("telegram caído")
        respuestas.append(mensaje)

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id), effective_chat=None if sin_chat else SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(text=texto, reply_text=reply_text), respuestas=respuestas,
    )


def _ctx(*args):
    return SimpleNamespace(args=list(args))


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setattr(type(settings), "admin_ids", property(lambda self: [str(ADMIN_ID)]))
    for nombre in ("AGENT_TELEGRAM_ALLOWED_IDS", "AGENT_TELEGRAM_BLOCKED_IDS", "AGENT_TELEGRAM_RATE_PER_MIN"):
        monkeypatch.delenv(nombre, raising=False)
    agent_guard.resetear_contadores()
    agent_guard._VENTANA_CHAT.clear()
    yield
    agent_guard.resetear_contadores()
    agent_guard._VENTANA_CHAT.clear()


@pytest.fixture()
def sesion(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine)
    for modulo in _MODULOS_CON_SESION:
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    return fabrica


@pytest.fixture()
def herramienta(monkeypatch):
    """`_herramienta` falsa: registra (nombre, argumentos, aprobado) y devuelve lo que el test programe."""
    llamadas: list[tuple] = []
    respuestas: dict = {}

    async def falso(update, nombre, argumentos, *, aprobado=False):
        llamadas.append((nombre, argumentos, aprobado))
        valor = respuestas.get(nombre, {})
        if isinstance(valor, Exception):
            raise valor
        return valor

    monkeypatch.setattr(nucleo, "_herramienta", falso)
    return SimpleNamespace(llamadas=llamadas, respuestas=respuestas)


# --------------------------------------------------------------------------------------------
# Acceso: protegido / solo_admin
# --------------------------------------------------------------------------------------------

def test_protegido_ignora_actualizaciones_sin_usuario_o_sin_mensaje():
    llamados = []

    @bot.protegido
    async def handler(update, context):
        llamados.append(1)

    sin_usuario = _update()
    sin_usuario.effective_user = None
    sin_mensaje = _update()
    sin_mensaje.effective_message = None
    _run(handler(sin_usuario, None))
    _run(handler(sin_mensaje, None))
    assert llamados == [] and sin_usuario.respuestas == []


def test_usuario_vetado_no_entra_pero_el_admin_vetado_si(monkeypatch):
    monkeypatch.setenv("AGENT_TELEGRAM_BLOCKED_IDS", f"{USUARIO_ID},{ADMIN_ID}")
    vetado, admin = _update(USUARIO_ID), _update(ADMIN_ID)
    _run(bot.cmd_start(vetado, None))
    _run(bot.cmd_start(admin, None))
    assert vetado.respuestas == [bot.MSG_NO_AUTORIZADO]
    assert "Laplace" in admin.respuestas[0]


def test_modo_restringido_solo_deja_pasar_a_los_permitidos_y_al_admin(monkeypatch):
    monkeypatch.setenv("AGENT_TELEGRAM_ALLOWED_IDS", "7")
    for user_id, entra in ((7, True), (8, False), (ADMIN_ID, True)):
        agent_guard._VENTANA_CHAT.clear()
        u = _update(user_id)
        _run(bot.cmd_start(u, None))
        assert (u.respuestas != [bot.MSG_NO_AUTORIZADO]) is entra, user_id


def test_esta_autorizado_sin_usuario_es_falso():
    u = _update()
    u.effective_user = None
    assert bot._esta_autorizado(u) is False and bot._es_admin(u) is False and bot._id_usuario(u) == ""


def test_rate_limit_por_chat_avisa_y_no_ejecuta(monkeypatch):
    monkeypatch.setenv("AGENT_TELEGRAM_RATE_PER_MIN", "1")
    u = _update()
    _run(bot.cmd_start(u, None))
    _run(bot.cmd_start(u, None))
    assert len(u.respuestas) == 2 and u.respuestas[1] == bot.MSG_LIMITE


def test_sin_chat_el_limite_se_cuenta_por_usuario(monkeypatch):
    monkeypatch.setenv("AGENT_TELEGRAM_RATE_PER_MIN", "1")
    u = _update(sin_chat=True)
    _run(bot.cmd_start(u, None))
    _run(bot.cmd_start(u, None))
    assert u.respuestas[-1] == bot.MSG_LIMITE


def test_un_error_en_el_handler_se_contiene_y_se_avisa():
    @bot.protegido
    async def roto(update, context):
        raise ValueError("bug")

    u = _update()
    _run(roto(u, None))
    assert u.respuestas == [bot.MSG_ERROR]


def test_si_ni_avisar_del_error_funciona_tampoco_se_propaga():
    @bot.protegido
    async def roto(update, context):
        raise ValueError("bug")

    _run(roto(_update(falla_al_responder=True), None))  # no debe lanzar


# --------------------------------------------------------------------------------------------
# Utilidades de formato
# --------------------------------------------------------------------------------------------

def test_enviar_parte_los_mensajes_largos_por_saltos_de_linea():
    u = _update()
    lineas = [("x" * 99) for _ in range(120)]
    _run(bot._enviar(u, "\n".join(lineas)))
    assert len(u.respuestas) >= 3 and all(len(m) <= bot.MAX_MENSAJE for m in u.respuestas)
    assert "".join(u.respuestas).replace("\n", "") == "".join(lineas)


def test_enviar_corta_en_seco_si_no_hay_saltos_de_linea_y_rellena_vacios():
    u = _update()
    _run(bot._enviar(u, "y" * (bot.MAX_MENSAJE + 10)))
    assert [len(m) for m in u.respuestas] == [bot.MAX_MENSAJE, 10]
    vacio = _update()
    _run(bot._enviar(vacio, "   "))
    assert vacio.respuestas == ["Sin contenido."]


def test_fecha_desde_acepta_hoy_manana_iso_y_cae_en_hoy_con_basura():
    hoy = bot._fecha_desde("hoy")
    assert bot._fecha_desde(None) == hoy and bot._fecha_desde("cualquier cosa") == hoy
    assert bot._fecha_desde("2026-12-31") == "2026-12-31"
    assert bot._fecha_desde("Mañana") == bot._fecha_desde("tomorrow") == bot._fecha_desde("manana") > hoy


def test_es_token_fecha():
    assert all(bot._es_token_fecha(t) for t in ("hoy", "Mañana", "today", "2026-10-07"))
    assert not any(bot._es_token_fecha(t) for t in ("river", "2026/10/07"))


def test_hora_corta_desde_formato_compacto_iso_o_nada():
    assert bot._hora_corta("20261007183000") == "18:30"
    assert bot._hora_corta("202610071830") == "18:30"
    assert bot._hora_corta("2026-10-07T21:05:00Z") == "21:05"
    assert bot._hora_corta("sin hora") == "" and bot._hora_corta(None) == ""


def test_separar_equipos_y_coincidencia():
    assert bot._separar_equipos("River vs Boca") == ("River", "Boca")
    assert bot._separar_equipos("River contra Boca Juniors") == ("River", "Boca Juniors")
    assert bot._separar_equipos("Real Madrid - Barcelona") == ("Real Madrid", "Barcelona")
    assert bot._separar_equipos("River") is None and bot._separar_equipos("vs Boca") is None
    assert bot._coincide("boca", "Boca Juniors") and bot._coincide("Boca Juniors FC", "boca juniors")
    assert not bot._coincide("", "Boca")


def test_un_nombre_de_partido_vacio_no_deberia_coincidir_con_nada():
    assert bot._coincide("river", "") is False


def test_formatear_prediccion_sin_pick_lista_motivos_y_referencia():
    texto = bot.formatear_prediccion(
        {"local": "A", "visitante": "B", "liga": "Liga X"},
        {"pick": None, "motivos_sin_pronostico": ["sin cuotas", "sin historial"],
         "referencia_tasa_base": {"nivel": "liga", "pct_local": 44, "pct_empate": 26, "pct_visitante": 30}},
    )
    assert "Liga X" in texto and "• sin cuotas" in texto and "esta liga" in texto and "No distingue a estos dos equipos" in texto
    general = bot.formatear_prediccion({}, {"referencia_tasa_base": {"nivel": "global", "pct_local": 40, "pct_empate": 25, "pct_visitante": 35}})
    assert "promedio general" in general


def test_formatear_prediccion_con_pick_sin_probabilidades_ni_tasa_base():
    texto = bot.formatear_prediccion({"local": "A", "visitante": "B"}, {"pick": "Empate"})
    assert "Empate" in texto and "n/d" in texto and bot.AVISO_ESTIMACION in texto and "Probabilidad estimada" not in texto


# --------------------------------------------------------------------------------------------
# Comandos para todos
# --------------------------------------------------------------------------------------------

def test_start_y_ayuda_para_usuario_y_admin():
    u = _update()
    _run(bot.cmd_start(u, None))
    assert "No soy una casa de apuestas" in u.respuestas[0]
    normal, admin = _update(USUARIO_ID), _update(ADMIN_ID)
    _run(bot.cmd_ayuda(normal, None))
    _run(bot.cmd_ayuda(admin, None))
    assert "/predecir" in normal.respuestas[0] and "Administración" not in normal.respuestas[0] and "/publicar" not in normal.respuestas[0]
    assert "Administración" in admin.respuestas[0] and "/publicar" in admin.respuestas[0]


def test_mensaje_libre_vacio_pide_una_consulta_y_con_texto_consulta_al_agente(monkeypatch):
    consultas = []

    async def falso(update, texto, usar_ia):
        consultas.append((texto, usar_ia))

    monkeypatch.setattr(nucleo, "_consultar_agente", falso)
    vacio = _update(texto="   ")
    _run(bot._responder(vacio, None))
    assert "Escribe una consulta" in vacio.respuestas[0]
    _run(bot._responder(_update(texto="hola " + "x" * 5000), None))
    assert consultas[0][1] is False and len(consultas[0][0]) == 4000


def test_ia_sin_texto_explica_el_uso_y_con_texto_usa_ia(monkeypatch):
    consultas = []

    async def falso(update, texto, usar_ia):
        consultas.append((texto, usar_ia))

    monkeypatch.setattr(nucleo, "_consultar_agente", falso)
    u = _update()
    _run(bot.cmd_ia(u, _ctx()))
    assert u.respuestas == ["Uso: /ia <consulta dentro del alcance de Laplace>"] and consultas == []
    _run(bot.cmd_ia(_update(), _ctx("quién", "gana")))
    assert consultas == [("quién gana", True)]


def test_consultar_agente_responde_con_el_texto_del_runtime(monkeypatch, sesion):
    vistos = {}

    async def procesar(db, **kwargs):
        vistos.update(kwargs)
        return {"respuesta": "listo"}

    monkeypatch.setattr(nucleo, "sincronizar_conocimiento_json", lambda db: 0)
    monkeypatch.setattr(nucleo, "procesar_mensaje", procesar)
    u = _update(ADMIN_ID)
    _run(bot._consultar_agente(u, "hola", False))
    assert u.respuestas == ["listo"]
    assert vistos["user_id"] == f"telegram:{ADMIN_ID}" and vistos["es_admin"] is True and vistos["channel"] == "telegram_agent"


def test_la_ia_del_usuario_normal_se_corta_al_agotar_el_presupuesto(monkeypatch, sesion):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "1")

    async def procesar(db, **kwargs):
        return {"respuesta": "ok"}

    monkeypatch.setattr(nucleo, "sincronizar_conocimiento_json", lambda db: 0)
    monkeypatch.setattr(nucleo, "procesar_mensaje", procesar)
    u = _update()
    _run(bot._consultar_agente(u, "a", True))
    _run(bot._consultar_agente(u, "b", True))
    assert u.respuestas[0] == "ok" and u.respuestas[1].endswith("Inténtalo más tarde.")


def test_estado_resume_tareas_y_memorias_propias(sesion):
    with sesion() as db:
        db.add(AgentTask(id="t1", user_id=f"telegram:{USUARIO_ID}", kind="agent.qa", status="queued", creado_en="2026-10-07T10:00:00"))
        db.add(AgentTask(id="t2", user_id="telegram:999", kind="agent.chat", status="failed", creado_en="2026-10-07T11:00:00"))
        db.add(AgentMemory(agent_id="laplace", scope="usuario", owner_id=f"telegram:{USUARIO_ID}", kind="preferencia", topic_key="k", content="c", source="s", creado_en="x", actualizado_en="x"))
        db.commit()
    u = _update()
    _run(bot.cmd_estado(u, None))
    assert "Memorias privadas: 1" in u.respuestas[0] and "agent.qa:queued" in u.respuestas[0] and "agent.chat" not in u.respuestas[0]
    vacio = _update(77)
    _run(bot.cmd_estado(vacio, None))
    assert "sin tareas" in vacio.respuestas[0]


def test_partidos_por_defecto_hoy_con_filtro_de_equipo(herramienta):
    herramienta.respuestas["sports.list_fixtures"] = {"fixtures": [{"local": "River", "visitante": "Boca", "liga": "Liga X", "fecha": "20261007183000"}]}
    u = _update()
    _run(bot.cmd_partidos(u, _ctx("2026-10-07", "River")))
    assert herramienta.llamadas == [("sports.list_fixtures", {"date": "2026-10-07", "team": "River", "limit": 200}, False)]
    assert "18:30 River vs Boca" in u.respuestas[0]


def test_partidos_sin_equipo_reintenta_el_filtro_como_liga(monkeypatch):
    secuencia = [{"fixtures": []}, {"fixtures": [{"local": "A", "visitante": "B", "liga": "Premier"}]}]
    argumentos_vistos = []

    async def falso(update, nombre, argumentos, *, aprobado=False):
        argumentos_vistos.append(argumentos)
        return secuencia.pop(0)

    monkeypatch.setattr(nucleo, "_herramienta", falso)
    u = _update()
    _run(bot.cmd_partidos(u, _ctx("Premier")))
    assert argumentos_vistos[0]["team"] == "Premier" and argumentos_vistos[1]["league"] == "Premier"
    assert "A vs B" in u.respuestas[0]


def test_partidos_sin_argumentos_y_sin_resultados(herramienta):
    u = _update()
    _run(bot.cmd_partidos(u, _ctx()))
    assert herramienta.llamadas[0][1]["date"] == bot._fecha_desde("hoy") and "team" not in herramienta.llamadas[0][1]
    assert u.respuestas[0].startswith("No encontré partidos")


def test_partidos_si_la_herramienta_falla_responde_con_un_mensaje_claro(herramienta):
    herramienta.respuestas["sports.list_fixtures"] = RuntimeError("bot caído")
    u = _update()
    _run(bot.cmd_partidos(u, _ctx("mañana")))
    assert u.respuestas == ["No pude consultar los partidos ahora mismo. Inténtalo en un momento."]


def test_predecir_no_encontrado_y_errores_se_explican(herramienta):
    herramienta.respuestas["sports.list_fixtures"] = {"fixtures": []}
    u = _update()
    _run(bot.cmd_predecir(u, _ctx("River", "vs", "Boca")))
    assert "No encontré ese partido hoy ni mañana" in u.respuestas[0]

    partido = {"match_id": "1", "local": "River", "visitante": "Boca", "liga": ""}
    herramienta.respuestas["sports.list_fixtures"] = {"fixtures": [partido]}
    for fallo, esperado in (
        (LimiteExcedido("Tope de predicciones", 60), "Tope de predicciones. Inténtalo más tarde."),
        (PermissionError("sin sesión"), "No pude autenticar la consulta al bot deportivo. Avisa al administrador."),
        (RuntimeError("boom"), "No pude generar la predicción ahora mismo. Inténtalo en un momento."),
    ):
        agent_guard._VENTANA_CHAT.clear()
        herramienta.respuestas["sports.predict"] = fallo
        v = _update()
        _run(bot.cmd_predecir(v, _ctx("River", "vs", "Boca")))
        assert v.respuestas == [esperado]


def test_predecir_usa_competicion_por_defecto_si_el_partido_no_trae_liga(herramienta):
    partido = {"match_id": "1", "local": "River", "visitante": "Boca", "liga": ""}
    herramienta.respuestas["sports.list_fixtures"] = {"fixtures": [partido]}
    herramienta.respuestas["sports.predict"] = {"resumen": {"pick": None}}
    u = _update()
    _run(bot.cmd_predecir(u, _ctx("River", "vs", "Boca")))
    predict = [c for c in herramienta.llamadas if c[0] == "sports.predict"][0]
    assert predict[1]["league"] == "Competición" and "Sin pronóstico" in u.respuestas[0]


def test_top_muestra_hasta_cinco_picks_y_maneja_vacio_y_errores(herramienta):
    picks = [{"local": f"L{i}", "visitante": f"V{i}", "pick_final": "Local", "confianza_final": "ALTA"} for i in range(7)]
    herramienta.respuestas["sports.list_top_picks"] = {"picks": picks}
    u = _update()
    _run(bot.cmd_top(u, _ctx("2026-10-07")))
    assert u.respuestas[0].count("•") == 5 and "L4 vs V4 → Local (ALTA)" in u.respuestas[0] and "L5" not in u.respuestas[0]
    herramienta.respuestas["sports.list_top_picks"] = {"picks": [{"pick": "Empate"}]}
    sin_campos = _update()
    _run(bot.cmd_top(sin_campos, _ctx()))
    assert "? vs ? → Empate (n/d)" in sin_campos.respuestas[0]
    herramienta.respuestas["sports.list_top_picks"] = {"picks": []}
    vacio = _update()
    _run(bot.cmd_top(vacio, _ctx()))
    assert "No hay Top Picks publicados" in vacio.respuestas[0]
    herramienta.respuestas["sports.list_top_picks"] = RuntimeError("x")
    roto = _update()
    _run(bot.cmd_top(roto, _ctx()))
    assert roto.respuestas == ["No pude consultar los Top Picks ahora mismo."]


def test_ligas_lista_los_slugs_y_trunca_a_60(herramienta):
    herramienta.respuestas["sports.list_leagues"] = {"leagues": [{"slug": f"liga-{i}"} for i in range(70)] + [{"slug": ""}]}
    u = _update()
    _run(bot.cmd_ligas(u, None))
    assert "(70)" in u.respuestas[0] and "liga-59" in u.respuestas[0] and "liga-60" not in u.respuestas[0] and "…" in u.respuestas[0]
    herramienta.respuestas["sports.list_leagues"] = RuntimeError("x")
    roto = _update()
    _run(bot.cmd_ligas(roto, None))
    assert roto.respuestas == ["No pude consultar las ligas ahora mismo."]


# --------------------------------------------------------------------------------------------
# Comandos de administrador
# --------------------------------------------------------------------------------------------

def _cliente_httpx(monkeypatch, manejador):
    def fabrica(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(manejador)
        return _CLIENTE_REAL(*args, **kwargs)

    monkeypatch.setattr(bot.httpx, "AsyncClient", fabrica)


def test_panel_cuenta_tablas_y_muestra_el_scheduler(monkeypatch, sesion):
    vistas = []

    def manejador(request):
        vistas.append(request.url.path)
        return httpx.Response(200, json={"saludable": True, "jobs": [{"job": "top_picks", "estado": "ok"}, {"nombre": "res", "ok": False}]})

    _cliente_httpx(monkeypatch, manejador)
    u = _update(ADMIN_ID)
    _run(bot.cmd_panel(u, _ctx()))
    texto = u.respuestas[0]
    assert "Panel Laplace" in texto and "usuarios: 0" in texto and "sin observaciones" in texto
    assert "Scheduler: saludable" in texto and "• top_picks: ok" in texto and "• res: revisar" in texto
    assert vistas == ["/api/v1/scheduler/status"]


def test_panel_con_scheduler_caido_lo_dice_sin_romper(monkeypatch, sesion):
    def manejador(request):
        raise httpx.ConnectError("apagado")

    _cliente_httpx(monkeypatch, manejador)
    u = _update(ADMIN_ID)
    _run(bot.cmd_panel(u, _ctx()))
    assert "Scheduler: no disponible (ConnectError)" in u.respuestas[0]


def test_panel_marca_nd_si_una_tabla_no_existe(monkeypatch, sesion):
    from sqlalchemy import text

    with sesion() as db:
        db.execute(text("DROP TABLE analisis_comparativo"))
        db.commit()
    _cliente_httpx(monkeypatch, lambda request: httpx.Response(200, json={"saludable": False}))
    u = _update(ADMIN_ID)
    _run(bot.cmd_panel(u, _ctx()))
    assert "análisis: n/d" in u.respuestas[0] and "con jobs atrasados" in u.respuestas[0]


def test_fuentes_muestra_el_estado_de_cada_fuente(monkeypatch, sesion):
    from backend.api.services import source_health

    async def verificar(db, client):
        return [
            {"fuente": "odds", "saludable": True, "configurada": True, "latencia_ms": 120, "cuota_restante": 450},
            {"fuente": "bsd", "saludable": False, "configurada": False},
            {"fuente": "apif", "saludable": False, "configurada": True},
        ]

    monkeypatch.setattr(source_health, "verificar_fuentes", verificar)
    u = _update(ADMIN_ID)
    _run(bot.cmd_fuentes(u, _ctx()))
    assert "✅ odds · 120 ms · cuota 450" in u.respuestas[0] and "⚪ bsd" in u.respuestas[0] and "❌ apif" in u.respuestas[0]


def test_resultados_pasa_la_fecha_valida_y_resume(herramienta):
    herramienta.respuestas["sports.results"] = {"result": {"data": {"actualizados": 3, "total": 8}}}
    u = _update(ADMIN_ID)
    _run(bot.cmd_resultados(u, _ctx("2026-10-07")))
    assert herramienta.llamadas == [("sports.results", {"date": "2026-10-07"}, True)]
    assert u.respuestas == ["Verificación de resultados: 3 actualizados de 8 revisados."]
    herramienta.respuestas["sports.results"] = {"result": {}}
    herramienta.llamadas.clear()
    sin_datos = _update(ADMIN_ID)
    _run(bot.cmd_resultados(sin_datos, _ctx("ayer")))
    assert herramienta.llamadas[0][1] == {"date": ""} and sin_datos.respuestas == ["Verificación ejecutada."]


def test_toppicks_cuenta_picks_sin_publicar(herramienta):
    herramienta.respuestas["sports.top_picks"] = {"result": {"resultado": {"picks": [{}, {}]}}}
    u = _update(ADMIN_ID)
    _run(bot.cmd_toppicks(u, _ctx()))
    assert "2 pick(s)" in u.respuestas[0] and "/publicar confirmo" in u.respuestas[0] and herramienta.llamadas[0][2] is True
    herramienta.respuestas["sports.top_picks"] = {"result": {"picks": [{}]}}
    plano = _update(ADMIN_ID)
    _run(bot.cmd_toppicks(plano, _ctx()))
    assert "1 pick(s)" in plano.respuestas[0]


def test_publicar_informa_si_se_publico_o_no(herramienta):
    herramienta.respuestas["sports.publish"] = {"result": {"publicado": False}}
    u = _update(ADMIN_ID)
    _run(bot.cmd_publicar(u, _ctx("CONFIRMO")))
    assert u.respuestas[0].startswith("No se publicó")
    herramienta.respuestas["sports.publish"] = {"result": {}}
    ok = _update(ADMIN_ID)
    _run(bot.cmd_publicar(ok, _ctx("confirmo")))
    assert ok.respuestas == ["Top Picks publicados en el canal."]
    for malo in ((), ("si",)):
        sin_confirmar = _update(ADMIN_ID)
        _run(bot.cmd_publicar(sin_confirmar, _ctx(*malo)))
        assert "confirmo" in sin_confirmar.respuestas[0]


def test_aprobaciones_lista_pendientes_y_vacio(sesion):
    vacio = _update(ADMIN_ID)
    _run(bot.cmd_aprobaciones(vacio, _ctx()))
    assert vacio.respuestas == ["No hay aprobaciones pendientes."]
    with sesion() as db:
        aprobacion = crear_aprobacion(db, "inv", "usuario-9", "sports.publish", {"publish": True})
        db.commit()
        identificador = aprobacion.id
    u = _update(ADMIN_ID)
    _run(bot.cmd_aprobaciones(u, _ctx()))
    assert f"{identificador} · sports.publish · usuario usuario-9" in u.respuestas[0]


def test_decidir_con_aprobacion_inexistente_informa_el_motivo(sesion):
    u = _update(ADMIN_ID)
    _run(bot.cmd_decidir_aprobacion(u, _ctx("no-existe", "aprobar")))
    assert u.respuestas == ["Aprobación no-existe: Aprobación pendiente no encontrada o ya decidida."]


def test_decidir_rechazar_una_aprobacion_real_no_ejecuta_nada(sesion):
    with sesion() as db:
        identificador = crear_aprobacion(db, "inv", "usuario-9", "sports.publish", {"publish": True}).id
        db.commit()
    u = _update(ADMIN_ID)
    _run(bot.cmd_decidir_aprobacion(u, _ctx(identificador, "rechazar")))
    assert u.respuestas == [f"Aprobación {identificador}: rejected."]


def test_los_comandos_de_admin_rechazan_al_usuario_normal(herramienta):
    for comando in (bot.cmd_panel, bot.cmd_fuentes, bot.cmd_resultados, bot.cmd_toppicks, bot.cmd_publicar, bot.cmd_aprobaciones, bot.cmd_decidir_aprobacion):
        agent_guard._VENTANA_CHAT.clear()
        u = _update(USUARIO_ID)
        _run(comando(u, _ctx("confirmo", "aprobar")))
        assert u.respuestas == [bot.MSG_SOLO_ADMIN], comando.__name__
    assert herramienta.llamadas == []


# --------------------------------------------------------------------------------------------
# _herramienta, errores globales, menú y fábrica
# --------------------------------------------------------------------------------------------

def test_herramienta_real_pasa_rol_usuario_y_autorizacion(monkeypatch):
    vistos = {}

    async def falso(nombre, argumentos, **kwargs):
        vistos.update(nombre=nombre, argumentos=argumentos, **kwargs)
        return {"ok": True}

    monkeypatch.setattr(nucleo, "ejecutar_herramienta_deportiva", falso)
    monkeypatch.setattr(nucleo, "autorizacion_sports", lambda usuario, bearer, admin=False: f"Bearer {usuario}/{admin}")
    assert _run(bot._herramienta(_update(ADMIN_ID), "sports.results", {"a": 1}, aprobado=True)) == {"ok": True}
    assert vistos["es_admin"] is True and vistos["aprobado"] is True and vistos["usuario"] == f"telegram:{ADMIN_ID}"
    assert vistos["authorization"] == f"Bearer telegram:{ADMIN_ID}/True"
    _run(bot._herramienta(_update(USUARIO_ID), "sports.predict", {}))
    assert vistos["es_admin"] is False and vistos["aprobado"] is False


def test_error_global_solo_registra():
    _run(bot._error_global(object(), SimpleNamespace(error=RuntimeError("x"))))


class _AppFalsa:
    def __init__(self, falla_publico=False, falla_admin=False):
        self.llamadas = []
        self.falla_publico, self.falla_admin = falla_publico, falla_admin
        self.bot = SimpleNamespace(set_my_commands=self._set)

    async def _set(self, comandos, scope=None):
        if scope is None and self.falla_publico:
            raise RuntimeError("telegram caído")
        if scope is not None and self.falla_admin:
            raise RuntimeError("el admin no abrió el chat")
        self.llamadas.append((len(comandos), getattr(scope, "chat_id", None)))


def test_menu_de_comandos_publico_y_ampliado_para_el_admin():
    app = _AppFalsa()
    _run(bot._publicar_menu_de_comandos(app))
    assert app.llamadas == [(len(bot.COMANDOS_PUBLICOS), None), (len(bot.COMANDOS_PUBLICOS) + len(bot.COMANDOS_ADMIN), ADMIN_ID)]


def test_menu_tolera_fallos_del_chat_del_admin_y_de_telegram():
    sin_chat_admin = _AppFalsa(falla_admin=True)
    _run(bot._publicar_menu_de_comandos(sin_chat_admin))
    assert sin_chat_admin.llamadas == [(len(bot.COMANDOS_PUBLICOS), None)]
    caido = _AppFalsa(falla_publico=True)
    _run(bot._publicar_menu_de_comandos(caido))  # no lanza
    assert caido.llamadas == []


def test_construir_app_exige_token(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(RuntimeError, match="AGENT_TELEGRAM_BOT_TOKEN"):
        bot.construir_app()


def test_construir_app_registra_todos_los_comandos(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", "123456:token-falso-de-prueba")
    app = bot.construir_app()
    comandos = {c for handlers in app.handlers.values() for h in handlers for c in getattr(h, "commands", [])}
    esperados = {n for n, _ in bot.COMANDOS_PUBLICOS + bot.COMANDOS_ADMIN} | {"start"}
    assert esperados <= comandos
    assert any(type(h).__name__ == "MessageHandler" for h in app.handlers[0])
    assert app.error_handlers
