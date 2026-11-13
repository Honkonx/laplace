"""Bot de Telegram del agente: abierto a todos, privilegios solo del administrador (2026-10-07)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.api.bot import laplace_agent_bot as bot
from backend.api.bot import laplace_agent_bot_admin, laplace_agent_bot_nucleo as nucleo
from backend.api.core.config import settings
from backend.api.services import agent_guard


def _update(user_id: int, texto: str = "hola"):
    respuestas: list[str] = []

    async def reply_text(mensaje):
        respuestas.append(mensaje)

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id), effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(text=texto, reply_text=reply_text), respuestas=respuestas,
    )


def _ctx(*args):
    return SimpleNamespace(args=list(args))


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setattr(type(settings), "admin_ids", property(lambda self: ["1"]))
    for nombre in ("AGENT_TELEGRAM_ALLOWED_IDS", "AGENT_TELEGRAM_BLOCKED_IDS"):
        monkeypatch.delenv(nombre, raising=False)
    agent_guard.resetear_contadores()
    agent_guard._VENTANA_CHAT.clear()
    yield
    agent_guard.resetear_contadores()
    agent_guard._VENTANA_CHAT.clear()


def test_comandos_de_administracion_rechazan_a_un_usuario_normal():
    for comando in (bot.cmd_panel, bot.cmd_fuentes, bot.cmd_resultados, bot.cmd_toppicks, bot.cmd_publicar,
                    bot.cmd_aprobaciones, bot.cmd_decidir_aprobacion):
        agent_guard._VENTANA_CHAT.clear()
        usuario = _update(42)
        asyncio.run(comando(usuario, _ctx("confirmo")))
        assert usuario.respuestas == [bot.MSG_SOLO_ADMIN], comando.__name__


def test_publicar_exige_la_palabra_confirmo(monkeypatch):
    llamadas = []

    async def falso(update, nombre, argumentos, *, aprobado=False):
        llamadas.append((nombre, aprobado))
        return {"result": {"publicado": True}}

    monkeypatch.setattr(nucleo, "_herramienta", falso)
    admin = _update(1)
    asyncio.run(bot.cmd_publicar(admin, _ctx()))
    assert llamadas == [] and "confirmo" in admin.respuestas[0]
    asyncio.run(bot.cmd_publicar(admin, _ctx("confirmo")))
    assert llamadas == [("sports.publish", True)]


def test_el_administrador_tiene_mas_margen_de_mensajes_por_minuto(monkeypatch):
    monkeypatch.setenv("AGENT_TELEGRAM_RATE_PER_MIN", "2")
    llamados = []

    @bot.protegido
    async def handler(update, context):
        llamados.append(update.effective_user.id)

    for _ in range(6):
        asyncio.run(handler(_update(2), None))
    assert llamados.count(2) == 2  # usuario normal: tope de 2 por minuto
    for _ in range(8):
        asyncio.run(handler(_update(1), None))
    assert llamados.count(1) == 8  # admin: 2 x 6 = 12 por minuto


def test_predecir_sin_formato_correcto_explica_el_uso():
    u = _update(5)
    asyncio.run(bot.cmd_predecir(u, _ctx("River")))
    assert "Uso: /predecir" in u.respuestas[0]


def test_predecir_busca_el_partido_y_muestra_probabilidades_honestas(monkeypatch):
    partido = {"match_id": "77", "local": "River Plate", "visitante": "Boca Juniors", "liga": "Liga Profesional"}
    llamadas = []

    async def falso(update, nombre, argumentos, *, aprobado=False):
        llamadas.append(nombre)
        if nombre == "sports.list_fixtures":
            return {"fixtures": [partido]}
        return {"resumen": {
            "pick": "Local", "confianza": "MEDIA", "prob_ponderada_pct": {"local": 52.0, "empate": 26.0, "visitante": 22.0},
            "modulos_usados": ["odds", "historico"],
            "tasa_base_liga": {"partidos": 900, "pct_local": 44.0, "pct_empate": 26.0, "pct_visitante": 30.0},
        }}

    monkeypatch.setattr(nucleo, "_herramienta", falso)
    u = _update(5)
    asyncio.run(bot.cmd_predecir(u, _ctx("River", "vs", "Boca")))
    texto = u.respuestas[0]
    assert "52.0%" in texto and "MEDIA" in texto and "odds, historico" in texto and "no una certeza" in texto
    assert "sports.predict" in llamadas


def test_prediccion_sin_pick_es_un_resultado_honesto_no_un_error():
    texto = bot.formatear_prediccion({"local": "A", "visitante": "B"}, {"pick": None})
    assert "Sin pronóstico" in texto and "no un error" in texto


def test_un_usuario_normal_tiene_tope_de_predicciones_y_el_admin_no(monkeypatch):
    """El tope vive en la herramienta (punto común de todos los caminos): aquí se ejercita de verdad."""
    from backend.api.services import agent_tools

    monkeypatch.setenv("AGENT_PREDICCIONES_MAX_POR_MINUTO", "2")
    partido = {"match_id": "1", "local": "River Plate", "visitante": "Boca Juniors", "liga": "X"}

    async def falso_get(ruta, params=None):
        return {"fixtures": [partido]}

    async def falso_post(ruta, payload, params=None, authorization=None):
        return {"consenso": {"pick_final": "Sin pronóstico"}}

    monkeypatch.setattr(agent_tools, "_get", falso_get)
    monkeypatch.setattr(agent_tools, "_post", falso_post)
    normal = _update(9)
    for _ in range(3):
        agent_guard._VENTANA_CHAT.clear()
        asyncio.run(bot.cmd_predecir(normal, _ctx("River", "vs", "Boca")))
    assert any("Demasiadas predicciones" in r for r in normal.respuestas)
    admin = _update(1)
    for _ in range(4):
        agent_guard._VENTANA_CHAT.clear()
        asyncio.run(bot.cmd_predecir(admin, _ctx("River", "vs", "Boca")))
    assert not any("Demasiadas" in r for r in admin.respuestas)


def test_formatear_partidos_agrupa_por_liga_y_limita():
    partidos = [{"local": f"L{i}", "visitante": f"V{i}", "liga": "Liga A" if i % 2 else "Liga B", "fecha": "20261007183000"}
                for i in range(30)]
    texto = bot.formatear_partidos(partidos, "2026-10-07")
    assert "Liga A" in texto and "Liga B" in texto and "18:30" in texto and "y 10 más" in texto
    assert bot.formatear_partidos([], "2026-10-07").startswith("No encontré")


def test_ia_del_admin_no_consume_presupuesto_y_la_del_usuario_si(monkeypatch):
    consumos = []
    monkeypatch.setattr(nucleo, "consumir_ia", lambda usuario, es_admin=False: consumos.append(usuario))

    class _Sesion:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    async def procesar(db, **kwargs):
        return {"respuesta": "ok"}

    monkeypatch.setattr(nucleo, "SessionLocal", lambda: _Sesion())
    monkeypatch.setattr(nucleo, "sincronizar_conocimiento_json", lambda db: 0)
    monkeypatch.setattr(nucleo, "ultima_sesion", lambda db, usuario, canal: None)
    monkeypatch.setattr(nucleo, "procesar_mensaje", procesar)
    asyncio.run(bot._consultar_agente(_update(1), "hola", True))
    asyncio.run(bot._consultar_agente(_update(7), "hola", True))
    assert consumos == ["telegram:7"]


def test_decidir_no_decide_si_la_palabra_no_es_aprobar_ni_rechazar(monkeypatch):
    llamadas = []

    async def falso(db, approval_id, decision, decididor, **kw):
        llamadas.append((approval_id, decision))
        return {"status": decision}

    monkeypatch.setattr(laplace_agent_bot_admin, "decidir_aprobacion", falso)
    for args in ((), ("abc",), ("abc", "aprobr"), ("abc", "tal vez")):
        admin = _update(1)
        asyncio.run(bot.cmd_decidir_aprobacion(admin, _ctx(*args)))
        assert admin.respuestas == ["Uso: /decidir <id> aprobar | rechazar"], args
    assert llamadas == []          # un error de tipeo ya no rechaza una aprobación en silencio


def test_decidir_aprueba_y_rechaza_con_las_palabras_validas(monkeypatch):
    llamadas = []

    async def falso(db, approval_id, decision, decididor, **kw):
        llamadas.append((approval_id, decision))
        return {"status": decision}

    monkeypatch.setattr(laplace_agent_bot_admin, "decidir_aprobacion", falso)
    for palabra in ("aprobar", "Approve"):
        asyncio.run(bot.cmd_decidir_aprobacion(_update(1), _ctx("x1", palabra)))
    asyncio.run(bot.cmd_decidir_aprobacion(_update(1), _ctx("x2", "rechazar")))
    assert llamadas == [("x1", "approved"), ("x1", "approved"), ("x2", "rejected")]


@pytest.mark.parametrize(("politica", "usuario", "ia_esperada"), [("nadie", 1, False), ("nadie", 42, False), ("admin", 1, True), ("admin", 42, False), ("todos", 1, True), ("todos", 42, True)])
def test_el_texto_libre_usa_ia_segun_la_politica(monkeypatch, politica, usuario, ia_esperada):
    """MA-05: quién puede usar IA en el texto libre de Telegram (por defecto solo el administrador)."""
    llamadas = []

    async def consultar(update, texto, usar_ia):
        llamadas.append(usar_ia)

    monkeypatch.setattr(nucleo, "_consultar_agente", consultar)
    monkeypatch.setattr(settings, "AGENT_TEXTO_LIBRE_IA", politica)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    asyncio.run(bot._responder(_update(usuario, "analiza Boca vs River"), _ctx()))
    assert llamadas == [ia_esperada]


def test_con_la_ia_apagada_el_texto_libre_nunca_usa_ia(monkeypatch):
    llamadas = []

    async def consultar(update, texto, usar_ia):
        llamadas.append(usar_ia)

    monkeypatch.setattr(nucleo, "_consultar_agente", consultar)
    monkeypatch.setattr(settings, "AGENT_TEXTO_LIBRE_IA", "todos")
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", False)
    asyncio.run(bot._responder(_update(1, "hola"), _ctx()))
    assert llamadas == [False]


def test_los_comandos_de_sesion_responden_y_aislan_por_usuario(monkeypatch, db_session):
    from backend.api.bot import laplace_agent_bot_comandos as comandos

    monkeypatch.setattr(comandos, "SessionLocal", lambda: _Contexto(db_session))
    u = _update(5)
    asyncio.run(bot.cmd_sesiones(u, _ctx()))
    assert "Todavía no tienes conversaciones" in u.respuestas[0]
    u = _update(5)
    asyncio.run(bot.cmd_nuevo(u, _ctx()))
    assert "conversación nueva" in u.respuestas[0]
    u = _update(5)
    asyncio.run(bot.cmd_retomar(u, _ctx()))
    assert "Todavía no tengo una conversación anterior" in u.respuestas[0]


class _Contexto:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *args):
        return False
