"""Rutas de herramienta, degradación y límites de `procesar_mensaje` (sin red, IA ni claves reales)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from backend.tests._requisitos import requiere_conocimiento_equipos

from backend.api.core.config import settings
from backend.api.models.agent_runtime import AgentMemory, AgentMessage, AgentRun, AgentTask
from backend.api.models.predicciones import PrediccionVarianteAgente
from backend.api.services import agent_runtime
from backend.api.services.agent_guard import LimiteExcedido
from backend.api.services.ai_client import AnalisisIAError

PARTIDO = {"match_id": "m1", "local": "Barcelona", "visitante": "PSG", "liga": "Champions"}


def _procesar(db, mensaje, *, usar_ia=False, session_id=None, es_admin=False):
    return asyncio.run(agent_runtime.procesar_mensaje(db, "u1", mensaje, session_id, "web", usar_ia, es_admin))


def _forzar_regla(monkeypatch, herramienta, respuesta="base", modo="reglas"):
    monkeypatch.setattr(agent_runtime, "_respuesta_reglas", lambda *_a, **_k: (respuesta, modo, herramienta))


def _ultimo_run(db):
    return db.query(AgentRun).order_by(AgentRun.creado_en.desc()).first()


def _herramienta_que_falla(monkeypatch):
    async def falla(*_a, **_k):
        raise RuntimeError("bot caído")

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", falla)


def test_mensaje_vacio_se_rechaza_sin_crear_nada(db_session):
    with pytest.raises(ValueError):
        _procesar(db_session, "   ")
    assert db_session.query(AgentMessage).count() == 0


def test_politica_activa_bloquea_el_tema_y_no_llama_a_la_ia(db_session, monkeypatch):
    monkeypatch.setattr(agent_runtime, "tema_bloqueado", lambda *_a: True)

    async def no_debe_llamarse(*_a, **_k):
        raise AssertionError("la IA no debe intervenir en un bloqueo")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", no_debe_llamarse)
    r = _procesar(db_session, "quien gana Barcelona vs PSG", usar_ia=True)
    assert r["herramienta"] == "agent.policy_block"
    assert r["modo"] == "politica"
    assert "fuera de mi alcance" in r["respuesta"]


def test_prediccion_solo_ia_sin_permiso_explica_como_activarla(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "agent.ai_prediction")
    r = _procesar(db_session, "prediccion solo IA Barcelona vs PSG", usar_ia=False)
    assert "Permitir IA" in r["respuesta"]
    assert r["modo"] == "reglas"
    assert db_session.query(PrediccionVarianteAgente).count() == 0


def _ia_scout(monkeypatch, texto='{"pick": "Barcelona", "marcador_probable": "2-1", "confianza": "media"}'):
    async def ia(prompt, **_k):
        return texto, "proveedor", "modelo-x"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)


def test_prediccion_solo_ia_guarda_hipotesis_identificada_como_ia(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "agent.ai_prediction")
    _ia_scout(monkeypatch)

    async def herramienta(nombre, argumentos, *, es_admin=False):
        return {"fixtures": [PARTIDO]}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = _procesar(db_session, "prediccion solo IA Barcelona vs PSG", usar_ia=True)
    assert r["herramienta"] == "agent.ai_prediction"
    assert r["modo"].startswith("ia_experimental")
    assert "No sustituye el análisis estadístico" in r["respuesta"]
    fila = db_session.query(PrediccionVarianteAgente).one()
    assert fila.via == "ai_scout"
    assert fila.partido_id == "m1"
    assert fila.local == "Barcelona" and fila.visitante == "PSG"


def test_prediccion_solo_ia_se_guarda_igual_si_el_bot_no_resuelve_el_partido(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "agent.ai_prediction")
    _ia_scout(monkeypatch)
    _herramienta_que_falla(monkeypatch)
    r = _procesar(db_session, "prediccion solo IA Barcelona vs PSG", usar_ia=True)
    assert r["herramienta"] == "agent.ai_prediction"
    fila = db_session.query(PrediccionVarianteAgente).one()
    assert fila.partido_id is None


def test_ia_caida_degrada_a_reglas_y_marca_la_corrida_parcial(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def ia_caida(*_a, **_k):
        raise AnalisisIAError("sin proveedor")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia_caida)
    _forzar_regla(monkeypatch, None, respuesta="respuesta local")
    monkeypatch.setattr(agent_runtime, "_fuera_de_alcance", lambda *_a: False)
    r = _procesar(db_session, "cuéntame algo", usar_ia=True)
    assert r["modo"] == "reglas_fallback"
    assert r["respuesta"].startswith("La IA no está disponible ahora")
    assert "respuesta local" in r["respuesta"]
    assert _ultimo_run(db_session).status == "partial"


def test_conversacion_libre_usa_la_respuesta_de_la_ia(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def ia(prompt, **_k):
        return "respuesta del modelo", "prov", "mod"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    _forzar_regla(monkeypatch, None)
    monkeypatch.setattr(agent_runtime, "_fuera_de_alcance", lambda *_a: False)
    r = _procesar(db_session, "háblame de ti", usar_ia=True)
    assert r["herramienta"] == "llm.respond"
    assert r["modo"] == "ia · prov/mod"
    assert r["respuesta"].startswith("respuesta del modelo") and "no verificada por el modelo de Laplace" in r["respuesta"]


def test_ia_desactivada_por_configuracion_no_se_llama(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", False)

    async def no_debe_llamarse(*_a, **_k):
        raise AssertionError("IA desactivada")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", no_debe_llamarse)
    _forzar_regla(monkeypatch, None, respuesta="local")
    r = _procesar(db_session, "háblame de ti", usar_ia=True)
    assert r["respuesta"] == "local"


def test_catalogo_de_ligas_cuenta_entradas_y_degrada_si_falla(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "sports.list_leagues")

    async def ok(nombre, argumentos, *, es_admin=False):
        return {"leagues": [1, 2, 3]}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", ok)
    assert "3 entradas de ligas" in _procesar(db_session, "ligas")["respuesta"]

    _herramienta_que_falla(monkeypatch)
    r = _procesar(db_session, "ligas")
    assert "No pude consultar ahora el catálogo" in r["respuesta"]
    run = _ultimo_run(db_session)
    assert run.status == "failed"
    assert json.loads(run.output_json)["tool_failed"] is True


def test_ligas_con_actividad_sin_partidos_lo_dice(db_session, monkeypatch):
    async def vacio(nombre, argumentos, *, es_admin=False):
        return {"fixtures": []}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", vacio)
    r = _procesar(db_session, "dime las ligas que juegan hoy")
    assert "No encontré partidos disponibles" in r["respuesta"]


def test_ligas_con_actividad_limita_el_listado_a_20(db_session, monkeypatch):
    async def muchas(nombre, argumentos, *, es_admin=False):
        return {"fixtures": [{"league": f"Liga {i:02d}"} for i in range(23)] + [{"liga": "  "}]}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", muchas)
    r = _procesar(db_session, "dime las ligas que juegan hoy")
    assert "24 partidos en 24 ligas" in r["respuesta"]
    assert "y 4 ligas más" in r["respuesta"]


def test_ligas_con_actividad_degrada_si_el_bot_falla(db_session, monkeypatch):
    _herramienta_que_falla(monkeypatch)
    r = _procesar(db_session, "dime las ligas que juegan hoy")
    assert "No pude consultar las ligas con actividad" in r["respuesta"]
    assert _ultimo_run(db_session).status == "failed"


def test_lista_de_partidos_cuenta_y_degrada(db_session, monkeypatch):
    async def ok(nombre, argumentos, *, es_admin=False):
        return {"fixtures": [PARTIDO, PARTIDO], "date": "20261110"}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", ok)
    r = _procesar(db_session, "partidos de hoy")
    assert r["herramienta"] == "sports.list_fixtures"
    assert "Encontré 2 partidos para la fecha 20261110" in r["respuesta"]

    _herramienta_que_falla(monkeypatch)
    assert "No pude consultar los partidos ahora" in _procesar(db_session, "partidos de hoy")["respuesta"]


def test_top_picks_con_y_sin_publicados_y_con_fallo(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "sports.list_top_picks")

    async def con_picks(nombre, argumentos, *, es_admin=False):
        return {"picks": [{"local": "A", "visitante": "B", "pick_final": "Local"}, {"pick": "x"}]}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", con_picks)
    r = _procesar(db_session, "top picks")["respuesta"]
    assert "A vs B: Local" in r and "? vs ?: x" in r

    async def sin_picks(nombre, argumentos, *, es_admin=False):
        return {"picks": []}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", sin_picks)
    assert "Todavía no hay Top Picks" in _procesar(db_session, "top picks")["respuesta"]

    _herramienta_que_falla(monkeypatch)
    assert "No pude consultar los Top Picks" in _procesar(db_session, "top picks")["respuesta"]


def test_prediccion_sin_formato_de_partido_pide_el_formato(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "sports.predict")
    r = _procesar(db_session, "predice algo")
    assert r["herramienta"] == "sports.match_required"
    assert "equipo local vs equipo visitante" in r["respuesta"]


def test_partido_inexistente_en_el_bot_se_informa(db_session, monkeypatch):
    async def sin_partido(nombre, argumentos, *, es_admin=False, **_k):
        return {"fixtures": []}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", sin_partido)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG")
    assert r["herramienta"] == "sports.match_not_found"
    assert "No encontré un partido disponible" in r["respuesta"]


def test_cuotas_del_partido_se_muestran_o_avisan_si_no_hay(db_session, monkeypatch):
    estado = {"odds": {"local": 1.9}}

    async def herramienta(nombre, argumentos, *, es_admin=False, **_k):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [PARTIDO]}
        return {"odds": estado["odds"]}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    assert "Cuotas disponibles para Barcelona vs PSG" in _procesar(db_session, "cuotas Barcelona vs PSG")["respuesta"]
    estado["odds"] = {}
    assert "sin cuotas cargadas" in _procesar(db_session, "cuotas Barcelona vs PSG")["respuesta"]


def test_limite_de_predicciones_no_cuenta_como_fallo_de_herramienta(db_session, monkeypatch):
    async def herramienta(nombre, argumentos, *, es_admin=False, **_k):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [PARTIDO]}
        raise LimiteExcedido("Límite diario de predicciones")

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG")
    assert r["herramienta"] == "sports.rate_limited"
    assert "inténtalo más tarde" in r["respuesta"]
    assert _ultimo_run(db_session).status == "succeeded"


def test_fallo_del_bot_en_prediccion_no_inventa_resultado_ni_llama_a_la_ia(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_IA_PURA_AUTOMATICA", False)  # con la hipótesis automática apagada el comportamiento es el de siempre

    async def ia(*_a, **_k):
        raise AssertionError("no se redacta sobre un fallo")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    _herramienta_que_falla(monkeypatch)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG", usar_ia=True)
    assert "no invento un resultado" in r["respuesta"]
    assert _ultimo_run(db_session).status == "failed"


def _bot_con_prediccion(monkeypatch):
    async def herramienta(nombre, argumentos, *, es_admin=False, **_k):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [PARTIDO]}
        return {"prediction": {"consenso": {"pick_final": "Barcelona", "confianza_final": "MEDIA"}}}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)


def test_redaccion_ia_con_cifras_ajenas_se_descarta(db_session, monkeypatch):
    _bot_con_prediccion(monkeypatch)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def ia(prompt, **_k):
        return "Barcelona gana con 99.9% de seguridad y cuota 7.77", "p", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG", usar_ia=True)
    assert "99.9" not in r["respuesta"]
    assert r["modo"] == "reglas · ia_descartada p/m"
    assert "pick Barcelona" in r["respuesta"]


def test_redaccion_ia_fiel_reemplaza_el_texto(db_session, monkeypatch):
    _bot_con_prediccion(monkeypatch)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(agent_runtime, "_redaccion_fiel", lambda *_a: True)

    async def ia(prompt, **_k):
        return "  Redacción amable  ", "p", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG", usar_ia=True)
    assert r["respuesta"] == "Redacción amable"
    assert r["modo"] == "ia · p/m"


def test_conectar_con_el_bot_segun_disponibilidad(db_session, monkeypatch):
    async def disponible():
        return {"available": True, "capabilities": {"capabilities": ["fútbol", "tenis"]}}

    monkeypatch.setattr(agent_runtime, "consultar_capacidades_deportivas", disponible)
    r = _procesar(db_session, "conecta con el bot deportivo")
    assert r["herramienta"] == "sports.capabilities"
    assert "fútbol, tenis" in r["respuesta"]

    async def caido():
        return {"available": False}

    monkeypatch.setattr(agent_runtime, "consultar_capacidades_deportivas", caido)
    r = _procesar(db_session, "conecta con el bot deportivo")
    assert r["herramienta"] == "sports.route_unavailable"
    assert "no está disponible" in r["respuesta"]


@requiere_conocimiento_equipos
def test_conocimiento_responde_de_forma_determinista_sin_ia(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)

    async def ia(*_a, **_k):
        raise AssertionError("respuesta determinista")

    async def herramienta(nombre, argumentos, *, es_admin=False):
        return {"texto": "Perfil de Boca: ..."}

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = _procesar(db_session, "perfil de Boca", usar_ia=True)
    assert r["respuesta"] == "Perfil de Boca: ..."
    assert r["herramienta"] == "knowledge.team_profile"


def test_conocimiento_sin_argumentos_entendibles_orienta_al_usuario(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "knowledge.glossary")
    r = _procesar(db_session, "xyz qwerty")
    assert "No pude entender qué equipo, liga o término" in r["respuesta"]


def test_tareas_del_usuario_listadas_y_vacias(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "agent.tasks")
    assert "Todavía no tienes tareas" in _procesar(db_session, "mis tareas")["respuesta"]
    ahora = datetime(2026, 11, 10, 12, 0).isoformat()
    db_session.add(AgentTask(id="t1", user_id="u1", kind="recordatorio", status="pending", creado_en=ahora))
    db_session.add(AgentTask(id="t2", user_id="otro", kind="ajena", status="pending", creado_en=ahora))
    db_session.flush()
    r = _procesar(db_session, "mis tareas")["respuesta"]
    assert "recordatorio: pending" in r
    assert "ajena" not in r


def test_recuerdos_solo_activos_normales_y_propios(db_session, monkeypatch):
    _forzar_regla(monkeypatch, "agent.memory")
    assert "Aún no tengo recuerdos" in _procesar(db_session, "mis recuerdos")["respuesta"]
    ahora = datetime(2026, 11, 10, 12, 0).isoformat()
    base = {"owner_id": "u1", "scope": "user", "kind": "preferencia", "activo": 1, "sensibilidad": "normal", "creado_en": ahora, "actualizado_en": ahora}
    filas = (("equipo", "Hincha de Colo-Colo", {}), ("secreto", "dato sensible", {"sensibilidad": "alta"}), ("viejo", "inactivo", {"activo": 0}))
    for clave, texto, extra in filas:
        db_session.add(AgentMemory(topic_key=clave, content=texto, **{**base, **extra}))
    db_session.flush()
    r = _procesar(db_session, "mis recuerdos")["respuesta"]
    assert "Hincha de Colo-Colo" in r
    assert "dato sensible" not in r and "inactivo" not in r


def test_sesion_ajena_no_se_reutiliza_y_el_titulo_se_acota(db_session):
    primera = _procesar(db_session, "hola " + "x" * 200)
    propia = asyncio.run(agent_runtime.procesar_mensaje(db_session, "otro-usuario", "hola", primera["session_id"], "web", False, False))
    assert propia["session_id"] != primera["session_id"]
    sesion = agent_runtime._sesion(db_session, "u1", primera["session_id"], "web")
    assert len(sesion.title) == 80


def test_si_caen_el_bot_y_el_modelo_la_ia_pura_se_ofrece_rotulada_como_no_calculada(db_session, monkeypatch):
    """MA-14: con la IA permitida en el turno, sin bot ni modelo se da una hipótesis verbal, sin porcentajes y con la etiqueta de que no la calculó Laplace."""
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_IA_PURA_AUTOMATICA", True)
    _herramienta_que_falla(monkeypatch)

    async def ia(prompt, **_k):
        return ('{"pick": "Barcelona", "marcador_probable": "2-1", "confianza": "media", "razon": "Llega mejor, 70% de posesión", "incertidumbre": "sin datos recientes"}', "proveedor", "modelo")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG", usar_ia=True)
    assert "NO calculada por Laplace" in r["respuesta"] and "Se inclina por: Barcelona" in r["respuesta"] and "2-1" not in r["respuesta"] and r["herramienta"] == "agent.ai_prediction"


def test_con_el_bot_caido_el_agente_responde_con_el_modelo_sin_llamar_a_la_ia(db_session, monkeypatch):
    """MA-11: el modelo solo necesita los nombres; que el bot esté caído ya no deja al usuario sin pronóstico."""
    modelo = {"ok": True, "p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}, "goles_esperados": {"local": 1.6, "visitante": 1.1, "total": 2.7}, "btts": {"si": 0.5, "no": 0.5},
              "over_under": {"2.5": {"mas": 0.5, "menos": 0.5}}, "marcadores": [{"marcador": "1-1", "prob": 0.12}], "confianza": 0.2, "validados": [], "fuente": "modelo_laplace", "degradado": False, "modelo": None}

    async def herramienta(nombre, argumentos, *, es_admin=False, **_k):
        if nombre == "modelo.pronosticar":
            return modelo
        raise RuntimeError("bot caído")

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    r = _procesar(db_session, "prediccion bot Barcelona vs PSG", usar_ia=False)
    assert "solo tengo la lectura del modelo Laplace" in r["respuesta"] and "local 50.0%" in r["respuesta"] and r["herramienta"] == "sports.predict"
    assert _ultimo_run(db_session).status == "succeeded"
