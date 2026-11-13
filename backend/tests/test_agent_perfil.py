"""MS-6: la memoria tipada del usuario (zona horaria, estilo, mercados) sobre una base de las MIGRACIONES REALES y el agente real. Con consentimiento, tope duro, borrado con `/olvidame`,
instantánea para la IA y zona horaria en los avisos. Solo el exterior (Telegram, proveedor de IA, partidos programados) va simulado en el límite."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.api.core.config import settings
from backend.api.db import bot_memoria_repo
from backend.api.models.bot_memoria import BotPerfilUsuario
from backend.api.models.partidos import PartidoDia
from backend.api.services import agent_perfil, agent_runtime, avisos_favoritos as av

TG = "telegram:777"
CHILE = ZoneInfo("America/Santiago")


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


def _decir(db, texto, user=TG, incognito=False):
    return asyncio.run(agent_runtime.procesar_mensaje(db, user, texto, None, "telegram_agent", False, False, incognito=incognito))["respuesta"]


# ---------------------------------------------------------------- interpretar
@pytest.mark.parametrize("texto, esperado", [
    ("estoy en Chile", ("zona", "Chile")), ("mi zona horaria es America/Santiago", ("zona", "America/Santiago")), ("vivo en Madrid", ("zona", "Madrid")),
    ("responde corto", ("estilo", "corto")), ("respóndeme técnico", ("estilo", "tecnico")), ("contestame de forma resumido", ("estilo", "resumido")), ("responde normal", ("estilo", "normal")),
    ("me interesan goles y ambos marcan", ("mercados", "goles|ambos marcan")), ("miro solo 1x2", ("mercados", "1x2")), ("quiero ver más de 2,5", ("mercados", "mas de 2,5")),
    ("mi perfil", ("ver", "")), ("ver mis preferencias", ("ver", "")), ("borra mi perfil", ("borrar", "")), ("olvida mis preferencias", ("borrar", "")),
    ("estoy en el estadio", None), ("estoy en casa", None), ("responde la pregunta", None), ("me interesa la política", None), ("miro la tele", None), ("mi perfil?", None), ("hola", None),
])
def test_interpretar(texto, esperado):
    r = agent_perfil.interpretar(texto)
    assert (None if r is None else (r[0], r[1].lower())) == (None if esperado is None else (esperado[0], esperado[1].lower()))


def test_las_zonas_se_reconocen_por_pais_ciudad_o_nombre_completo():
    assert agent_perfil._zona_valida("Chile") == "America/Santiago" and agent_perfil._zona_valida("Bogotá") == "America/Bogota" and agent_perfil._zona_valida("America/Lima") == "America/Lima"
    assert agent_perfil._zona_valida("Marte") is None and agent_perfil._zona_valida("Foo/Bar") is None


# ---------------------------------------------------------------- flujo de punta a punta
def test_sin_consentimiento_pide_aceptar_y_despues_guarda_cada_campo(db):
    assert "acepto" in _decir(db, "estoy en Chile").lower() and db.get(BotPerfilUsuario, "777") is None
    _decir(db, "acepto")
    assert "America/Santiago" in _decir(db, "estoy en Chile") and "estilo corto" in _decir(db, "responde corto") and "goles, ambos marcan" in _decir(db, "me interesan goles y ambos marcan")
    p = db.get(BotPerfilUsuario, "777")                                              # la misma identidad que el bot de partidos
    assert (p.zona_horaria, p.estilo, p.mercados) == ("America/Santiago", "corto", "goles|ambos marcan")
    ver = _decir(db, "mi perfil")
    assert "America/Santiago" in ver and "corto" in ver and "goles, ambos marcan" in ver


def test_una_zona_que_no_existe_no_se_guarda_y_explica_como_decirla(db):
    bot_memoria_repo.aceptar(db, "777")
    r = _decir(db, "mi zona horaria es Marte")
    assert "No reconozco" in r and db.get(BotPerfilUsuario, "777") is None
    assert agent_perfil.interpretar("estoy en el estadio") is None                      # esto es conversación, no un perfil


def test_el_tope_de_mercados_da_error_en_vez_de_truncar(db):
    bot_memoria_repo.aceptar(db, "777")
    r = agent_perfil.aplicar(db, TG, "mercados", "a|b|c|d|e")
    assert "tope" in r.lower() and db.get(BotPerfilUsuario, "777") is None


def test_borrar_el_perfil_y_olvidame_lo_eliminan(db):
    bot_memoria_repo.aceptar(db, "777")
    _decir(db, "responde corto")
    assert "Borré tu perfil" in _decir(db, "borra mi perfil") and db.get(BotPerfilUsuario, "777") is None
    assert "No tenías" in _decir(db, "borra mi perfil")
    _decir(db, "responde corto")
    assert bot_memoria_repo.olvidar(db, "777")["bot_perfil_usuario"] == 1 and db.get(BotPerfilUsuario, "777") is None
    _decir(db, "acepto")
    bot_memoria_repo.aceptar(db, "777")
    _decir(db, "responde corto")
    bot_memoria_repo.revocar(db, "777")                                              # revocar el consentimiento borra también lo que dependía de él
    assert db.get(BotPerfilUsuario, "777") is None


def test_en_modo_sin_memoria_no_se_guarda_pero_se_puede_ver_y_borrar(db):
    bot_memoria_repo.aceptar(db, "777")
    assert "sin memoria" in _decir(db, "responde corto", incognito=True) and db.get(BotPerfilUsuario, "777") is None
    _decir(db, "responde corto")
    assert "corto" in _decir(db, "mi perfil", incognito=True)


def test_si_la_tabla_falta_el_chat_no_se_rompe(base_migrada):
    s = base_migrada("b8d0f2a4c6e1")()                                                 # la revisión anterior a la tabla del perfil
    bot_memoria_repo.aceptar(s, "777")
    assert "No pude guardar" in _decir(s, "responde corto")
    assert agent_perfil.perfil(s, TG) is None and agent_perfil.instantanea_para_ia(s, TG) == "" and agent_perfil.zona_de(s, TG) is None
    assert _decir(s, "hola")
    s.close()


# ---------------------------------------------------------------- instantánea para la IA
def test_la_instantanea_para_la_ia_resume_lo_guardado_sin_tocar_cifras(db):
    assert agent_perfil.instantanea_para_ia(db, TG) == ""
    bot_memoria_repo.aceptar(db, "777")
    _decir(db, "responde corto")
    _decir(db, "estoy en Madrid")
    t = agent_perfil.instantanea_para_ia(db, TG)
    assert "pocas líneas" in t and "Europe/Madrid" in t and "nunca para cambiar cifras" in t


def test_el_prompt_de_la_ia_lleva_las_preferencias_del_usuario(db, monkeypatch):
    bot_memoria_repo.aceptar(db, "777")
    _decir(db, "responde corto")
    prompts = []

    async def generar(prompt, max_tokens=700, rol="bot"):
        prompts.append(prompt)
        return "El VAR ayuda al árbitro.", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "abierto")
    asyncio.run(agent_runtime.procesar_mensaje(db, TG, "explicame que es el var", None, "telegram_agent", True, False))
    assert prompts and "responde en pocas líneas" in prompts[0]


# ---------------------------------------------------------------- zona horaria en los avisos
def test_la_hora_se_convierte_a_la_zona_de_la_persona():
    assert agent_perfil.hora_para("16:00", "2026-11-20", ZoneInfo("America/Bogota")) == "14:00"
    assert agent_perfil.hora_para("16:00", "2026-11-20", ZoneInfo("Europe/Madrid")) == "20:00"
    assert agent_perfil.hora_para("16:00", "2026-11-20", None) == "16:00" and agent_perfil.hora_para(None, "2026-11-20", ZoneInfo("Europe/Madrid")) is None
    assert agent_perfil.hora_para("hora rara", "2026-11-20", ZoneInfo("Europe/Madrid")) == "hora rara"


@pytest.fixture()
def partidos(db, monkeypatch):
    db.add(PartidoDia(match_id="1", fecha="2026-11-20", status="scheduled", liga_nombre="LaLiga", local="Real Madrid", visitante="Getafe", hora_chile="16:00"))
    db.commit()

    def listar(d, fecha):
        return {"partidos": [{"match_id": "1", "liga": "LaLiga", "local": "Real Madrid", "visitante": "Getafe", "hora_chile": "16:00"}]}

    monkeypatch.setattr(av.pronosticables, "listar_pronosticables", listar)


def _enviados():
    cola = []

    async def enviar(client, chat_id, texto):
        cola.append((chat_id, texto))
        return True

    return cola, enviar


def _siguiendo(db):
    _decir(db, "acepto")
    _decir(db, "sigue al Real Madrid")
    _decir(db, "activa los avisos")


def test_el_aviso_llega_con_la_hora_de_la_zona_de_la_persona(db, partidos):
    _siguiendo(db)
    _decir(db, "mi zona horaria es America/Bogota")
    cola, enviar = _enviados()
    asyncio.run(av.enviar_avisos(db, None, "2026-11-20", enviar, None, datetime(2026, 11, 20, 12, 0, tzinfo=CHILE)))
    assert "(14:00)" in cola[0][1] and "(16:00)" not in cola[0][1]


def test_el_horario_activo_se_mide_en_la_zona_de_cada_persona(db, partidos):
    _siguiendo(db)
    _decir(db, "mi zona horaria es Asia/Tokyo")                                       # las 12:00 de Chile son las 00:00 allí
    cola, enviar = _enviados()
    r = asyncio.run(av.enviar_avisos(db, None, "2026-11-20", enviar, None, datetime(2026, 11, 20, 12, 0, tzinfo=CHILE)))
    assert cola == [] and r["candidatos"] == 0
    _decir(db, "mi zona horaria es America/Santiago")
    assert asyncio.run(av.enviar_avisos(db, None, "2026-11-20", enviar, None, datetime(2026, 11, 20, 12, 0, tzinfo=CHILE)))["enviados"] == 1


# ---------------------------------------------------------------- MS-10: la retroalimentación ajusta el estilo y se revierte
@pytest.mark.parametrize("frase, estilo", [("más corto", "corto"), ("muy largo", "corto"), ("sin tanto detalle", "corto"), ("más técnico", "tecnico"), ("explícame más", "tecnico"), ("más detalle", "tecnico"),
                                           ("como antes", "normal"), ("menos técnico", "normal"), ("estilo normal", "normal")])
def test_la_retroalimentacion_se_entiende(frase, estilo):
    assert agent_perfil.interpretar(frase) == ("estilo", estilo)


@pytest.mark.parametrize("frase", ["más corto el pase", "como antes de ayer jugaba mejor el madrid", "muy largo el partido", "explícame más sobre el var", "hola"])
def test_una_frase_de_futbol_con_las_mismas_palabras_no_cambia_el_estilo(frase):
    assert agent_perfil.interpretar(frase) is None


def test_el_estilo_cambia_en_la_siguiente_respuesta_de_la_ia_y_se_puede_revertir(db, monkeypatch):
    prompts = []

    async def generar(prompt, max_tokens=700, rol="bot"):
        prompts.append(prompt)
        return "El VAR ayuda al árbitro.", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "abierto")
    bot_memoria_repo.aceptar(db, "777")

    def pregunta():
        asyncio.run(agent_runtime.procesar_mensaje(db, TG, "explicame que es el var", None, "telegram_agent", True, False))
        return prompts[-1]

    assert "pocas líneas" not in pregunta()
    assert "estilo corto" in _decir(db, "más corto")
    assert "pocas líneas" in pregunta()                                   # la siguiente respuesta ya lo usa
    _decir(db, "más técnico")
    assert "pocas líneas" not in pregunta() and "detalle técnico" in prompts[-1]
    assert "estilo normal" in _decir(db, "como antes")
    assert "pocas líneas" not in pregunta() and "detalle técnico" not in prompts[-1]
    assert db.get(BotPerfilUsuario, "777").estilo == "normal"


def test_la_retroalimentacion_sin_consentimiento_pide_aceptar_y_no_guarda(db):
    assert "acepto" in _decir(db, "más corto").lower() and db.get(BotPerfilUsuario, "777") is None
