"""Seguir equipos y ligas desde el agente (MS-1, MS-2, MS-3): un solo almacén con el bot, identidad común y pronóstico directo para lo que se sigue.

Sobre una base construida con las MIGRACIONES REALES y el agente real (`procesar_mensaje`); solo el exterior (el bot deportivo) va simulado en el límite de la herramienta."""
from __future__ import annotations

import asyncio

import pytest

from backend.api.db import bot_memoria_repo, usuarios_repo
from backend.api.services import agent_runtime, agent_seguimientos

TG = "telegram:777"


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


def _decir(db, texto, user=TG, incognito=False):
    return asyncio.run(agent_runtime.procesar_mensaje(db, user, texto, None, "telegram_agent", False, False, incognito=incognito))


# ---------------------------------------------------------------- interpretar
@pytest.mark.parametrize("texto, esperado", [
    ("sigue al Barcelona", ("seguir_equipo", "barcelona")),
    ("¿Puedes seguir al Atlético de Madrid?", None),                                    # con «?» no es una orden: es una pregunta
    ("por favor sigue al Real Madrid y avísame", ("seguir_equipo", "real madrid")),
    ("quiero seguir la Premier League", ("seguir_liga", "premier league")),
    ("sigue el campeonato chileno", ("seguir_liga", "campeonato chileno")),
    ("deja de seguir al Barcelona", ("dejar", "barcelona")),
    ("¿qué sigo?", ("listar", "")),
    ("mis seguimientos", ("listar", "")),
    ("acepto", ("aceptar", "")),
    ("sigue donde quedamos", None),                                                     # lo resuelve el diálogo, no es un equipo
    ("sigue lloviendo en Santiago", None),
    ("sigue", None),
    ("quien gana Barcelona vs PSG", None),
    ("hola", None),
])
def test_interpretar(texto, esperado):
    assert agent_seguimientos.interpretar(texto) == esperado


def test_la_identidad_comun_junta_telegram_con_el_bot_y_deja_en_paz_a_los_demas():
    assert agent_seguimientos.id_comun("telegram:123") == "123"
    assert agent_seguimientos.id_comun("123") == "123"
    assert agent_seguimientos.id_comun("web-abc") == "web-abc"


# ---------------------------------------------------------------- flujo de punta a punta
def test_sin_consentimiento_pide_aceptar_y_despues_guarda_en_el_almacen_del_bot(db):
    r = _decir(db, "sigue al Barcelona")
    assert r["herramienta"] == "agent.seguimiento" and "acepto" in r["respuesta"].lower()
    assert bot_memoria_repo.equipos_favoritos(db, "777") == []
    assert "guardaré" in _decir(db, "acepto")["respuesta"]
    assert bot_memoria_repo.tiene_consentimiento(db, "777")
    assert "Ahora sigues a Barcelona" in _decir(db, "sigue al Barcelona")["respuesta"]
    assert bot_memoria_repo.equipos_favoritos(db, "777") == ["Barcelona"]          # lo mismo que verá /equipos en el bot
    assert "Barcelona" in _decir(db, "que sigo")["respuesta"]
    assert "Dejé de seguir Barcelona" in _decir(db, "deja de seguir al barcelona")["respuesta"]
    assert bot_memoria_repo.equipos_favoritos(db, "777") == []


def test_lo_que_se_sigue_en_el_bot_lo_ve_el_agente(db):
    bot_memoria_repo.aceptar(db, "888")
    assert bot_memoria_repo.agregar_equipo(db, "888", "Boca Juniors")["ok"]
    assert "Boca Juniors" in _decir(db, "mis seguimientos", user="telegram:888")["respuesta"]


def test_seguir_una_liga_registra_al_usuario_y_queda_en_sus_favoritos_del_bot(db):
    bot_memoria_repo.aceptar(db, "777")
    assert "Ahora sigues Premier League" in _decir(db, "sigue la Premier League")["respuesta"]
    assert usuarios_repo.listar_favoritos_ligas(db, "777") == ["Premier League"]


def test_un_nombre_generico_pide_el_nombre_completo_y_no_guarda_nada(db):
    bot_memoria_repo.aceptar(db, "777")
    r = _decir(db, "sigue al Real")
    assert "no alcanza" in r["respuesta"] and bot_memoria_repo.equipos_favoritos(db, "777") == []


def test_el_limite_de_equipos_se_respeta_con_su_mensaje(db):
    bot_memoria_repo.aceptar(db, "777")
    for nombre in ("Barcelona", "Sevilla", "Valencia", "Villarreal", "Getafe"):
        assert bot_memoria_repo.agregar_equipo(db, "777", nombre)["ok"]
    assert "Máximo" in _decir(db, "sigue al Osasuna")["respuesta"]


def test_en_modo_sin_memoria_no_se_guarda_nada(db):
    bot_memoria_repo.aceptar(db, "777")
    r = _decir(db, "sigue al Barcelona", incognito=True)
    assert "sin memoria" in r["respuesta"] and bot_memoria_repo.equipos_favoritos(db, "777") == []


def test_si_la_base_falla_el_chat_no_se_rompe(db, monkeypatch):
    def roto(*_a, **_k):
        raise RuntimeError("tabla ausente")

    monkeypatch.setattr(bot_memoria_repo, "equipos_favoritos", roto)
    assert agent_seguimientos.seguidos(db, TG) == {"equipos": [], "ligas": []}
    r = _decir(db, "hola")
    assert r["respuesta"]


# ---------------------------------------------------------------- MS-3 pronóstico directo
def test_el_partido_de_un_equipo_seguido_se_pronostica_sin_preguntar_la_via(db, monkeypatch):
    llamadas = []

    async def herramienta(nombre, argumentos, **_k):
        llamadas.append(nombre)
        if nombre == "sports.list_fixtures":
            return {"fixtures": [{"match_id": "m1", "local": "Barcelona", "visitante": "PSG", "liga": "Champions"}]}
        return {"prediction": {"consenso": {"pick_final": "Barcelona", "confianza_final": "MEDIA"}}}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    sin_seguir = _decir(db, "quien gana Barcelona vs PSG")
    assert sin_seguir["herramienta"] == "agent.prediction_choice"                  # sin seguimiento sigue preguntando: no cambia lo que ya andaba
    bot_memoria_repo.aceptar(db, "777")
    bot_memoria_repo.agregar_equipo(db, "777", "Barcelona")
    r = _decir(db, "quien gana Barcelona vs PSG")
    assert r["herramienta"] == "sports.predict" and "sports.predict" in llamadas and "Barcelona" in r["respuesta"]


def test_un_partido_ajeno_a_lo_que_sigues_sigue_preguntando(db):
    bot_memoria_repo.aceptar(db, "777")
    bot_memoria_repo.agregar_equipo(db, "777", "Boca Juniors")
    assert _decir(db, "quien gana Barcelona vs PSG")["herramienta"] == "agent.prediction_choice"


def test_solo_ia_se_respeta_aunque_sigas_al_equipo(db):
    bot_memoria_repo.aceptar(db, "777")
    bot_memoria_repo.agregar_equipo(db, "777", "Barcelona")
    assert _decir(db, "prediccion solo ia Barcelona vs PSG")["herramienta"] == "agent.ai_prediction"
