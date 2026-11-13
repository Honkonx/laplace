"""MA-33: resultados recientes y comparación de perfiles (lectura, esquema cerrado, sin inventar)."""
import asyncio

from backend.api.models.partidos import ResultadoPartido
from backend.api.services import agent_tools_extra as x
from backend.api.services.agent_runtime import procesar_mensaje
from backend.api.services.agent_tools import SPORTS_TOOLS, ejecutar_herramienta_deportiva


def _res(db, i, local, visitante, gl, gv, fecha):
    db.add(ResultadoPartido(fixture_id=f"f{i}", local=local, visitante=visitante, liga="X", goles_local=gl, goles_visitante=gv, ganador="L", status_api="FT", fecha_partido=fecha, actualizado_en="2026-11-01"))


def test_resultados_recientes_ordena_limita_y_no_inventa(db_session):
    for i in range(12):
        _res(db_session, i, "Real Betis", f"Rival {i}", 1, 0, f"2026-10-{i + 1:02d}")
    _res(db_session, 99, "Otro", "Equipo", 3, 3, "2026-10-30")
    db_session.add(ResultadoPartido(fixture_id="pend", local="Real Betis", visitante="Pendiente", liga="X", goles_local=None, goles_visitante=None, status_api="NS", fecha_partido="2026-11-05", actualizado_en="2026-11-01"))
    db_session.commit()
    r = x.resultados_recientes(db_session, "betis", 50)
    assert r["estado"] == "ok" and len(r["data"]) == x.MAX_RESULTADOS and r["data"][0]["fecha"] == "2026-10-12" and all("Pendiente" not in d["visitante"] for d in r["data"])
    assert x.resultados_recientes(db_session, "Equipo Inventado")["estado"] == "sin_datos"
    assert x.resultados_recientes(db_session, "ab")["estado"] == "equipo_invalido"
    assert x.resultados_recientes(db_session, "%")["estado"] == "equipo_invalido"


def test_la_consulta_por_chat_usa_la_herramienta_y_los_datos_locales(db_session):
    _res(db_session, 1, "Real Betis", "Sevilla", 2, 1, "2026-10-20")
    db_session.commit()
    r = asyncio.run(procesar_mensaje(db_session, "u-x", "ultimos resultados del betis", None, "web", False, False))
    assert r["herramienta"] == "sports.recent_results" and "Real Betis 2-1 Sevilla" in r["respuesta"]


def test_comparar_perfiles_junta_los_dos_equipos_y_no_pronostica():
    r = asyncio.run(ejecutar_herramienta_deportiva("knowledge.compare_teams", {"team_a": "Boca Juniors", "team_b": "River Plate"}))
    assert r["tool"] == "knowledge.compare_teams" and "pronóstico" in r["texto"] and set(r["data"]) == {"a", "b"}


def test_las_herramientas_quedan_en_el_catalogo_como_solo_lectura():
    nuevas = {t.name: t for t in SPORTS_TOOLS if t.name in ("sports.recent_results", "knowledge.compare_teams")}
    assert len(nuevas) == 2 and all(not t.admin_only and not t.requires_confirmation for t in nuevas.values())


# ---------- MA-43: búsqueda en el historial ----------
def test_busca_en_el_historial_propio_con_acentos_y_sin_leer_lo_de_otros(db_session):
    asyncio.run(procesar_mensaje(db_session, "bus1", "analiza Boca vs River", None, "web", False, False))
    asyncio.run(procesar_mensaje(db_session, "bus2", "analiza Boca vs River por favor", None, "web", False, False))
    r = asyncio.run(procesar_mensaje(db_session, "bus1", "¿qué me dijiste del Boca-River?", None, "web", False, False))
    assert r["herramienta"] == "agent.search_history" and "Boca" in r["respuesta"]
    from backend.api.services import agent_sesiones

    hallado = agent_sesiones.buscar_en_historial(db_session, "bus1", "boca river")
    assert hallado and all(h["sesion"] for h in hallado)
    assert agent_sesiones.buscar_en_historial(db_session, "bus1", "xyzzy") == []
    assert agent_sesiones.buscar_en_historial(db_session, "nadie", "boca") == []


def test_el_tema_de_busqueda_se_extrae_solo_de_frases_de_historial():
    from backend.api.services.agent_sesiones import tema_de_busqueda

    assert tema_de_busqueda("que me dijiste del boca-river") == "boca-river" and tema_de_busqueda("cuando hablamos de la premier league") == "premier league"
    assert tema_de_busqueda("partidos de hoy") is None


# ---------- MA-40: resumen progresivo ----------
def test_una_sesion_de_40_turnos_conserva_partido_y_mercados_y_cabe_en_el_prompt(db_session):
    from backend.api.models.agent_runtime import AgentMessage, AgentSession
    from backend.api.services import agent_sesiones as s

    db_session.add(AgentSession(id="largo", user_id="L", channel="web", status="active", creado_en="2026-11-01", actualizado_en="2026-11-01"))
    frases = ["analiza Boca vs River", "y las cuotas?", "hola", "over 2.5 en Boca vs River", "que bien", "ambos marcan en Boca vs River", "gracias"] + ["mensaje de relleno numero %d" % i for i in range(30)] + ["analiza Real Madrid vs Barcelona"]
    for i, f in enumerate(frases):
        db_session.add(AgentMessage(session_id="largo", user_id="L", role="user", content=f, modo="entrada", creado_en="2026-11-01T00:%02d:00Z" % (i % 60)))
        db_session.add(AgentMessage(session_id="largo", user_id="L", role="assistant", content="respuesta %d" % i, modo="reglas", creado_en="2026-11-01T00:%02d:30Z" % (i % 60)))
    db_session.commit()
    bloque = s.historial_reciente(db_session, "largo")
    assert "Resumen de lo anterior" in bloque and "Boca vs River" in bloque and "over/under" in bloque and "cuotas" in bloque
    assert len(bloque) < 3000 and bloque.count("Usuario:") <= s.TURNOS_EN_PROMPT
    assert s.resumen_estructurado(db_session, "inexistente") == ""


def test_una_sesion_corta_no_lleva_resumen(db_session):
    from backend.api.services import agent_sesiones as s

    r = asyncio.run(procesar_mensaje(db_session, "corta", "hola", None, "web", False, False))
    assert "Resumen" not in s.historial_reciente(db_session, r["session_id"])
