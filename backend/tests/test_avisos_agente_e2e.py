"""MS-12: recorrido de punta a punta «seguir → avisar → resultado» desde el agente, sobre una base construida con las MIGRACIONES REALES y el agente real (`procesar_mensaje`).

Solo el exterior va simulado: Telegram (`enviar`), la lista de partidos programados (que valida contra datos históricos no publicados) y el modelo (`pronostico`).
Matriz de estados: esquema al día o atrasado, con y sin consentimiento, avisos activados o no, con y sin pronóstico, fuente caída, modelo caído, fuera de horario,
partido de lo que se sigue o ajeno, doble ejecución, envío fallido, tope por usuario."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from backend.api.db import bot_memoria_repo
from backend.api.models.bot_memoria import BotAvisoEnviado
from backend.api.models.usuarios import Usuario
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.services import agent_runtime, avisos_favoritos as av

CHILE = ZoneInfo("America/Santiago")
DIA = "2026-11-20"
MEDIODIA = datetime(2026, 11, 20, 12, 0, tzinfo=CHILE)
MADRUGADA = datetime(2026, 11, 20, 5, 0, tzinfo=CHILE)
PRON = {"local": 0.55, "empate": 0.25, "visitante": 0.20}
TG = "telegram:777"


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def telegram():
    class Telegram:
        def __init__(self):
            self.enviados, self.falla = [], False

        async def enviar(self, client, chat_id, texto):
            if self.falla:
                return False
            self.enviados.append((chat_id, texto))
            return True

    return Telegram()


@pytest.fixture(autouse=True)
def _partidos_programados(monkeypatch):
    """La lista real valida contra datos históricos no publicados: se sustituye por los programados de la base, sin tocar nada más."""
    def listar(db, fecha):
        filas = db.query(PartidoDia).filter(PartidoDia.fecha == fecha, PartidoDia.status == "scheduled").all()
        return {"partidos": [{"match_id": f.match_id, "liga": f.liga_nombre, "local": f.local, "visitante": f.visitante, "hora_chile": f.hora_chile} for f in filas]}

    monkeypatch.setattr(av.pronosticables, "listar_pronosticables", listar)


def _decir(db, texto, user=TG):
    return asyncio.run(agent_runtime.procesar_mensaje(db, user, texto, None, "telegram_agent", False, False))["respuesta"]


def _partido(db, match_id="1", local="Real Madrid", visitante="Getafe", liga="LaLiga", hora="16:00"):
    db.add(PartidoDia(match_id=match_id, fecha=DIA, status="scheduled", liga_nombre=liga, local=local, visitante=visitante, hora_chile=hora))
    db.commit()


def _resultado(db, match_id, gl, gv, local="Real Madrid", visitante="Getafe"):
    db.add(ResultadoPartido(fixture_id=match_id, local=local, visitante=visitante, goles_local=gl, goles_visitante=gv, fecha_partido=DIA, actualizado_en="x"))
    db.commit()


def _avisar(db, telegram, pronostico=lambda d, p: PRON, ahora=MEDIODIA):
    return asyncio.run(av.enviar_avisos(db, None, DIA, telegram.enviar, pronostico, ahora))


def _finales(db, telegram, ahora=MEDIODIA):
    return asyncio.run(av.enviar_resultados(db, None, telegram.enviar, ahora))


def _siguiendo(db, equipo="Real Madrid", avisos=True):
    assert "acepto" in _decir(db, f"sigue al {equipo}").lower()
    assert "guardaré" in _decir(db, "acepto")
    assert "Ahora sigues" in _decir(db, f"sigue al {equipo}")
    if avisos:
        assert "Avisos activados" in _decir(db, "activa los avisos")


# ---------------------------------------------------------------- el recorrido completo
def test_seguir_avisar_y_dar_el_resultado_con_acierto_de_punta_a_punta(db, telegram):
    _siguiendo(db)
    _partido(db)
    r = _avisar(db, telegram)
    assert r == {"fecha": DIA, "candidatos": 1, "enviados": 1, "fallidos": 0}
    chat, texto = telegram.enviados[0]
    assert chat == "777" and "Real Madrid vs Getafe" in texto and "(16:00)" in texto and "LaLiga" in texto            # cuándo, contra quién y dónde (liga)
    assert "Modelo: Local 55% · Empate 25% · Visitante 20%" in texto and av.NOTA_ESTIMACION in texto
    assert _avisar(db, telegram)["candidatos"] == 0 and len(telegram.enviados) == 1                                   # doble ejecución: un aviso por partido

    assert _finales(db, telegram)["candidatos"] == 0                                                                  # sin resultado todavía: silencio
    _resultado(db, "1", 2, 0)
    assert _finales(db, telegram) == {"candidatos": 1, "enviados": 1, "fallidos": 0}
    assert "Real Madrid 2-0 Getafe" in telegram.enviados[1][1] and "acertó ✅" in telegram.enviados[1][1]
    assert _finales(db, telegram)["candidatos"] == 0 and len(telegram.enviados) == 2                                  # un final por partido


def test_el_resultado_dice_cuando_el_modelo_no_acerto(db, telegram):
    _siguiendo(db)
    _partido(db)
    _avisar(db, telegram)
    _resultado(db, "1", 0, 1)
    _finales(db, telegram)
    assert "no acertó ❌" in telegram.enviados[1][1]


# ---------------------------------------------------------------- matriz de estados
def test_sin_pronostico_del_modelo_el_aviso_sale_sin_inventar_nada(db, telegram):
    _siguiendo(db)
    _partido(db)
    _avisar(db, telegram, pronostico=lambda d, p: None)
    texto = telegram.enviados[0][1]
    assert "Real Madrid vs Getafe" in texto and "%" not in texto and "Modelo" not in texto
    _resultado(db, "1", 1, 1)
    _finales(db, telegram)
    assert "acertó" not in telegram.enviados[1][1] and "Real Madrid 1-1 Getafe" in telegram.enviados[1][1]


def test_si_el_modelo_falla_el_aviso_sale_igual_sin_pronostico(db, telegram):
    _siguiendo(db)
    _partido(db)

    def roto(d, p):
        raise RuntimeError("modelo caído")

    assert _avisar(db, telegram, pronostico=roto)["enviados"] == 1 and "Modelo" not in telegram.enviados[0][1]


def test_si_la_fuente_de_partidos_cae_no_se_envia_nada_ni_se_rompe(db, telegram, monkeypatch):
    _siguiendo(db)

    def caida(*_a):
        raise ConnectionError("503")

    monkeypatch.setattr(av.pronosticables, "listar_pronosticables", caida)
    r = _avisar(db, telegram)
    assert r["omitido"] == "partidos no disponibles" and r["enviados"] == 0 and telegram.enviados == []


def test_fuera_del_horario_activo_no_se_envia_y_despues_si(db, telegram):
    _siguiendo(db)
    _partido(db)
    assert _avisar(db, telegram, ahora=MADRUGADA)["omitido"] == "fuera del horario de avisos" and telegram.enviados == []
    assert _avisar(db, telegram, ahora=MEDIODIA)["enviados"] == 1


def test_sin_avisos_activados_o_con_los_avisos_apagados_no_llega_nada(db, telegram):
    _siguiendo(db, avisos=False)
    _partido(db)
    assert _avisar(db, telegram)["candidatos"] == 0
    _decir(db, "activa los avisos")
    assert _avisar(db, telegram)["enviados"] == 1
    _partido(db, "2", "Real Madrid", "Sevilla", hora="19:00")
    assert "no te enviaré avisos" in _decir(db, "apaga los avisos")
    assert _avisar(db, telegram)["candidatos"] == 0


def test_activar_los_avisos_sin_seguir_nada_o_sin_consentimiento_lo_dice(db):
    assert "acepto" in _decir(db, "activa los avisos").lower()
    _decir(db, "acepto")
    assert "Primero dime qué sigues" in _decir(db, "activa los avisos")


def test_un_partido_ajeno_a_lo_que_se_sigue_deja_en_silencio(db, telegram):
    _siguiendo(db, "Barcelona")
    _partido(db)
    assert _avisar(db, telegram) == {"fecha": DIA, "candidatos": 0, "enviados": 0, "fallidos": 0} and telegram.enviados == []


def test_si_revoca_el_consentimiento_no_llega_el_aviso_ni_el_final(db, telegram):
    _siguiendo(db)
    _partido(db)
    _avisar(db, telegram)
    bot_memoria_repo.revocar(db, "777")
    _resultado(db, "1", 2, 0)
    assert _finales(db, telegram)["candidatos"] == 0 and len(telegram.enviados) == 1
    assert db.query(BotAvisoEnviado).count() == 0                                   # revocar borra también lo que dependía del consentimiento


def test_un_envio_fallido_no_se_da_por_enviado_y_se_reintenta(db, telegram):
    _siguiendo(db)
    _partido(db)
    telegram.falla = True
    assert _avisar(db, telegram) == {"fecha": DIA, "candidatos": 1, "enviados": 0, "fallidos": 1}
    assert db.query(BotAvisoEnviado).count() == 0
    telegram.falla = False
    assert _avisar(db, telegram)["enviados"] == 1


def test_el_tope_por_usuario_limita_los_partidos_avisados_en_24_horas(db, telegram):
    assert "guardaré" in _decir(db, "acepto") and "Ahora sigues" in _decir(db, "sigue laliga")        # seguir una liga registra a la persona como free
    db.query(Usuario).filter(Usuario.device_id == "777").update({"plan": "pro"})                        # MS-11: el cupo de 6 en 24 h es el del plan pro
    db.commit()
    _decir(db, "activa los avisos")
    for i in range(8):
        _partido(db, str(i), f"Local {i}", f"Visita {i}")
    assert _avisar(db, telegram)["enviados"] == 1 and telegram.enviados[0][1].count("•") == av.MAX_PARTIDOS_POR_AVISO
    assert _avisar(db, telegram)["enviados"] == 1 and telegram.enviados[1][1].count("•") == 1                     # el cupo de 6 en 24 h deja pasar solo 1
    assert _avisar(db, telegram)["candidatos"] == 0                                                              # cupo agotado: los 2 restantes esperan


def test_con_el_plan_free_el_cupo_de_avisos_es_de_3_partidos(db, telegram):
    _decir(db, "acepto")
    _decir(db, "sigue laliga")
    _decir(db, "activa los avisos")
    for i in range(8):
        _partido(db, str(i), f"Local {i}", f"Visita {i}")
    assert _avisar(db, telegram)["enviados"] == 1 and telegram.enviados[0][1].count("•") == 3
    assert _avisar(db, telegram)["candidatos"] == 0                                                               # cupo free agotado


def test_olvidame_borra_los_avisos_enviados(db, telegram):
    _siguiendo(db)
    _partido(db)
    _avisar(db, telegram)
    assert db.query(BotAvisoEnviado).count() == 1
    assert bot_memoria_repo.olvidar(db, "777")["bot_avisos_enviados"] == 1 and db.query(BotAvisoEnviado).count() == 0


def test_con_el_esquema_atrasado_no_se_envia_nada_en_vez_de_repetir_avisos(base_migrada, telegram):
    s = base_migrada("a7c9e1f3b5d2")()                                              # la revisión anterior a `bot_avisos_enviados`
    assert s.execute(text("SELECT name FROM sqlite_master WHERE name = 'bot_avisos_enviados'")).first() is None
    bot_memoria_repo.aceptar(s, "777")
    bot_memoria_repo.agregar_equipo(s, "777", "Real Madrid")
    bot_memoria_repo.configurar_avisos(s, "777", True)
    s.add(PartidoDia(match_id="1", fecha=DIA, status="scheduled", liga_nombre="LaLiga", local="Real Madrid", visitante="Getafe", hora_chile="16:00"))
    s.commit()
    r = asyncio.run(av.enviar_avisos(s, None, DIA, telegram.enviar, lambda d, p: PRON, MEDIODIA))
    assert r["omitido"] == "no se pudo comprobar lo ya enviado" and telegram.enviados == []
    assert asyncio.run(av.enviar_resultados(s, None, telegram.enviar, MEDIODIA))["omitido"] == "no se pudo comprobar lo ya enviado"
    s.close()


def test_la_migracion_real_crea_la_tabla_con_clave_unica(db):
    db.add(BotAvisoEnviado(user_id="1", partido_id="p", tipo="previo", enviado_en="2026-11-20T10:00:00Z"))
    db.commit()
    db.add(BotAvisoEnviado(user_id="1", partido_id="p", tipo="previo", enviado_en="2026-11-20T11:00:00Z"))
    with pytest.raises(Exception, match="UNIQUE"):
        db.commit()
    db.rollback()
