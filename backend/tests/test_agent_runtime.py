"""Regresiones del routing determinista del agente Laplace."""
from __future__ import annotations

import asyncio
import json

from backend.api.core.config import settings
from backend.api.models.predicciones import PrediccionVarianteAgente
from backend.api.routers.agent import PROVIDER_CATALOG
from backend.api.services import agent_runtime


def test_catalogo_agente_ofrece_ollama_cloud_y_no_ollama_local():
    proveedores = {item[0]: item for item in PROVIDER_CATALOG}
    assert "ollama" not in proveedores
    assert proveedores["ollama_cloud"][2:4] == ("OLLAMA_CLOUD_MODEL", "OLLAMA_API_KEY")


def test_saludo_es_natural_y_declara_modo_local():
    respuesta, modo, herramienta = agent_runtime._respuesta_reglas("hola", False)
    assert modo == "reglas"
    assert herramienta == "agent.greeting"
    assert "soy Laplace" in respuesta
    assert "[Sin IA]" in respuesta


def test_ligas_de_hoy_prioriza_los_fixtures_sobre_catalogo_estatico():
    _, _, herramienta = agent_runtime._respuesta_reglas("conecta con el bot y dime las ligas que juegan hoy", False)
    assert herramienta == "sports.list_playing_leagues"


def test_ligas_de_hoy_devuelve_ligas_reales_agrupadas(db_session, monkeypatch):
    async def herramienta(nombre, argumentos, *, es_admin=False):
        assert nombre == "sports.list_fixtures"
        return {
            "fixtures": [
                {"liga": "Chile Primera", "local": "A", "visitante": "B"},
                {"liga": "Chile Primera", "local": "C", "visitante": "D"},
                {"liga": "Copa Regional", "local": "E", "visitante": "F"},
            ]
        }

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    resultado = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "dime las ligas que juegan hoy", None, "web", False, False
    ))

    assert resultado["herramienta"] == "sports.list_playing_leagues"
    assert "Chile Primera (2)" in resultado["respuesta"]
    assert "Copa Regional (1)" in resultado["respuesta"]


def test_prediccion_ambigua_pide_elegir_bot_o_ia():
    respuesta, _, herramienta = agent_runtime._respuesta_reglas("quien gana Barcelona vs PSG", False)
    assert herramienta == "agent.prediction_choice"
    assert "bot" in respuesta.lower()
    assert "ia" in respuesta.lower()


def test_eleccion_ia_reusa_el_partido_anterior_de_la_sesion(db_session):
    resultado_inicial = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "quien gana Barcelona vs PSG", None, "web", False, False
    ))
    resultado_eleccion = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "IA", resultado_inicial["session_id"], "web", False, False
    ))
    assert resultado_eleccion["herramienta"] == "agent.ai_prediction"
    assert "Activa" in resultado_eleccion["respuesta"]


def test_eleccion_bot_reusa_el_partido_anterior_de_la_sesion(db_session, monkeypatch):
    resultado_inicial = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "prediccion Barcelona vs PSG", None, "web", False, False
    ))

    async def herramienta(nombre, argumentos, *, es_admin=False, authorization=None, usuario=None):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [{"match_id": "m1", "local": "Barcelona", "visitante": "PSG", "liga": "Champions"}]}
        assert nombre == "sports.predict"
        assert authorization == "Bearer prueba"
        return {"prediction": {"consenso": {"pick_final": "Barcelona", "confianza_final": "MEDIA"}}}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    resultado = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "bot", resultado_inicial["session_id"], "web", False, False, "Bearer prueba"
    ))

    assert resultado["herramienta"] == "sports.predict"
    assert "pick Barcelona" in resultado["respuesta"]


def test_eleccion_no_duplica_el_prefijo_de_prediccion(db_session):
    inicial = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "prediccion AD Ceuta FC vs Real Sociedad B", None, "web", False, False
    ))
    sesion = agent_runtime._sesion(db_session, "usuario", inicial["session_id"], "web")
    ruta = agent_runtime._eleccion_prediccion_pendiente(db_session, sesion, "bot")
    assert ruta is not None
    assert ruta.endswith("AD Ceuta FC vs Real Sociedad B")
    assert agent_runtime._texto_normalizado(ruta).count("prediccion") == 1


def test_scout_ia_guarda_variante_privada_por_usuario(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def generar(prompt, max_tokens=700, rol="bot"):
        return ('{"pick":"Barcelona","marcador_probable":"2-1","confianza":"media","razon":"hipotesis","incertidumbre":"alta"}', "gemini", "gemini-2.5-flash")

    async def sin_partido(equipos, mensaje, es_admin):
        return {}

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(agent_runtime, "_buscar_partido", sin_partido)
    resultado = asyncio.run(agent_runtime.procesar_mensaje(
        db_session, "usuario", "prediccion solo ia Barcelona vs PSG", None, "web", True, False
    ))
    fila = db_session.query(PrediccionVarianteAgente).one()
    assert fila.partido_id is None and fila.liga is None   # sin partido resuelto se guarda igual
    assert resultado["herramienta"] == "agent.ai_prediction"
    assert (fila.user_id, fila.via, fila.pick, fila.marcador_probable, fila.proveedor) == ("usuario", "ai_scout", "Barcelona", "2-1", "gemini")
    assert json.loads(fila.resultado_json)["confianza"] == "media"


def test_scout_ia_guarda_partido_y_liga_cuando_el_bot_lo_resuelve(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def generar(prompt, max_tokens=700, rol="bot"):
        return ('{"pick":"Barcelona","marcador_probable":"2-1","confianza":"media","razon":"x","incertidumbre":"alta"}', "gemini", "gemini-flash-lite-latest")

    async def partido(equipos, mensaje, es_admin):
        return {"match_id": "1234", "local": "Barcelona", "visitante": "PSG", "league": "Champions League"}

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(agent_runtime, "_buscar_partido", partido)
    asyncio.run(agent_runtime.procesar_mensaje(db_session, "usuario", "prediccion solo ia Barcelona vs PSG", None, "web", True, False))
    fila = db_session.query(PrediccionVarianteAgente).one()
    assert (fila.partido_id, fila.liga) == ("1234", "Champions League")


def test_si_resolver_el_partido_falla_la_hipotesis_se_guarda_igual(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def generar(prompt, max_tokens=700, rol="bot"):
        return ('{"pick":"PSG","marcador_probable":"1-2","confianza":"baja","razon":"x","incertidumbre":"alta"}', "groq", "m")

    async def roto(equipos, mensaje, es_admin):
        raise RuntimeError("El bot deportivo no respondió")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(agent_runtime, "_buscar_partido", roto)
    asyncio.run(agent_runtime.procesar_mensaje(db_session, "usuario", "prediccion solo ia Barcelona vs PSG", None, "web", True, False))
    fila = db_session.query(PrediccionVarianteAgente).one()
    assert fila.partido_id is None and fila.pick == "PSG"


def test_router_humano_reconoce_top_pick_y_errores_frecuentes():
    _, _, herramienta = agent_runtime._respuesta_reglas("ke top pick ves mas fuerte mañana", False)
    assert herramienta == "sports.list_top_picks"
    assert agent_runtime._normalizar_humano("ke ligas juegan mañana") == "que ligas juegan mañana"
