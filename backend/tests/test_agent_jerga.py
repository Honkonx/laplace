"""MS-7 (jerga y fechas) y MS-8 (nivel «abierto» con IA) del agente. Reglas puras y el agente real (`procesar_mensaje`); solo el proveedor de IA y el bot deportivo van simulados en el límite."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from backend.api.core.config import settings
from backend.api.services import agent_jerga as j, agent_runtime
from backend.tests._requisitos import requiere_conocimiento_equipos

VIERNES = date(2026, 11, 13)


# ---------------------------------------------------------------- MS-7: apodos
@pytest.mark.parametrize("texto, esperado", [
    ("quien gana el barça y los merengues", "quien gana Barcelona y Real Madrid"),
    ("¿Los colchoneros contra el Atleti?", "¿Atlético de Madrid contra Atlético de Madrid?"),
    ("pronostico los citizens contra los gunners", "pronostico Manchester City contra Arsenal"),
    ("el cacique juega mañana", "Colo-Colo juega mañana"),
    ("la vecchia signora y los nerazzurri", "Juventus y Inter"),
    ("hola", "hola"),
    ("millonarios contra los azules", "millonarios contra los azules"),          # apodos ambiguos: nombran a varios equipos, no se tocan
    ("el barcelona vs el madrid", "el barcelona vs el madrid"),                  # los nombres propios no cambian
])
def test_normalizar_apodos(texto, esperado):
    assert j.normalizar_apodos(texto) == esperado


def test_un_apodo_dentro_de_otra_palabra_no_se_reemplaza():
    assert j.normalizar_apodos("el barcaza y juventud") == "el barcaza y juventud"


# ---------------------------------------------------------------- MS-7: fechas
@pytest.mark.parametrize("texto, dia", [
    ("partidos de hoy", date(2026, 11, 13)), ("partidos de mañana", date(2026, 11, 14)), ("partidos de pasado mañana", date(2026, 11, 15)),
    ("resultados de ayer", date(2026, 11, 12)), ("los de anteayer", date(2026, 11, 11)),
    ("juegos del sábado", date(2026, 11, 14)), ("dime los juegos del domingo", date(2026, 11, 15)), ("el lunes", date(2026, 11, 16)),
    ("el viernes", date(2026, 11, 13)),                                            # hoy es viernes: «el viernes» es hoy
    ("que hay este finde", date(2026, 11, 14)), ("partidos del fin de semana", date(2026, 11, 14)),
    ("partidos en general", date(2026, 11, 13)),
])
def test_fecha_relativa(texto, dia):
    assert j.fecha(texto, VIERNES) == dia


def test_el_fin_de_semana_estando_en_fin_de_semana_es_hoy():
    assert j.fecha("este finde", date(2026, 11, 14)) == date(2026, 11, 14) and j.fecha("este finde", date(2026, 11, 15)) == date(2026, 11, 15)


def test_la_etiqueta_nombra_el_dia_como_lo_diria_una_persona():
    assert [j.etiqueta(VIERNES + timedelta(days=d), VIERNES) for d in (-1, 0, 1, 2)] == ["ayer", "hoy", "mañana", "pasado mañana"]
    assert j.etiqueta(date(2026, 11, 21), VIERNES) == "el sábado 21/11"


# ---------------------------------------------------------------- MS-7: el enrutador entiende la jerga
@pytest.mark.parametrize("frase, herramienta, partido", [
    ("quien se lleva el Madrid-Barça", "agent.prediction_choice", ("Madrid", "Barcelona")),
    ("¿quién se lleva el Madrid vs Barça?", "agent.prediction_choice", ("Madrid", "Barcelona")),
    ("quien gana el barça contra los merengues", "agent.prediction_choice", ("Barcelona", "Real Madrid")),
    ("como pinta el Barcelona vs Real Madrid", "agent.prediction_choice", ("Barcelona", "Real Madrid")),
    ("a quien le das el Madrid vs Barcelona", "agent.prediction_choice", ("Madrid", "Barcelona")),
    ("va a ganar el Madrid contra el Barça?", "agent.prediction_choice", ("Madrid", "Barcelona")),
    ("quien la gana: Madrid o Barça", "agent.prediction_choice", ("Madrid", "Barcelona")),
    ("pronostico los citizens contra los gunners", "agent.prediction_choice", ("Manchester City", "Arsenal")),
    ("partidos del sábado", "sports.list_fixtures", None), ("dime los juegos del domingo", "sports.list_fixtures", None), ("que partidos hay este finde", "sports.list_fixtures", None),
    ("partidos de pasado mañana", "sports.list_fixtures", None), ("ligas que juegan mañana", "sports.list_playing_leagues", None),
    pytest.param("como viene el atleti", "knowledge.team_profile", None, marks=requiere_conocimiento_equipos),   # el perfil de un equipo necesita el conocimiento por equipo (no se publica)
])
def test_el_enrutador_entiende_la_jerga(frase, herramienta, partido):
    normal = agent_runtime._normalizar_humano(frase)
    assert agent_runtime._respuesta_reglas(normal, False)[2] == herramienta
    assert agent_runtime._partido_desde_mensaje(normal) == partido


@pytest.mark.parametrize("frase", ["que opinas del partido Bayern vs Dortmund", "analiza el Bayern vs Dortmund"])
def test_bayern_no_se_confunde_con_ayer(frase):
    assert agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano(frase), False)[2] == "agent.prediction_choice"


@pytest.mark.parametrize("frase", ["Los Angeles FC vs Las Palmas", "analiza Los Angeles FC vs Las Palmas"])
def test_los_equipos_con_articulo_en_el_nombre_no_pierden_el_articulo(frase):
    local, visitante = agent_runtime._partido_desde_mensaje(agent_runtime._normalizar_humano(f"pronostico {frase.replace('analiza ', '')}"))
    assert local == "Los Angeles FC" and visitante == "Las Palmas"


@pytest.mark.parametrize("frase", ["quien paso por mi casa ayer", "como pinta mi dia", "a quien le das las gracias"])
def test_la_jerga_no_activa_pronosticos_fuera_del_futbol(frase):
    assert agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano(frase), False)[2] not in ("sports.predict", "agent.prediction_choice", "sports.list_fixtures")


def test_los_partidos_de_otro_dia_piden_ESA_fecha_a_la_herramienta(db_session, monkeypatch):
    fechas = []

    async def herramienta(nombre, argumentos, **_k):
        fechas.append((nombre, argumentos.get("date")))
        return {"fixtures": [], "date": argumentos.get("date")}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    for texto, dias in (("partidos de mañana", 1), ("partidos de pasado mañana", 2), ("partidos de hoy", 0)):
        asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", texto, None, "web", False, False))
        assert fechas[-1] == ("sports.list_fixtures", (date.today() + timedelta(days=dias)).strftime("%Y%m%d")), texto   # antes la herramienta se llamaba sin fecha: siempre hoy
    asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "partidos del sábado", None, "web", False, False))
    assert fechas[-1][1] == j.fecha("partidos del sábado").strftime("%Y%m%d")


# ---------------------------------------------------------------- MS-8: nivel «abierto»
CULTURA = ["explicame que es el var", "como funciona el fuera de lugar para un arbitro", "cuantos fichajes hizo el club este año", "quien es el mejor tecnico de la historia"]
AJENO = ["dame una receta de empanadas", "quien gano las elecciones", "cuanto es 2+2", "hablame de musica clasica"]


@pytest.mark.parametrize("frase", CULTURA)
def test_la_cultura_de_futbol_cae_fuera_en_normal_y_dentro_en_abierto(frase, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "normal")
    assert agent_runtime._fuera_de_alcance(frase) is True
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "abierto")
    assert agent_runtime._fuera_de_alcance(frase) is False


@pytest.mark.parametrize("frase", AJENO)
def test_lo_ajeno_al_futbol_sigue_fuera_en_todos_los_niveles(frase, monkeypatch):
    for nivel in ("estricto", "normal", "abierto"):
        monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", nivel)
        assert agent_runtime._fuera_de_alcance(frase) is True, (nivel, frase)


def _con_ia(monkeypatch, nivel):
    llamadas = []

    async def generar(prompt, max_tokens=700, rol="bot"):
        llamadas.append(prompt)
        return "El VAR es el sistema de asistencia por video que ayuda al árbitro a revisar jugadas.", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", nivel)
    return llamadas


def test_en_abierto_la_ia_responde_cultura_de_futbol_con_su_etiqueta_y_el_prompt_pide_no_dar_cifras(db_session, monkeypatch):
    llamadas = _con_ia(monkeypatch, "abierto")
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "explicame que es el var", None, "web", True, False))
    assert len(llamadas) == 1 and "VAR" in r["respuesta"] and "no verificada por el modelo" in r["respuesta"]
    assert "ajenos al fútbol" in llamadas[0] and "cifras de partidos" in llamadas[0]


def test_en_normal_y_estricto_la_misma_pregunta_no_llega_a_la_ia(db_session, monkeypatch):
    for nivel in ("normal", "estricto"):
        llamadas = _con_ia(monkeypatch, nivel)
        asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "explicame que es el var", None, "web", True, False))
        assert llamadas == [], nivel


def test_en_abierto_lo_ajeno_al_futbol_tampoco_llega_a_la_ia(db_session, monkeypatch):
    llamadas = _con_ia(monkeypatch, "abierto")
    for frase in AJENO:
        asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", frase, None, "web", True, False))
    assert llamadas == []


def test_en_abierto_una_cifra_inventada_por_la_ia_se_descarta(db_session, monkeypatch):
    async def generar(prompt, max_tokens=700, rol="bot"):
        return "El Madrid gana 70% de las veces el clásico y el marcador será 2-1.", "gemini", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", generar)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "abierto")
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u", "quien es el mejor tecnico de la historia", None, "web", True, False))
    assert "70%" not in r["respuesta"] and "charla_descartada" in r["modo"]
