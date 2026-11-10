"""Perfiles de equipo, glosario, recuperación, herramientas `knowledge.*`, intención y endpoints de capacidades.

Los tests de resolución y recuperación usan el conocimiento REAL de `knowledge/` (generado por
`backend/scripts/generar_conocimiento_equipos.py`), no datos inventados: si los archivos no están en el
repo, fallan a propósito en vez de saltarse.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.core.config import settings
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.models.agent_runtime import AgentKnowledge
from backend.api.services import agent_capacidades, agent_guard, agent_knowledge, agent_runtime, agent_tools, conocimiento_equipos as ce, conocimiento_referencia as ref
from backend.api.services.agent_intencion_conocimiento import consulta_conocimiento
from backend.scripts import generar_conocimiento_equipos as gen
import backend.api.models  # noqa: F401

# El conocimiento por equipo se genera con datos históricos propios (no se publica): sin él, estas pruebas se omiten.
pytestmark = pytest.mark.skipif(
    not list((settings.repo_root / "backend" / "knowledge" / "sports").glob("equipos-*.json")),
    reason="falta el conocimiento por equipo (se genera con backend/scripts/generar_conocimiento_equipos.py y datos históricos propios)",
)


@pytest.fixture(autouse=True)
def _conocimiento_real_presente():
    assert ref.archivos_equipos(), "faltan knowledge/sports/equipos-*.json: correr backend/scripts/generar_conocimiento_equipos.py"
    assert (settings.repo_root / "backend" / "knowledge" / "sports" / "glosario-futbol.json").exists()


# --- Generador ------------------------------------------------------------------------------

def _partido(fecha, local, visitante, gl, gv, temporada="2024", **extra):
    base = {"liga": "T1", "liga_nombre": "Liga Test", "pais": "Chile", "temporada": temporada, "fecha": date.fromisoformat(fecha), "gl": gl, "gv": gv,
            "local": local, "visitante": visitante, **{n: (None, None) for n, _, _ in gen._EXTRAS}}
    return base | extra


PARTIDOS = [
    _partido("2023-01-10", "Alfa", "Beta", 1, 0, "2023"),
    _partido("2024-01-10", "Alfa", "Beta", 2, 2),
    _partido("2024-02-10", "Beta", "Alfa", 0, 3, tiros=(10.0, 5.0)),
    _partido("2024-03-10", "Alfa", "Gama", 0, 1),
    _partido("2024-04-10", "Gama", "Alfa", 1, 1),
    _partido("2024-05-10", "Beta", "Gama", 2, 0),
]


def test_generador_calcula_hechos_medidos_y_ventanas():
    entradas = {e["metadata"]["equipo"]: e for e in gen.entradas_liga("T1", PARTIDOS)}
    assert set(entradas) == {"Alfa", "Beta", "Gama"}
    alfa = entradas["Alfa"]["metadata"]
    # Ventana de 12 meses desde el último partido de la liga (2024-05-10): deja fuera el partido de 2023.
    assert alfa["ventana_12m"]["partidos"] == 4 and alfa["ventana_3t"]["partidos"] == 5
    assert (alfa["ventana_12m"]["g"], alfa["ventana_12m"]["e"], alfa["ventana_12m"]["p"]) == (1, 2, 1)
    assert alfa["ventana_12m"]["gf_pp"] == 1.5 and alfa["ventana_12m"]["gc_pp"] == 1.0
    assert alfa["ventana_12m"]["local"]["partidos"] == 2 and alfa["ventana_12m"]["visitante"]["partidos"] == 2
    assert [r["resultado"] for r in alfa["racha_5"]] == ["E", "P", "G", "E", "G"]  # más reciente primero
    assert alfa["racha_5"][0]["fecha"] == "2024-04-10" and alfa["ultimo_partido"] == "2024-04-10"
    assert alfa["corte_liga"] == "2024-05-10"
    assert entradas["Alfa"]["topic_key"] == "equipo-T1-alfa" and entradas["Alfa"]["namespace"] == "futbol"


def test_generador_extras_solo_con_muestra_suficiente_y_es_idempotente():
    beta = next(e for e in gen.entradas_liga("T1", PARTIDOS) if e["metadata"]["equipo"] == "Beta")
    assert "extras" not in beta["metadata"]["ventana_12m"]  # 1 partido con tiros < mínimo de 5
    assert gen.entradas_liga("T1", PARTIDOS) == gen.entradas_liga("T1", list(PARTIDOS))


def test_generador_descarta_equipos_sin_partidos_en_12_meses():
    viejo = [_partido("2020-01-01", "Viejo", "Alfa", 1, 0, "2020"), *PARTIDOS]
    nombres = {e["metadata"]["equipo"] for e in gen.entradas_liga("T1", sorted(viejo, key=lambda p: p["fecha"]))}
    assert "Viejo" not in nombres


def test_archivos_de_equipos_reales_son_deterministas_y_no_entran_a_la_tabla(db_session):
    assert ce.contar_equipos() >= 900
    agent_knowledge.sincronizar_conocimiento_json(db_session, forzar=True)
    claves = [f.topic_key for f in db_session.query(AgentKnowledge).all()]
    assert claves and not [c for c in claves if c.startswith("equipo-")]  # bajo demanda, no en la tabla


# --- Resolución de equipos ----------------------------------------------------------------------

@pytest.mark.parametrize("consulta,nombre,liga", [
    ("Colo Colo", "Colo Colo", "CHL1"), ("colo-colo", "Colo Colo", "CHL1"), ("COLO COLO", "Colo Colo", "CHL1"),
    ("la U", "Universidad de Chile", "CHL1"), ("U de Chile", "Universidad de Chile", "CHL1"),
    ("Man City", "Manchester City", "E0"), ("Man Utd", "Manchester United", "E0"),
    ("Boca", "Boca Juniors", "ARG"), ("Peñarol", "Penarol", "URY1"), ("Atlético Madrid", "Atletico Madrid", "SP1"),
    ("barça", "Barcelona", "SP1"), ("PSG", "Paris Saint Germain", "F1"), ("Bolívar", "Bolívar", "BOL1"),
    ("Vélez", "Velez Sarsfield", "ARG"), ("Real Madrid", "Real Madrid", "SP1"), ("Bayern", "Bayern Munich", "D1"),
])
def test_resolver_nombres_apodos_y_acentos(consulta, nombre, liga):
    r = ce.resolver_equipo(consulta)
    assert r["estado"] == "ok", r
    assert r["club"].nombre == nombre and r["club"].principal["metadata"]["liga_codigo"] == liga


def test_resolver_no_adivina_entre_clubes_distintos():
    river = ce.resolver_equipo("River")
    assert river["estado"] == "ambiguo"
    assert {c["liga_codigo"] for c in river["candidatos"]} == {"ARG", "URY1"}
    assert ce.resolver_equipo("Barcelona")["estado"] == "ambiguo"  # España y Ecuador
    assert {c["liga_codigo"] for c in ce.resolver_equipo("Universidad Catolica")["candidatos"]} == {"CHL1", "ECU1"}
    assert ce.resolver_equipo("Sporting")["estado"] == "ambiguo"
    assert ce.resolver_equipo("Equipo Inexistente FC")["estado"] == "no_encontrado"
    # La liga o el país desambiguan.
    assert ce.resolver_equipo("River", liga="Argentina")["club"].principal["metadata"]["liga_codigo"] == "ARG"
    assert ce.resolver_equipo("river uruguay")["club"].principal["metadata"]["liga_codigo"] == "URY1"


def test_errata_se_acepta_solo_si_es_unica_y_queda_marcada():
    r = ce.resolver_equipo("Liverpol")
    assert r["estado"] == "ok" and r["coincidencia"] == "aproximada" and r["club"].nombre == "Liverpool"
    perfil = ce.perfil_equipo("Liverpol")
    assert any("Entendí" in a for a in perfil["avisos"])


def test_club_en_dos_divisiones_es_un_solo_equipo():
    r = ce.resolver_equipo("Burnley")
    assert r["estado"] == "ok"
    ligas = {p["metadata"]["liga_codigo"] for p in r["club"].perfiles}
    assert len(ligas) >= 2 and r["club"].principal["metadata"]["liga_codigo"] in ligas


def test_perfil_avisa_cuando_los_datos_estan_desactualizados():
    chile = ce.perfil_equipo("Colo Colo", referencia=date(2026, 10, 7))
    assert chile["estado"] == "ok" and chile["frescura"]["nivel"] == "desactualizado" and chile["frescura"]["dias"] > 600
    assert any("desactualizados" in a for a in chile["avisos"])
    assert chile["perfil"]["ventana_12m"]["partidos"] > 20 and len(chile["perfil"]["racha_5"]) == 5
    al_dia = ce.perfil_equipo("Arsenal", referencia=date(2026, 9, 25))
    assert al_dia["frescura"]["nivel"] in ("al_dia", "reciente") and not al_dia["frescura"]["aviso"]
    assert al_dia["perfil"]["ventana_12m"].get("extras", {}).get("corners")  # la liga inglesa trae córners


def test_deteccion_en_texto_libre():
    def nombres(texto):
        return [h["club"].nombre for h in ce.detectar_equipos_en_texto(texto)]

    assert nombres("¿cómo viene Colo-Colo?") == ["Colo Colo"]
    assert nombres("perfil de Boca") == ["Boca Juniors"]
    assert nombres("Man City vs Arsenal hoy") == ["Manchester City", "Arsenal"]
    assert nombres("dime de la U") == ["Universidad de Chile"]
    assert nombres("perfil de River") == []  # ambiguo: no se inyecta
    assert nombres("un chico juega como puede") == []  # palabras comunes que también son equipos
    assert nombres("cuántos goles se hacen en la liga chilena") == []


# --- Ligas y glosario -----------------------------------------------------------------------------

@pytest.mark.parametrize("texto,codigo", [
    ("cuántos goles se hacen en la liga chilena", "CHL1"), ("la Premier", "E0"), ("Serie B de Brasil", "BRA2"),
    ("liga argentina", "ARG"), ("Bundesliga", "D1"), ("CHL1", "CHL1"), ("la liga de España", "SP1"), ("champions", "UCL"),
])
def test_deteccion_de_ligas(texto, codigo):
    d = ref.detectar_ligas(texto)
    assert d.codigos[0] == codigo and not d.ambiguo


def test_liga_ambigua_o_desconocida_no_se_adivina():
    assert ref.detectar_ligas("primera division").ambiguo
    assert ref.perfil_liga("primera division")["estado"] == "ambiguo"
    desconocida = ref.perfil_liga("la liga de Costa Rica")
    assert desconocida["estado"] == "no_encontrada" and desconocida["ligas_cubiertas"]


def test_perfil_de_liga_trae_tasas_cobertura_y_frescura():
    chile = ref.perfil_liga("liga chilena", referencia=date(2026, 10, 7))
    assert chile["estado"] == "ok" and chile["liga"]["codigo"] == "CHL1"
    assert chile["tasas_base"]["partidos"] == 720 and chile["cobertura"]["hasta"] == "2024-11-10"
    assert chile["frescura"]["nivel"] == "desactualizado" and chile["avisos"]
    copa = ref.perfil_liga("Copa Libertadores")
    assert copa["liga"]["tipo"] == "copa" and any("copa" in a.lower() for a in copa["avisos"])


@pytest.mark.parametrize("consulta,clave", [
    ("xG", "glosario-xg"), ("qué significa confianza media", "guia-confianza-frecuencias"), ("tasa base", "glosario-tasa-base"),
    ("BTTS", "glosario-btts"), ("over 2.5", "glosario-over-under"), ("H2H", "glosario-h2h"), ("localía", "glosario-localia"),
    ("sin pronóstico", "faq-sin-pronostico"), ("¿de dónde salen los datos?", "faq-origen-datos"),
])
def test_glosario_encuentra_el_termino(consulta, clave):
    r = ref.buscar_glosario(consulta)
    assert r["estado"] == "ok" and r["entrada"]["clave"] == clave


def test_glosario_no_inventa_terminos():
    r = ref.buscar_glosario("zzzqx")
    assert r["estado"] == "no_encontrado" and r["terminos_disponibles"]


def test_cifras_de_confianza_coinciden_con_el_codigo_del_consenso():
    from backend.api.services import consenso

    texto = ref.buscar_glosario("confianza")["entrada"]["texto"] + " " + ref.buscar_glosario("que significa confianza media")["entrada"]["texto"]
    assert consenso.PROB_CONFIANZA_ALTA == 0.60 and consenso.PROB_CONFIANZA_MEDIA == 0.50
    assert "60%" in texto and "50%" in texto and "72%" in texto and "57%" in texto


def test_el_glosario_no_incita_a_apostar():
    for entrada in ref._entradas_referencia():
        bajo = entrada["texto"].lower()
        assert "apuesta segura" not in bajo and "gana dinero" not in bajo and "garantizad" not in bajo, entrada["clave"]


# --- Recuperación ------------------------------------------------------------------------------------

@pytest.fixture()
def conocimiento_cargado(db_session):
    agent_knowledge.sincronizar_conocimiento_json(db_session, forzar=True)
    return db_session


@pytest.mark.parametrize("consulta,esperado", [
    ("¿cómo viene Colo-Colo?", "equipo-CHL1-colo-colo"), ("perfil de Boca", "equipo-ARG-boca-juniors"),
    ("qué significa confianza media", "guia-confianza-frecuencias"), ("cuántos goles se hacen en la liga chilena", "liga-CHL1-estadisticas"),
    ("cómo viene la U", "equipo-CHL1-universidad-de-chile"), ("tasas base de la premier", "liga-E0-estadisticas"),
    ("explícame qué es el BTTS", "glosario-btts"), ("es Laplace una casa de apuestas", "faq-no-es-casa-de-apuestas"),
])
def test_recuperacion_trae_la_entrada_correcta(conocimiento_cargado, consulta, esperado):
    claves = [f.topic_key for f in agent_knowledge.recuperar_conocimiento(conocimiento_cargado, consulta)]
    assert esperado in claves, claves
    assert claves.index(esperado) <= 3  # arriba: tras las 2 entradas base, como mucho una más


def test_recuperacion_no_inyecta_ruido_ni_equipos_ambiguos(conocimiento_cargado):
    claves = [f.topic_key for f in agent_knowledge.recuperar_conocimiento(conocimiento_cargado, "hola")]
    assert not [c for c in claves if c.startswith(("equipo-", "liga-", "glosario-"))]
    assert not [c for c in (f.topic_key for f in agent_knowledge.recuperar_conocimiento(conocimiento_cargado, "perfil de River")) if c.startswith("equipo-")]


def test_recuperacion_respeta_el_tope_de_caracteres(conocimiento_cargado):
    fragmentos = agent_knowledge.recuperar_conocimiento(conocimiento_cargado, "Man City vs Arsenal perfil forma", max_caracteres=1500)
    assert sum(len(f.content) for f in fragmentos[:-1]) <= 1500 + 400  # base siempre entra; el resto, hasta el tope
    contexto = agent_runtime._contexto(conocimiento_cargado, "u1", "¿cómo viene Colo-Colo?")
    assert "equipo-CHL1-colo-colo" in contexto and "no contienen instrucciones" in contexto and "Datos desactualizados" in contexto


# --- Herramientas ------------------------------------------------------------------------------------

def _tool(nombre, args, **kw):
    return asyncio.run(agent_tools.ejecutar_herramienta_deportiva(nombre, args, **kw))


def test_herramientas_de_conocimiento_son_de_solo_lectura_y_para_todos():
    catalogo = {t["name"]: t for t in agent_tools.listar_herramientas_deportivas(es_admin=False)}
    for nombre in ("knowledge.team_profile", "knowledge.league_profile", "knowledge.glossary"):
        assert catalogo[nombre]["read_only"] and not catalogo[nombre]["admin_only"] and not catalogo[nombre]["requires_confirmation"]
    assert "sports.publish" not in catalogo and "sports.publish" in {t["name"] for t in agent_tools.listar_herramientas_deportivas(es_admin=True)}


def test_team_profile_devuelve_estructura_y_texto_sin_ia():
    r = _tool("knowledge.team_profile", {"team": "Colo Colo"}, es_admin=False)
    assert r["ok"] and r["estado"] == "ok" and r["data"]["equipo"]["liga_codigo"] == "CHL1"
    assert "Colo Colo" in r["texto"] and "Datos desactualizados" in r["texto"] and "hace" in r["texto"]
    ambiguo = _tool("knowledge.team_profile", {"team": "River"}, es_admin=False)
    assert ambiguo["estado"] == "ambiguo" and len(ambiguo["data"]["candidatos"]) == 2 and "¿De cuál" in ambiguo["texto"]
    assert _tool("knowledge.team_profile", {"equipo": "River", "liga": "Uruguay"})["data"]["equipo"]["liga_codigo"] == "URY1"


def test_league_profile_y_glossary():
    liga = _tool("knowledge.league_profile", {"league": "ARG"})
    assert liga["estado"] == "ok" and liga["data"]["tasas_base"]["partidos"] == 1673 and "gana el local 42.7%" in liga["texto"]
    glosario = _tool("knowledge.glossary", {"term": "tasa base"})
    assert glosario["estado"] == "ok" and glosario["texto"].startswith("Tasa base")
    assert _tool("knowledge.glossary", {"term": "zzzqx"})["estado"] == "no_encontrado"


@pytest.mark.parametrize("nombre,args", [
    ("knowledge.team_profile", {}), ("knowledge.team_profile", {"team": 123}), ("knowledge.team_profile", {"team": "x" * 201}),
    ("knowledge.league_profile", {"league": ""}), ("knowledge.glossary", {"term": ["a"]}), ("knowledge.glossary", {}),
])
def test_herramientas_validan_argumentos(nombre, args):
    with pytest.raises(ValueError):
        _tool(nombre, args)


# --- Intención y respuesta del agente ------------------------------------------------------------------

@pytest.mark.parametrize("mensaje,herramienta", [
    ("¿cómo viene Colo-Colo?", "knowledge.team_profile"), ("perfil de Boca", "knowledge.team_profile"), ("cómo viene la U", "knowledge.team_profile"),
    ("perfil de River", "knowledge.team_profile"), ("qué significa confianza media", "knowledge.glossary"),
    ("cuántos goles se hacen en la liga chilena", "knowledge.league_profile"), ("tasas base de la Premier", "knowledge.league_profile"),
    ("qué es una tasa base", "knowledge.glossary"), ("cada cuánto se actualiza la información", "knowledge.glossary"),
    ("qué ligas cubres", "knowledge.glossary"), ("cobertura de la liga de Costa Rica", "knowledge.league_profile"),
])
def test_el_router_enruta_a_conocimiento(mensaje, herramienta):
    respuesta, _, tool = agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano(mensaje), False)
    assert tool == herramienta, respuesta


@pytest.mark.parametrize("mensaje", ["hola", "partidos de hoy", "predicción bot Barcelona vs PSG", "cómo viene el clima", "qué es la vida", "mi perfil de usuario"])
def test_el_router_no_secuestra_otras_consultas(mensaje):
    _, _, tool = agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano(mensaje), False)
    assert not (tool or "").startswith("knowledge.")


def test_consulta_conocimiento_con_partido_deja_pasar_la_prediccion():
    assert consulta_conocimiento("analiza boca vs river", hay_partido=True) is None


def test_agente_responde_perfil_sin_gastar_ia(db_session, monkeypatch):
    async def ia_prohibida(*a, **k):
        raise AssertionError("la IA no debe intervenir en herramientas de conocimiento")

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia_prohibida)
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u1", "¿cómo viene Colo-Colo?", None, "web", True, False))
    assert r["herramienta"] == "knowledge.team_profile" and "Colo Colo" in r["respuesta"] and "Datos desactualizados" in r["respuesta"]
    r2 = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u1", "qué significa confianza media", None, "web", True, False))
    assert r2["herramienta"] == "knowledge.glossary" and "72%" in r2["respuesta"] and r2["modo"] == "reglas"


DATOS_MOTOR = {"consenso": {"pick_final": "Local", "confianza_final": "MEDIA", "nivel": "FUERTE", "criterio_pick": "probabilidad_ponderada",
                            "prob_ponderada": {"local": 0.512, "empate": 0.263, "visitante": 0.225}, "modulos_en_consenso": ["historico"], "modulos_disidentes": [], "total_modulos": 1}}


def _predictor_falso(monkeypatch, datos, local, visitante):
    async def herramienta(nombre, argumentos, *, es_admin=False, authorization=None, usuario=None):
        if nombre == "sports.list_fixtures":
            return {"fixtures": [{"match_id": "m1", "local": local, "visitante": visitante, "liga": "Premier League"}]}
        return {"ok": True, "prediction": datos}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", herramienta)
    monkeypatch.setattr(agent_runtime, "autorizacion_sports", lambda *a, **k: "Bearer t")


def test_prediccion_incluye_la_forma_de_los_equipos_y_dice_si_no_hay_tasas_base(db_session, monkeypatch):
    _predictor_falso(monkeypatch, DATOS_MOTOR, "Manchester City", "Arsenal")
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u1", "predicción bot Manchester City vs Arsenal", None, "web", False, False))
    assert "Forma de Manchester City: últimos 5" in r["respuesta"] and "Forma de Arsenal" in r["respuesta"]
    assert "No tengo tasas base de esta liga" in r["respuesta"]  # el resumen falso no trae tasa base: se dice, no se inventa


def test_sin_pronostico_explica_la_falta_de_cobertura(db_session, monkeypatch):
    _predictor_falso(monkeypatch, {"consenso": {"pick_final": "Sin pronóstico"}}, "Equipo Raro", "Otro Raro")
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u1", "predicción bot Equipo Raro vs Otro Raro", None, "web", False, False))
    assert "no emite pronóstico" in r["respuesta"] and "fuera de la cobertura" in r["respuesta"] and "Forma de" not in r["respuesta"]


def test_partido_no_encontrado_ofrece_el_perfil_de_los_equipos_conocidos(db_session, monkeypatch):
    async def sin_partidos(nombre, argumentos, **k):
        return {"fixtures": []}

    monkeypatch.setattr(agent_runtime, "ejecutar_herramienta_deportiva", sin_partidos)
    r = asyncio.run(agent_runtime.procesar_mensaje(db_session, "u1", "predicción bot Colo Colo vs Equipo Raro", None, "web", False, False))
    assert "No encontré un partido" in r["respuesta"] and "perfil de Colo Colo" in r["respuesta"]


# --- Endpoints de capacidades y uso ------------------------------------------------------------------------

USUARIO = {"sub": "usuario-1", "rol": "user"}
ADMIN = {"sub": "admin-1", "rol": "admin"}


@pytest.fixture()
def entorno(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine)

    def _db():
        db = sesion()
        try:
            yield db
        finally:
            db.close()

    actual = {"usuario": USUARIO}
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[obtener_usuario_actual] = lambda: actual["usuario"]
    agent_guard.resetear_contadores()
    yield SimpleNamespace(client=TestClient(app), actual=actual)
    app.dependency_overrides.clear()
    agent_guard.resetear_contadores()


def test_el_catalogo_de_herramientas_oculta_las_de_admin_a_un_usuario_normal(entorno):
    nombres = {t["name"] for t in entorno.client.get("/api/v1/agent/tools").json()["tools"]}
    assert "sports.predict" in nombres and not {"sports.publish", "sports.results", "sports.top_picks"} & nombres
    entorno.actual["usuario"] = ADMIN
    nombres_admin = {t["name"] for t in entorno.client.get("/api/v1/agent/tools").json()["tools"]}
    assert {"sports.publish", "sports.results", "sports.top_picks"} <= nombres_admin


def test_capabilities_usuario_normal_no_ve_herramientas_admin_ni_proveedores(entorno, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_clave_de_prueba_que_no_debe_salir")
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    r = entorno.client.get("/api/v1/agent/capabilities")
    assert r.status_code == 200
    cuerpo = r.json()
    nombres = {t["name"] for t in cuerpo["herramientas"]}
    assert {"knowledge.team_profile", "knowledge.league_profile", "knowledge.glossary", "sports.predict"} <= nombres
    assert not {"sports.publish", "sports.results", "sports.top_picks"} & nombres
    ia = next(m for m in cuerpo["modos"] if m["id"] == "ia")
    assert cuerpo["rol"] == "usuario" and ia["disponible"] and ia["proveedores_configurados"] >= 1 and ia["proveedores"] == []
    assert "gsk_clave" not in r.text
    assert cuerpo["limites"]["ia_por_dia"] == 60 and cuerpo["limites"]["ia_por_minuto"] == 5
    assert cuerpo["conocimiento"]["equipos_con_perfil"] >= 900 and cuerpo["conocimiento"]["datos_hasta"] and len(cuerpo["conocimiento"]["version"]) == 10


def test_capabilities_admin_ve_todo_y_los_nombres_de_proveedor_pero_nunca_claves(entorno, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_clave_de_prueba_que_no_debe_salir")
    entorno.actual["usuario"] = ADMIN
    r = entorno.client.get("/api/v1/agent/capabilities")
    cuerpo = r.json()
    assert cuerpo["rol"] == "admin" and {"sports.publish", "sports.top_picks"} <= {t["name"] for t in cuerpo["herramientas"]}
    assert "groq" in next(m for m in cuerpo["modos"] if m["id"] == "ia")["proveedores"]
    assert cuerpo["limites"]["ia_por_dia"] == 300 and "gsk_clave" not in r.text


def test_capabilities_sin_proveedores_o_con_ia_desactivada_el_modo_ia_no_esta_disponible(entorno, monkeypatch):
    monkeypatch.setattr(agent_capacidades, "proveedores_ia_configurados", lambda: [])
    ia = next(m for m in entorno.client.get("/api/v1/agent/capabilities").json()["modos"] if m["id"] == "ia")
    assert not ia["disponible"] and ia["proveedores_configurados"] == 0
    monkeypatch.setattr(agent_capacidades, "proveedores_ia_configurados", lambda: ["groq"])
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", False)
    assert not next(m for m in entorno.client.get("/api/v1/agent/capabilities").json()["modos"] if m["id"] == "ia")["disponible"]
    reglas = next(m for m in entorno.client.get("/api/v1/agent/capabilities").json()["modos"] if m["id"] == "reglas")
    assert reglas["disponible"]


def test_usage_refleja_el_cupo_sin_consumirlo(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "3")
    monkeypatch.setenv("AGENT_IA_MAX_POR_DIA", "10")
    inicial = entorno.client.get("/api/v1/agent/usage").json()
    assert inicial["por_minuto"] == {"limite": 3, "usadas": 0, "restantes": 3, "reinicia_en_segundos": None}
    assert inicial["por_dia"]["restantes"] == 10 and inicial["rol"] == "usuario" and inicial["fecha"] == date.today().isoformat()
    for _ in range(3):  # consultar el uso no gasta cupo
        entorno.client.get("/api/v1/agent/usage")
    agent_guard.consumir_ia("usuario-1")
    agent_guard.consumir_ia("usuario-1")
    uso = entorno.client.get("/api/v1/agent/usage").json()
    assert uso["por_minuto"]["usadas"] == 2 and uso["por_minuto"]["restantes"] == 1 and 1 <= uso["por_minuto"]["reinicia_en_segundos"] <= 61
    assert uso["por_dia"]["usadas"] == 2 and uso["por_dia"]["restantes"] == 8
    agent_guard.consumir_ia("usuario-1")
    with pytest.raises(agent_guard.LimiteExcedido):
        agent_guard.consumir_ia("usuario-1")
    assert entorno.client.get("/api/v1/agent/usage").json()["por_minuto"]["restantes"] == 0


def test_usage_es_por_usuario_y_el_admin_tiene_cupo_ampliado(entorno, monkeypatch):
    monkeypatch.setenv("AGENT_IA_MAX_POR_DIA", "10")
    agent_guard.consumir_ia("usuario-1")
    assert entorno.client.get("/api/v1/agent/usage").json()["por_dia"]["usadas"] == 1
    entorno.actual["usuario"] = ADMIN
    uso = entorno.client.get("/api/v1/agent/usage").json()
    assert uso["rol"] == "admin" and uso["por_dia"] == {"limite": 50, "usadas": 0, "restantes": 50, "reinicia_en_segundos": None}


def test_las_herramientas_de_conocimiento_se_ejecutan_por_el_endpoint_para_un_usuario_normal(entorno):
    r = entorno.client.post("/api/v1/agent/tools/knowledge.glossary", headers={"Authorization": "Bearer x"}, json={"arguments": {"term": "xg"}})
    assert r.status_code == 200 and r.json()["estado"] == "ok"
    r = entorno.client.post("/api/v1/agent/tools/knowledge.team_profile", headers={"Authorization": "Bearer x"}, json={"arguments": {"team": ""}})
    assert r.status_code == 400
    assert json.loads(json.dumps(entorno.client.get("/api/v1/agent/tools").json()))["tools"]
