"""Tanda 6: canal de los avisos y sus ajustes, vía sin preguntar, nota de los mercados de goles (MP-11) y la memoria del modelo en el perfil de un equipo (MP-4).

La memoria del equipo se prueba sobre una base de las MIGRACIONES REALES con un modelo activo y su estado en `ml_estado_vivo`; solo la herramienta de conocimiento va simulada en el límite."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.api.core.config import settings
from backend.api.ml.laplace import entrenamiento
from backend.api.models.ml_modelo import MlEstadoVivo, MlModelo
from backend.api.services import agent_modelo_equipo, agent_runtime, avisos_favoritos as av, mensajes_analisis, telegram_client
from backend.api.services.agent_runtime_prompts import _mercados_de_goles
from backend.tests._requisitos import requiere_conocimiento_equipos

CHILE = ZoneInfo("America/Santiago")


# ---------------------------------------------------------------- canal de los avisos
@pytest.mark.parametrize("canal, token_agente, esperado", [("agente", "TOKEN-AGENTE", "TOKEN-AGENTE"), ("agente", "", None), ("bot", "TOKEN-AGENTE", None)])
def test_los_avisos_salen_por_el_bot_que_dice_la_configuracion(monkeypatch, canal, token_agente, esperado):
    vistos = []

    async def falso(client, chat_id, texto, *a, token=None, **k):
        vistos.append(token)
        return True

    monkeypatch.setattr(telegram_client, "enviar_mensaje", falso)
    monkeypatch.setattr(settings, "AVISOS_CANAL", canal)
    monkeypatch.setattr(settings, "AGENT_TELEGRAM_BOT_TOKEN", token_agente)
    assert asyncio.run(av.enviar_por_canal(None, "777", "hola")) is True and vistos == [esperado]


def test_el_cliente_de_telegram_usa_el_token_pedido_o_el_del_bot(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "DEL-BOT")
    assert "botDEL-BOT/sendMessage" in telegram_client._url("sendMessage") and "botOTRO/sendMessage" in telegram_client._url("sendMessage", "OTRO")


def test_el_horario_de_los_avisos_se_configura(monkeypatch):
    madrugada = datetime(2026, 11, 20, 5, 0, tzinfo=CHILE)
    assert av.en_horas_activas(madrugada) is False
    monkeypatch.setattr(settings, "AVISOS_HORA_INICIO", 0)
    monkeypatch.setattr(settings, "AVISOS_HORA_FIN", 24)
    assert av.en_horas_activas(madrugada) is True


def test_los_avisos_vienen_encendidos_pero_solo_para_quien_los_activo():
    assert settings.AVISOS_FAVORITOS is True and settings.AVISOS_CANAL in ("agente", "bot")


# ---------------------------------------------------------------- vía sin preguntar
def test_con_la_via_sin_preguntar_el_agente_pronostica_directo_y_respeta_solo_ia(monkeypatch):
    frase = agent_runtime._normalizar_humano("quien gana Barcelona vs PSG")
    assert agent_runtime._respuesta_reglas(frase, False)[2] == "agent.prediction_choice"            # por defecto sigue preguntando
    monkeypatch.setattr(settings, "AGENT_PREGUNTAR_VIA", False)
    assert agent_runtime._respuesta_reglas(frase, False)[2] == "sports.predict"
    assert agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano("prediccion solo ia Barcelona vs PSG"), False)[2] == "agent.ai_prediction"


# ---------------------------------------------------------------- MP-11: nota de los mercados de goles
def test_los_mercados_de_goles_llevan_la_nota_de_que_donde_hay_cuotas_la_cuota_es_mejor():
    assert mensajes_analisis._goles_validados({"btts_si": 0.5, "mas_2_5": 0.55}).endswith(mensajes_analisis.NOTA_GOLES)
    assert "cuota es mejor guía" in _mercados_de_goles({"btts_si": 0.5})
    solo_marcador = {"marcador_mas_probable": "1-0"}
    assert mensajes_analisis.NOTA_GOLES not in mensajes_analisis._goles_validados(solo_marcador) and "cuota" not in _mercados_de_goles(solo_marcador)
    assert mensajes_analisis._goles_validados({}) == "" and _mercados_de_goles({}) == ""


# ---------------------------------------------------------------- MP-4: la memoria del modelo en el perfil del equipo
@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    agent_modelo_equipo.limpiar_cache()
    try:
        yield s
    finally:
        s.close()
        agent_modelo_equipo.limpiar_cache()


def _estado(equipos: dict[str, int]):
    return entrenamiento.EstadoLiga.de_dict({"elo": {e: 1500.0 + i * 40 for i, e in enumerate(equipos)}, "gf": {e: 1.6 for e in equipos}, "gc": {e: 1.1 for e in equipos}, "n": dict(equipos),
                                             "media_local": 1.5, "media_visita": 1.1, "total_partidos": 200, "forma": {e: 1.9 for e in equipos}})


@pytest.fixture()
def modelo(db):
    m = MlModelo(nombre="m", version="v1", familia="x", tarea="1x2", estado="activo", creado_en="2026-11-13T00:00:00")
    db.add(m)
    db.commit()
    for liga, equipos in (("ARG", {"Boca Juniors": 40, "River Plate": 38, "Barcelona SC": 3}), ("ESP", {"Barcelona": 38, "Sevilla": 38}), ("ECU", {"Barcelona SC": 20})):
        db.add(MlEstadoVivo(modelo_id=m.id, liga=liga, estado_json=json.dumps(_estado(equipos).a_dict()), hasta_dia=1, partidos=sum(equipos.values()), actualizado_en="2026-11-13T06:40:00"))
    db.commit()
    return m


def test_la_linea_de_memoria_dice_rating_goles_forma_partidos_y_fecha(db, modelo):
    t = agent_modelo_equipo.linea_de_equipo(db, "Boca Juniors")
    assert t.startswith("\nMemoria del modelo: rating ") and "marca 1.60 y recibe 1.10 goles por partido" in t and "40 partidos en memoria" in t and "actualizado 2026-11-13" in t
    assert "poco fiable" not in t


def test_un_equipo_de_pocos_partidos_se_marca_poco_fiable(db, modelo):
    db.query(MlEstadoVivo).filter_by(liga="ARG").update({"estado_json": json.dumps(_estado({"Boca Juniors": 4}).a_dict())})
    db.commit()
    assert "poco fiable" in agent_modelo_equipo.linea_de_equipo(db, "Boca Juniors")


def test_un_nombre_ambiguo_o_desconocido_no_inventa_nada(db, modelo):
    assert "40 partidos" not in agent_modelo_equipo.linea_de_equipo(db, "Barcelona SC") and "20 partidos en memoria" in agent_modelo_equipo.linea_de_equipo(db, "Barcelona SC")
    assert agent_modelo_equipo.linea_de_equipo(db, "Equipo Inventado") == ""
    assert agent_modelo_equipo.linea_de_equipo(db, "Rio") == ""                               # menos de 4 letras
    indice = {"barcelona": [("ESP", "Barcelona", 38), ("UCL", "Barcelona", 8)], "barcelona sc": [("ARG", "Barcelona SC", 3), ("ECU", "Barcelona SC", 20)]}
    assert agent_modelo_equipo._buscar(indice, "barcelona sc") == ("ECU", "Barcelona SC")         # el mismo nombre en dos competiciones: la de más partidos
    assert agent_modelo_equipo._buscar(indice, "barcelona") == ("ESP", "Barcelona")                 # exacto gana a «Barcelona SC», que también lo contiene
    assert agent_modelo_equipo._buscar({"barcelona": [("ESP", "Barcelona", 38)], "barcelona sc": [("ECU", "Barcelona SC", 20)]}, "barcel") is None   # dos nombres distintos que cuadran: ambiguo


def test_sin_modelo_activo_o_con_la_base_rota_el_perfil_no_falla(db):
    assert agent_modelo_equipo.linea_de_equipo(db, "Boca Juniors") == ""


@requiere_conocimiento_equipos   # el perfil de un equipo necesita el conocimiento por equipo (no se publica)
def test_el_agente_agrega_la_memoria_del_modelo_al_perfil_del_equipo(db, modelo, monkeypatch):
    async def herramienta(nombre, argumentos, **_k):
        return {"texto": f"Perfil de {argumentos.get('team')}: club argentino."}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "u", "perfil de Boca Juniors", None, "web", False, False))
    assert r["herramienta"] == "knowledge.team_profile" and "Perfil de" in r["respuesta"] and "Memoria del modelo: rating" in r["respuesta"]
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "u", "perfil de Equipo Inventado FC", None, "web", False, False))
    assert "Memoria del modelo" not in r["respuesta"]
