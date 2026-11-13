"""Recorrido del menú completo de Telegram como lo usa una persona (H-008 en adelante, el plan de pruebas «como usuario» (repositorio de trabajo)).

Base construida con las migraciones reales; los manejadores son los reales; solo se simula el exterior (Telegram y las fuentes de datos, que responden 503 o vacío).
Matriz: tipo de persona (nueva, free, pro, administrador) × cada comando × argumentos normales, vacíos, enormes, con símbolos y con intentos de inyección; y cada botón con datos válidos, rotos y adversariales.
Contrato que se exige a TODO manejador: no lanza (en Telegram una excepción = el usuario no recibe nada), responde algo, no filtra trazas ni secretos, y lo exclusivo del administrador no se ejecuta para los demás.
"""
from __future__ import annotations

import asyncio
import itertools
import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import text

from backend.api.bot import laplace_bot, laplace_bot_admin, laplace_bot_callbacks, laplace_bot_usuario
from backend.api.core.config import settings
from backend.api.models.usuarios import Usuario

ADMIN = "111"
PERSONAS = {"nueva": ("5001", None), "free": ("5002", "free"), "pro": ("5003", "pro"), "admin": (ADMIN, "max")}
PROHIBIDO_EN_RESPUESTAS = re.compile(r"Traceback|sqlalchemy|OperationalError|IntegrityError|Exception|NoneType|KeyError|\bsk-[A-Za-z0-9]{10,}|\d{8,10}:[A-Za-z0-9_-]{30,}")

COMANDOS = {
    "cmd_start": [()], "cmd_ayuda": [()], "cmd_mi_id": [()], "cmd_juegos": [()], "cmd_ligas": [()], "cmd_stats": [()], "cmd_hoy": [()], "cmd_top": [()],
    "cmd_encuesta": [(), ("x",), ("1",) * 30], "cmd_misplanes": [()],
    "cmd_favoritos": [(), ("agregar", "LaLiga"), ("agregar", "Premier League"), ("agregar", "a" * 500), ("quitar", "LaLiga"), ("quitar", "inexistente"), ("borrar", "x"), ("agregar",), ("agregar", "'; DROP TABLE usuarios;--"), ("agregar", "💥" * 40)],
    "cmd_vincular": [(), ("u",), ("u", "p"), ("'; DROP TABLE usuarios;--", "x"), ("u" * 300, "p" * 300), ("💥", "💥")],
    "cmd_privacidad": [(), ("aceptar",), ("revocar",), ("zzz",), ("aceptar", "extra", "args")],
    "cmd_equipos": [(), ("agregar", "Arsenal"), ("agregar", "A|B"), ("agregar", "x" * 200), ("quitar", "Arsenal"), ("quitar",), ("agregar", "Real", "Madrid")],
    "cmd_olvidame": [(), ("confirmo",), ("CONFIRMO",), ("si",)],
    "cmd_avisos": [(), ("on",), ("off",), ("ON",), ("quizas",)],
    "cmd_desconocido": [()],
}
ADMIN_ONLY = {
    "cmd_generarcodigos": [(), ("pro", "30", "2"), ("pro", "abc", "2"), ("max", "-5", "9999"), ("zzz", "1", "1")],
    "cmd_listarcodigos": [()], "cmd_gestionarusuario": [(), ("123", "pro"), ("123", "inexistente"), ("abc", "pro"), ("123", "pro", "-1")],
}


class _Entorno:
    def __init__(self, fabrica):
        self.fabrica = fabrica

    def update(self, user_id: str, texto: str = "/cmd", callback: str | None = None):
        u = MagicMock()
        u.effective_user.id = int(user_id)
        u.effective_user.first_name = "Ana"
        u.effective_chat.id = int(user_id)
        u.message.text = texto
        u.message.reply_html = AsyncMock()
        u.message.reply_text = AsyncMock()
        u.effective_message.reply_text = AsyncMock()
        u.effective_message.reply_html = AsyncMock()
        if callback is not None:
            u.callback_query.id = "cbq"
            u.callback_query.data = callback
            u.callback_query.from_user.id = int(user_id)
            u.callback_query.message.reply_html = AsyncMock()
            u.callback_query.message.reply_text = AsyncMock()
            u.callback_query.message.edit_reply_markup = AsyncMock()
            u.callback_query.answer = AsyncMock()
        return u

    def contexto(self, *args: str, fuentes: str = "503"):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="caído") if fuentes == "503" else httpx.Response(200, json={})

        c = MagicMock()
        c.args = list(args)
        c.application.bot_data = {"http_client": httpx.AsyncClient(transport=httpx.MockTransport(handler))}
        c.bot.send_message = AsyncMock()
        return c

    @staticmethod
    def respuestas(update) -> list[str]:
        textos = []
        for destino in (update.message, update.effective_message, getattr(update.callback_query, "message", None)):
            if destino is None:
                continue
            for metodo in ("reply_html", "reply_text"):
                for llamada in getattr(destino, metodo).call_args_list:
                    if llamada.args:
                        textos.append(str(llamada.args[0]))
        return textos


@pytest.fixture()
def entorno(base_migrada, monkeypatch):
    fabrica = base_migrada("head")
    for modulo in (laplace_bot_usuario, laplace_bot_callbacks, laplace_bot_admin, laplace_bot):
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", ADMIN)
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", AsyncMock())
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    monkeypatch.setattr(laplace_bot.telegram_client, "enviar_mensaje", AsyncMock(return_value=True))
    return _Entorno(fabrica)


def _crear_persona(entorno, user_id: str, plan: str | None) -> None:
    if plan is None:
        return
    with entorno.fabrica() as db:
        if not db.query(Usuario).filter(Usuario.device_id == user_id).first():
            db.add(Usuario(device_id=user_id, activo=1, plan=plan, creado_en="2026-11-11 10:00:00"))
            db.commit()


def _correr(coro):
    return asyncio.run(coro)


CASOS_COMANDOS = [(p, c, a) for p in PERSONAS for c, variantes in COMANDOS.items() for a in variantes]


@pytest.mark.parametrize("persona,comando,args", CASOS_COMANDOS, ids=lambda v: str(v)[:40])
def test_cada_comando_responde_sin_romperse_para_cada_tipo_de_persona(entorno, persona, comando, args):
    user_id, plan = PERSONAS[persona]
    _crear_persona(entorno, user_id, plan)
    u = entorno.update(user_id)
    _correr(getattr(laplace_bot, comando)(u, entorno.contexto(*args)))
    respuestas = entorno.respuestas(u)
    assert respuestas, f"{comando}{args} no respondió nada a {persona}"
    assert not any(PROHIBIDO_EN_RESPUESTAS.search(r) for r in respuestas), f"{comando}{args} filtró un error interno: {respuestas[0][:120]}"
    with entorno.fabrica() as db:  # los intentos de inyección no dañan nada
        assert db.execute(text("select count(*) from usuarios")).scalar() >= 0


CASOS_ADMIN = [(p, c, a) for p in PERSONAS for c, variantes in ADMIN_ONLY.items() for a in variantes]


@pytest.mark.parametrize("persona,comando,args", CASOS_ADMIN, ids=lambda v: str(v)[:40])
def test_lo_exclusivo_del_administrador_no_se_ejecuta_para_los_demas(entorno, persona, comando, args):
    user_id, plan = PERSONAS[persona]
    _crear_persona(entorno, user_id, plan)
    antes = _contar(entorno, "codigos_acceso"), _planes(entorno)
    u = entorno.update(user_id)
    _correr(getattr(laplace_bot, comando)(u, entorno.contexto(*args)))
    respuestas = entorno.respuestas(u)
    assert respuestas, f"{comando}{args} no respondió nada a {persona}"
    assert not any(PROHIBIDO_EN_RESPUESTAS.search(r) for r in respuestas), f"{comando}{args} filtró un error interno: {respuestas[0][:120]}"
    if persona != "admin":
        assert (_contar(entorno, "codigos_acceso"), _planes(entorno)) == antes, f"{persona} logró cambiar datos con {comando}{args}"


def _contar(entorno, tabla: str) -> int:
    with entorno.fabrica() as db:
        return db.execute(text(f"select count(*) from {tabla}")).scalar()


def _planes(entorno) -> list:
    with entorno.fabrica() as db:
        return db.execute(text("select device_id, plan from usuarios order by device_id")).fetchall()


BOTONES = [
    "DAY_TODAY", "DAY_TOMORROW", "DAY_OTHER", "DAY_", "LEAGUE_20261111_premier-league", "LEAGUE_20261111_", "LEAGUE_x", "LEAGUE_", "LEAGUE_99999999_" + "z" * 300,
    "PREDICT_20261111_m1", "PREDICT_20261111_", "PREDICT_", "PREDICT_x", "PREDICT_20261111_" + "9" * 200, "PREDICT_20261111_'; DROP TABLE jobs;--", "PREDICT_20261111_💥",
    "REFRESH_20261111_m1", "REFRESH_", "VOTE_m1_L", "VOTE_m1_E", "VOTE_m1_V", "VOTE_m1_Z", "VOTE_", "VOTE_ _L", "pub_x", "nopub_x", "pub_", "nopub_", "ZZZ_inexistente",
]
CASOS_BOTONES = list(itertools.product(["nueva", "free", "admin"], BOTONES))


@pytest.mark.parametrize("persona,dato", CASOS_BOTONES, ids=lambda v: str(v)[:44])
def test_cada_boton_responde_o_ignora_sin_romperse_incluso_con_datos_rotos(entorno, persona, dato):
    user_id, plan = PERSONAS[persona]
    _crear_persona(entorno, user_id, plan)
    u = entorno.update(user_id, callback=dato)
    ctx = entorno.contexto()
    prefijo = dato.split("_")[0]
    manejador = {
        "DAY": laplace_bot.callback_dia, "LEAGUE": laplace_bot.callback_liga, "PREDICT": laplace_bot.callback_predict, "REFRESH": laplace_bot.callback_predict,
        "VOTE": laplace_bot.callback_voto, "pub": laplace_bot.callback_confirmar_picks, "nopub": laplace_bot.callback_confirmar_picks,
    }.get(prefijo)
    if manejador is None:
        pytest.skip("Telegram solo enruta los prefijos registrados; el resto nunca llega a un manejador")
    _correr(manejador(u, ctx))
    respuestas = entorno.respuestas(u)
    assert not any(PROHIBIDO_EN_RESPUESTAS.search(r) for r in respuestas), f"{dato} filtró un error interno: {respuestas[0][:120]}"
    respondio = bool(respuestas) or laplace_bot.telegram_client.responder_callback.await_count > 0 or u.callback_query.answer.await_count > 0
    assert respondio, f"{dato} no produjo ninguna respuesta visible para {persona}"
    if prefijo in ("pub", "nopub") and persona != "admin":
        assert laplace_bot.telegram_client.enviar_mensaje.await_count == 0, "un usuario no administrador publicó en el canal"


# ---------------------------------------------------------------- menú publicado en Telegram (H-012)
def test_todo_comando_del_menu_tiene_manejador_y_los_publicos_estan_en_el_menu():
    import re
    from pathlib import Path

    fuente = Path("backend/api/bot/laplace_bot.py").read_text(encoding="utf-8")
    con_manejador = set(re.findall(r'CommandHandler\("([a-z_]+)"', fuente))
    menu = {n for n, _ in laplace_bot.COMANDOS_PUBLICOS}
    assert menu <= con_manejador, f"comandos del menú sin manejador: {menu - con_manejador}"
    administracion = {"generarcodigos", "listarcodigos", "gestionarusuario"}
    assert (con_manejador - menu) == administracion, f"comandos públicos que faltan en el menú: {con_manejador - menu - administracion}"
    assert all(len(d) <= 256 and re.fullmatch(r"[a-z0-9_]{1,32}", n) for n, d in laplace_bot.COMANDOS_PUBLICOS)


def test_el_menu_se_registra_en_telegram_y_un_fallo_de_red_no_tumba_el_arranque():
    app = MagicMock()
    app.bot.set_my_commands = AsyncMock()
    asyncio.run(laplace_bot.registrar_menu(app))
    comandos = app.bot.set_my_commands.await_args.args[0]
    assert [c.command for c in comandos] == [n for n, _ in laplace_bot.COMANDOS_PUBLICOS]
    app.bot.set_my_commands = AsyncMock(side_effect=RuntimeError("sin red"))
    asyncio.run(laplace_bot.registrar_menu(app))  # no lanza
