"""Memoria mínima del bot (MB-30…33): consentimiento, equipos, historial con poda, personalización que solo ordena y `/olvidame` que cubre todas las tablas del bot."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.api.db import bot_memoria_repo as m
from backend.api.db.session import Base
from backend.api.models.bot_memoria import BotConsentimiento, BotHistorialConsulta, BotPreferencias
from backend.api.models.predicciones import PrediccionUsuario
from backend.api.models.usuarios import Usuario


def test_sin_consentimiento_no_se_guarda_nada(db_session):
    assert m.registrar_consulta(db_session, "1", "p1") is False
    r = m.agregar_equipo(db_session, "1", "Arsenal")
    assert r["ok"] is False and r["error"] == "sin_consentimiento"
    assert db_session.query(BotHistorialConsulta).count() == 0 and db_session.query(BotPreferencias).count() == 0


def test_con_consentimiento_guarda_equipos_con_limite_y_sin_duplicados(db_session):
    m.aceptar(db_session, "1")
    assert m.tiene_consentimiento(db_session, "1")
    for e in ["Arsenal", "Chelsea", "Betis", "Milan", "Lazio"]:
        assert m.agregar_equipo(db_session, "1", e)["ok"]
    assert m.agregar_equipo(db_session, "1", "arsenal")["error"] == "ya_existe"
    assert m.agregar_equipo(db_session, "1", "Roma")["error"] == "limite_alcanzado"
    assert m.agregar_equipo(db_session, "1", "A|B")["error"] == "equipo_invalido"
    assert m.quitar_equipo(db_session, "1", "BETIS")["ok"] and "Betis" not in m.equipos_favoritos(db_session, "1")
    assert m.quitar_equipo(db_session, "1", "Nadie")["error"] == "no_encontrado"


def test_revocar_borra_historial_y_equipos_y_deja_constancia(db_session):
    m.aceptar(db_session, "1")
    m.agregar_equipo(db_session, "1", "Arsenal")
    m.registrar_consulta(db_session, "1", "p1")
    m.revocar(db_session, "1")
    assert not m.tiene_consentimiento(db_session, "1")
    assert db_session.query(BotHistorialConsulta).count() == 0 and m.equipos_favoritos(db_session, "1") == []
    assert db_session.get(BotConsentimiento, "1").revocado_en is not None
    assert m.registrar_consulta(db_session, "1", "p2") is False
    m.aceptar(db_session, "1")  # volver a aceptar reactiva
    assert m.tiene_consentimiento(db_session, "1") and db_session.get(BotConsentimiento, "1").revocado_en is None


def test_el_historial_se_poda_por_antiguedad_y_por_cantidad(db_session, monkeypatch):
    m.aceptar(db_session, "1")
    viejo = (datetime.now(timezone.utc) - timedelta(days=m.RETENCION_DIAS + 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_session.add(BotHistorialConsulta(user_id="1", partido_id="viejo", creado_en=viejo))
    db_session.commit()
    m.registrar_consulta(db_session, "1", "nuevo")
    assert [h["partido_id"] for h in m.historial(db_session, "1")] == ["nuevo"]
    monkeypatch.setattr(m, "MAX_HISTORIAL", 5)
    for i in range(12):
        m.registrar_consulta(db_session, "1", f"p{i}")
    filas = m.historial(db_session, "1", limite=50)
    assert len(filas) == 5 and filas[0]["partido_id"] == "p11"


def test_la_personalizacion_solo_ordena_y_la_lista_es_la_misma(db_session):
    ligas = [{"nombre": "Serie A", "partidos": 3}, {"nombre": "LaLiga", "partidos": 5}, {"nombre": "Premier League", "partidos": 4}]
    orden = m.ordenar_por_favoritos(ligas, nombre_liga=lambda l: l["nombre"], ligas_favoritas=["premier league"])
    assert orden[0]["nombre"] == "Premier League" and sorted(x["nombre"] for x in orden) == sorted(x["nombre"] for x in ligas) and all(x in ligas for x in orden)
    partidos = [{"local": "Betis", "visitante": "Sevilla", "p": 0.31}, {"local": "Arsenal", "visitante": "Chelsea", "p": 0.52}]
    o2 = m.ordenar_por_favoritos(partidos, nombres_equipo=lambda p: (p["local"], p["visitante"]), equipos=["chelsea"])
    assert o2[0]["p"] == 0.52 and o2[1]["p"] == 0.31  # las cifras viajan intactas
    assert m.ordenar_por_favoritos(partidos) == partidos  # sin favoritos: mismo orden


def test_olvidame_borra_todo_lo_del_usuario_y_nada_de_otro(db_session):
    db_session.add(Usuario(device_id="1", activo=1, plan="free", creado_en="2026-11-01", favoritos_ligas="LaLiga"))
    db_session.add(Usuario(device_id="2", activo=1, plan="free", creado_en="2026-11-01", favoritos_ligas="Serie A"))
    db_session.add(PrediccionUsuario(match_id="m1", telegram_user_id="1", pick="local", creado_en="2026-11-01"))
    db_session.commit()
    for uid in ("1", "2"):
        m.aceptar(db_session, uid)
        m.agregar_equipo(db_session, uid, "Arsenal")
        m.registrar_consulta(db_session, uid, "p1")
    borrado = m.olvidar(db_session, "1")
    assert borrado["bot_preferencias"] == 1 and borrado["bot_historial_consultas"] == 1 and borrado["bot_consentimientos"] == 1 and borrado["predicciones_usuario"] == 1 and borrado["favoritos_ligas"] == 1
    assert db_session.query(Usuario).filter_by(device_id="1").one().favoritos_ligas is None
    assert db_session.query(BotHistorialConsulta).filter_by(user_id="1").count() == 0 and not m.tiene_consentimiento(db_session, "1")
    assert m.equipos_favoritos(db_session, "2") == ["Arsenal"] and db_session.query(Usuario).filter_by(device_id="2").one().favoritos_ligas == "Serie A"


def test_toda_tabla_bot_nueva_debe_estar_cubierta_por_el_borrado():
    """Falla si alguien agrega una tabla `bot_*` y olvida incluirla en `/olvidame` (MB-32)."""
    en_metadata = {t.name for t in Base.metadata.sorted_tables if t.name.startswith("bot_")}
    cubiertas = {mod.__tablename__ for mod in m.TABLAS_DEL_BOT}
    assert en_metadata == cubiertas, f"tablas bot_* sin cubrir en olvidar(): {en_metadata - cubiertas}"
    for mod in m.TABLAS_DEL_BOT:
        assert "user_id" in mod.__table__.columns


def test_el_texto_de_consentimiento_es_corto_y_dice_que_no_cambia_pronosticos():
    assert len(m.TEXTO_CONSENTIMIENTO) < 300 and "Nunca cambia un pronóstico" in m.TEXTO_CONSENTIMIENTO and "/olvidame" in m.TEXTO_CONSENTIMIENTO
    pytest.importorskip("telegram")


# ---------- MB-34: avisos de favoritos ----------
def test_los_avisos_exigen_consentimiento_y_un_favorito(db_session):
    assert m.configurar_avisos(db_session, "9", True)["error"] == "sin_consentimiento"
    m.aceptar(db_session, "9")
    assert m.configurar_avisos(db_session, "9", True)["error"] == "sin_favoritos"
    m.agregar_equipo(db_session, "9", "Arsenal")
    r = m.configurar_avisos(db_session, "9", True)
    assert r["ok"] and r["avisos"] is True and db_session.get(BotPreferencias, "9").avisos == 1
    assert m.configurar_avisos(db_session, "9", False)["avisos"] is False and db_session.get(BotPreferencias, "9").avisos == 0


def test_el_aviso_llega_solo_a_quien_lo_activo_y_conserva_el_consentimiento(db_session):
    partidos = [{"local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "hora_chile": "14:00"}, {"local": "Betis", "visitante": "Sevilla", "liga": "LaLiga"}]
    for uid, activar in (("a", True), ("b", False), ("c", True)):
        m.aceptar(db_session, uid)
        m.agregar_equipo(db_session, uid, "Arsenal")
        if activar:
            m.configurar_avisos(db_session, uid, True)
    m.revocar(db_session, "c")  # revocar borra los favoritos y corta el aviso
    db_session.query(BotPreferencias).filter_by(user_id="c").update({"avisos": 1})
    db_session.commit()
    r = m.avisos_del_dia(db_session, partidos)
    assert list(r) == ["a"] and r["a"][0]["local"] == "Arsenal" and len(r["a"]) == 1
    assert m.avisos_del_dia(db_session, [{"local": "Otro", "visitante": "Equipo", "liga": "X"}]) == {}


def test_enviar_avisos_manda_un_mensaje_sin_pronostico_y_cuenta_los_fallos(db_session, monkeypatch):
    import asyncio

    from backend.api.models.partidos import PartidoDia
    from backend.api.services import avisos_favoritos as av

    for uid in ("u1", "u2"):
        m.aceptar(db_session, uid)
        m.agregar_equipo(db_session, uid, "Real Madrid")
        m.configurar_avisos(db_session, uid, True)
    db_session.add(PartidoDia(match_id="1", fecha="2026-11-12", status="scheduled", liga_nombre="LaLiga", local="Real Madrid", visitante="Getafe", hora_chile="16:00"))
    db_session.commit()
    monkeypatch.setattr(av.pronosticables, "listar_pronosticables", lambda db, f: {"partidos": [{"match_id": "1", "liga": "LaLiga", "local": "Real Madrid", "visitante": "Getafe", "hora_chile": "16:00"}]})
    enviados = []

    async def enviar(client, chat_id, texto):
        enviados.append((chat_id, texto))
        return chat_id == "u1"

    r = asyncio.run(av.enviar_avisos(db_session, None, "2026-11-12", enviar))
    assert r == {"fecha": "2026-11-12", "candidatos": 2, "enviados": 1, "fallidos": 1}
    assert all("Real Madrid vs Getafe" in t and "%" not in t and "pronóstico" not in t.lower() for _, t in enviados)


def test_el_trabajo_de_avisos_esta_apagado_por_defecto_y_cuando_se_enciende_llama_al_servicio(monkeypatch):
    import asyncio

    from backend.api import main
    from backend.api.core.config import settings
    from backend.api.services import avisos_favoritos as av

    llamadas = []

    async def falso(db, client, fecha, enviar=None, pronostico=None, ahora=None):
        llamadas.append(fecha)
        assert pronostico is av.pronostico_del_modelo and ahora is not None  # MS-4: pronóstico del modelo y horario activo
        return {"enviados": 0}

    monkeypatch.setattr(av, "enviar_avisos", falso)
    monkeypatch.setattr(settings, "AVISOS_FAVORITOS", False)
    asyncio.run(main._job_avisos_favoritos())
    assert llamadas == []
    monkeypatch.setattr(settings, "AVISOS_FAVORITOS", True)
    asyncio.run(main._job_avisos_favoritos())
    assert len(llamadas) == 1 and len(llamadas[0]) == 10
