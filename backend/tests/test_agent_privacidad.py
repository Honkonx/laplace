"""Privacidad del agente (MA-41/42): redacción de secretos, incógnito y borrado en cascada con guarda de tablas nuevas."""
import asyncio

import pytest

from backend.api.db.session import Base
from backend.api.models.agent_runtime import AgentMemory, AgentMessage, AgentSession, AgentToolInvocation
from backend.api.services import agent_privacidad as p
from backend.api.services.agent_runtime import procesar_mensaje


def _t(*partes):
    return "".join(partes)


@pytest.mark.parametrize("original,ausente", [
    (_t("mi clave es sk-", "abcdefghijklmnopqrstuvwx1234"), "abcdefghij"),
    (_t("usa ghp_", "A" * 36), "AAAAAAAA"),
    (_t("token 123456789:", "ABCdef" * 6), "ABCdefABCdef"),
    ("escríbeme a persona@correo.com por favor", "persona@correo.com"),
    (_t("Authorization: Bearer ", "abcdefghijklmnop1234"), "abcdefghijklmnop1234"),
    ("mi tarjeta 4111 1111 1111 1111 vence", "4111 1111 1111 1111"),
    (_t("eyJhbGciOi", ".eyJzdWIiOiIx", ".firmafirmafirma"), "firmafirmafirma"),
    ("password = hunter2hunter2", "hunter2hunter2"),
])
def test_los_secretos_y_datos_personales_se_enmascaran(original, ausente):
    texto, n = p.redactar(original)
    assert ausente not in texto and n >= 1


def test_un_mensaje_normal_no_se_toca():
    for msg in ["¿Quién gana Real Madrid vs Barcelona mañana?", "predice Arsenal contra Chelsea 2-1 con 3.5 de cuota", "el 12 de noviembre juega el América"]:
        assert p.redactar(msg) == (msg, 0)


def test_el_mensaje_guardado_y_el_enviado_a_la_ia_estan_enmascarados(db_session):
    clave = _t("sk-", "abcdefghijklmnopqrstuvwx1234")
    r = asyncio.run(procesar_mensaje(db_session, "u1", f"hola, mi clave es {clave}", None, "web", False, False))
    guardados = [m.content for m in db_session.query(AgentMessage).filter_by(user_id="u1", role="user")]
    assert guardados and all(clave not in g and "abcdefghijklmnop" not in g for g in guardados) and r["session_id"]


def test_el_incognito_responde_pero_no_guarda_nada(db_session):
    p.activar_incognito("u2")
    try:
        r = asyncio.run(procesar_mensaje(db_session, "u2", "hola, recuerda que me gusta el Betis", None, "web", False, False))
    finally:
        p.desactivar_incognito("u2")
    assert r["incognito"] is True and r["session_id"] is None and r["respuesta"]
    assert db_session.query(AgentMessage).filter_by(user_id="u2").count() == 0
    assert db_session.query(AgentSession).filter_by(user_id="u2").count() == 0
    assert db_session.query(AgentMemory).filter_by(owner_id="u2").count() == 0
    r2 = asyncio.run(procesar_mensaje(db_session, "u2", "hola", None, "web", False, False, incognito=True))  # también por parámetro
    assert r2["incognito"] is True and db_session.query(AgentMessage).filter_by(user_id="u2").count() == 0


def test_olvidar_borra_lo_del_usuario_anonimiza_la_auditoria_y_respeta_a_otros(db_session):
    for uid in ("a", "b"):
        asyncio.run(procesar_mensaje(db_session, uid, "recuerda que prefiero la Premier League", None, "web", False, False))
    db_session.add(AgentToolInvocation(id="t-a", user_id="a", tool_name="x", status="succeeded", input_json="{}", output_json="{}", creado_en="2026-11-01", terminado_en="2026-11-01"))
    db_session.commit()
    hecho = p.olvidar_usuario(db_session, "a")
    assert hecho["agent_messages"] >= 2 and hecho["agent_sessions"] >= 1 and hecho["agent_memories"] >= 1 and hecho["agent_tool_invocations"] == 1
    assert db_session.query(AgentMessage).filter_by(user_id="a").count() == 0 and db_session.query(AgentMemory).filter_by(owner_id="a").count() == 0
    assert db_session.query(AgentToolInvocation).filter_by(user_id="a").count() == 0 and db_session.query(AgentToolInvocation).filter_by(user_id=p.ANONIMO).count() == 1
    assert db_session.query(AgentMessage).filter_by(user_id="b").count() >= 2 and db_session.query(AgentMemory).filter_by(owner_id="b").count() >= 1


def test_toda_tabla_agent_nueva_debe_estar_clasificada_en_el_borrado():
    """Falla si alguien agrega una tabla `agent_*` y no decide si se borra, se anonimiza o es global (MA-41)."""
    clasificadas = {m.__tablename__ for m, _ in p.TABLAS_A_BORRAR} | {m.__tablename__ for m, _ in p.TABLAS_A_ANONIMIZAR} | set(p.TABLAS_GLOBALES)
    en_metadata = {t.name for t in Base.metadata.sorted_tables if t.name.startswith("agent_")}
    assert en_metadata == clasificadas, f"tablas agent_* sin clasificar: {en_metadata - clasificadas}; sobrantes: {clasificadas - en_metadata}"


# ---------- MA-51: el cupo diario sobrevive a un reinicio ----------
def test_el_cupo_diario_sobrevive_a_un_reinicio(monkeypatch, db_session):
    from sqlalchemy.orm import sessionmaker

    from backend.api.models.agent_runtime import AgentUsoDiario
    from backend.api.services import agent_guard

    monkeypatch.setattr("backend.api.db.session.SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setenv("AGENT_IA_MAX_POR_DIA", "3")
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "50")
    agent_guard.resetear_contadores()
    for _ in range(3):
        agent_guard.consumir_ia("telegram:9")
    with pytest.raises(agent_guard.LimiteExcedido):
        agent_guard.consumir_ia("telegram:9")
    assert db_session.query(AgentUsoDiario).filter_by(clave="telegram:9").one().usos == 3
    agent_guard.resetear_contadores()  # simula el reinicio del proceso: la memoria queda vacía
    with pytest.raises(agent_guard.LimiteExcedido):
        agent_guard.consumir_ia("telegram:9")  # el cupo se recupera de la base: no se devolvió
    agent_guard.consumir_ia("telegram:10")  # otro usuario no se ve afectado
    agent_guard.resetear_contadores()
    db_session.query(AgentUsoDiario).delete()
    db_session.commit()


def test_sin_base_disponible_el_contador_sigue_en_memoria(monkeypatch):
    from backend.api.services import agent_guard

    monkeypatch.setenv("AGENT_IA_MAX_POR_DIA", "2")
    monkeypatch.setenv("AGENT_IA_MAX_POR_MINUTO", "50")
    agent_guard.resetear_contadores()
    agent_guard.consumir_ia("sin-base")
    agent_guard.consumir_ia("sin-base")
    with pytest.raises(agent_guard.LimiteExcedido):
        agent_guard.consumir_ia("sin-base")
    agent_guard.resetear_contadores()


def test_el_incognito_no_borra_la_auditoria_de_la_herramienta_pero_si_el_texto(db_session):
    """Revisión de seguridad: ocultar el contenido no debe permitir ejecutar herramientas sin dejar rastro."""
    r = asyncio.run(procesar_mensaje(db_session, "u3", "mis tareas", None, "web", False, False, incognito=True))
    assert r["incognito"] is True and r["herramienta"] == "agent.tasks"
    filas = db_session.query(AgentToolInvocation).filter_by(user_id="u3").all()
    if True:
        assert filas and all("mis tareas" not in (f.input_json or "") and "sesion" not in (f.input_json or "") and '"incognito": true' in f.input_json for f in filas)
    assert db_session.query(AgentMessage).filter_by(user_id="u3").count() == 0


# ---------- MA-51: presupuesto de tokens con degradación a SIN IA ----------
def test_el_presupuesto_de_tokens_se_agota_y_el_admin_tiene_mas(monkeypatch):
    from backend.api.services import agent_guard as g

    monkeypatch.setenv("AGENT_IA_TOKENS_POR_DIA", "1000")
    g.resetear_contadores()
    assert g.tokens_disponibles("t1") and g.estimar_tokens("a" * 300) == 100
    g.registrar_tokens("t1", 1200)
    assert not g.tokens_disponibles("t1") and g.tokens_disponibles("t1", es_admin=True) and g.tokens_disponibles("t2")
    g.resetear_contadores()


def test_con_el_presupuesto_agotado_el_agente_responde_sin_ia(monkeypatch, db_session):
    from backend.api.core.config import settings
    from backend.api.services import agent_guard as g

    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setenv("AGENT_IA_TOKENS_POR_DIA", "10")
    g.resetear_contadores()
    g.registrar_tokens("tk", 50)
    r = asyncio.run(procesar_mensaje(db_session, "tk", "dime algo del futbol", None, "web", True, False))
    assert "Presupuesto diario de IA agotado" in r["respuesta"] and r["modo"] == "reglas"
    g.resetear_contadores()
