"""AU-1 a AU-4: hora real del partido, cola de verificación y cierre automático, probados de punta a punta con las migraciones reales y un reloj simulado.

Solo la fuente de resultados (el exterior) es falsa; la cola, el cierre, los modelos y la base son los reales."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.api.core import horario
from backend.api.db import analisis_repo_guardado as guardado
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.models.verificacion import Verificacion
from backend.api.services import laboratorio_pronosticos as lab, verificacion as v

INICIO = datetime(2026, 11, 14, 21, 0)          # 18:00 en Chile (UTC−3 en noviembre)
INICIO_TXT = "2026-11-14T21:00:00"


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    yield s
    s.close()


class Reloj:
    """Una fuente de resultados falsa que responde según un guion por instante; cuenta las consultas."""

    def __init__(self, guion: list[tuple[datetime, dict | None]]):
        self.guion, self.consultas, self.ahora = guion, 0, INICIO

    async def __call__(self, client, fila):
        self.consultas += 1
        respuesta = None
        for desde, d in self.guion:
            if self.ahora >= desde:
                respuesta = d
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def correr(db, reloj, ahora):
    reloj.ahora = ahora
    return asyncio.run(v.procesar_vencidas(db, None, ahora=ahora, fuente=reloj))


def _encolar(db, pid="P1", inicio=INICIO_TXT, **k):
    return v.encolar(db, partido_id=pid, fecha_partido="2026-11-14", local="Colo-Colo", visitante="Cobreloa", liga="Chile", inicio_utc=inicio, ahora=INICIO - timedelta(hours=3), **k)


# ---------------------------------------------------------------- AU-1: la hora real
def test_la_hora_de_livescore_viene_en_utc_mas_7_no_en_hora_de_chile():
    assert horario.esd_livescore_a_utc("20261102024500") == datetime(2026, 11, 1, 19, 45)     # Juventus–Napoli: 02:45 «hora LiveScore» = 19:45 UTC = 20:45 en Turín
    assert horario.esd_livescore_a_utc("202611020030") == datetime(2026, 11, 1, 17, 30)
    assert horario.esd_livescore_a_utc("2026110") is None and horario.esd_livescore_a_utc(None) is None


@pytest.mark.parametrize("utc, esperado", [("2026-11-14T21:00:00", "18:00"), ("2026-07-14T21:00:00", "17:00"), ("2026-01-14T21:00:00", "18:00"), ("2026-11-14T02:30:00", "23:30")])
def test_chile_usa_su_horario_de_verano_y_no_un_menos_cuatro_fijo(utc, esperado):
    assert horario.hora_chile(utc) == esperado


def test_un_partido_de_madrugada_utc_es_del_dia_anterior_en_chile():
    assert horario.fecha_chile("2026-11-14T02:30:00") == "2026-11-13"


def test_el_timestamp_de_api_football_se_convierte_a_hora_de_chile_con_su_verano():
    ts = int(datetime(2026, 11, 14, 21, 0, tzinfo=ZoneInfo("UTC")).timestamp())
    assert horario.esd_chile_de_timestamp(ts) == "202611141800"


# ---------------------------------------------------------------- AU-2: la cola
def test_encolar_programa_la_primera_verificacion_a_inicio_mas_140_minutos_y_es_idempotente(db):
    fila = _encolar(db)
    assert fila.proximo_intento == "2026-11-14T23:20:00" and fila.estado == "pendiente" and fila.inicio_utc == INICIO_TXT
    assert _encolar(db) is fila and db.query(Verificacion).count() == 1


def test_sin_hora_conocida_busca_el_inicio_en_partidos_dia_aunque_la_fecha_sea_la_del_analisis(db):
    db.add(PartidoDia(fecha="2026-11-15", match_id="P2", liga_slug="x", liga_nombre="Chile", local="A", visitante="B", hora_chile="18:00", status="scheduled",
                      kick_off_utc=INICIO_TXT, creado_en="2026-11-14T00:00:00", cache_invalidado=0))
    db.commit()
    fila = v.encolar(db, partido_id="P2", fecha_partido="2026-11-14", local="A", visitante="B", ahora=INICIO - timedelta(hours=5))
    assert fila.inicio_utc == INICIO_TXT and fila.proximo_intento == "2026-11-14T23:20:00"


def test_si_la_hora_se_conoce_despues_se_completa_la_fila_abierta(db):
    fila = v.encolar(db, partido_id="P3", fecha_partido="2026-11-14", local="A", visitante="B", ahora=INICIO - timedelta(hours=5))
    assert fila.inicio_utc is None
    v.encolar(db, partido_id="P3", fecha_partido="2026-11-14", local="A", visitante="B", inicio_utc=INICIO_TXT, ahora=INICIO - timedelta(hours=4))
    assert db.get(Verificacion, "P3").proximo_intento == "2026-11-14T23:20:00"


def test_antes_de_inicio_mas_140_no_se_consulta_nada(db):
    _encolar(db)
    reloj = Reloj([(INICIO, {"status": "FT", "goles_local": 1, "goles_visitante": 0})])
    assert correr(db, reloj, INICIO + timedelta(minutes=139))["revisadas"] == 0 and reloj.consultas == 0


# ---------------------------------------------------------------- AU-3: el cierre único (de punta a punta)
def _pronosticos(db, pid="P1"):
    guardado.guardar_comparativo(db, partido_id=pid, fecha="2026-11-13", local="Colo-Colo", visitante="Cobreloa", liga="Chile", pick_final="Colo-Colo",
                                 prob_local_py=0.5, prob_empate_py=0.25, prob_visit_py=0.25, kick_off_utc=INICIO_TXT)
    lab.registrar_pronostico(db, experimento_codigo=_experimento(db), partido_id=pid, fecha_partido="2026-11-14", local="Colo-Colo", visitante="Cobreloa", fuente="t", variante="v",
                             corte_datos_en="2026-11-14T10:00:00", hora_kickoff=INICIO_TXT, pick="local", prob_local=0.5, prob_empate=0.25, prob_visitante=0.25,
                             goles_local_esperados=1.6, goles_visitante_esperados=1.0)
    db.commit()


def _experimento(db):
    lab.asegurar_experimentos_base(db)
    from backend.api.models.predicciones import ExperimentoPronostico

    return db.query(ExperimentoPronostico).filter(ExperimentoPronostico.permite_consenso == 0).first().codigo


def test_el_analisis_pedido_por_una_persona_queda_en_la_cola_con_la_fecha_del_partido_y_no_la_del_analisis(db):
    _pronosticos(db)
    fila = db.get(Verificacion, "P1")
    assert fila is not None and fila.inicio_utc == INICIO_TXT and fila.fecha_partido == "2026-11-14" and fila.proximo_intento == "2026-11-14T23:20:00"


def test_partido_a_las_18_se_verifica_a_las_2020_y_si_sigue_en_juego_se_reintenta_hasta_cerrar(db):
    _pronosticos(db)
    reloj = Reloj([(INICIO, None), (INICIO + timedelta(minutes=140), {"status": "2H"}), (INICIO + timedelta(minutes=161), {"status": "FT", "goles_local": 2, "goles_visitante": 1, "liga": "Chile", "fuente": "falsa"})])
    r1 = correr(db, reloj, INICIO + timedelta(minutes=140))
    assert r1["en_juego"] == 1 and db.get(Verificacion, "P1").proximo_intento == "2026-11-14T23:40:00"           # reintento a los 20 min
    assert correr(db, reloj, INICIO + timedelta(minutes=150))["revisadas"] == 0                                    # aún no vence
    r2 = correr(db, reloj, INICIO + timedelta(minutes=165))
    assert r2["final"] == 1
    fila = db.get(Verificacion, "P1")
    assert (fila.estado, fila.goles_local, fila.goles_visitante, fila.intentos) == ("final", 2, 1, 2)
    # un solo cierre actualiza TODO lo enlazado: la tabla de resultados, el comparativo y la observación del laboratorio (con los goles de cada equipo)
    assert db.query(ResultadoPartido).filter_by(fixture_id="P1").one().goles_local == 2
    comp = db.query(AnalisisComparativo).filter_by(partido_id="P1").one()
    assert comp.resultado_real == "2-1" and comp.goles_local == 2 and comp.goles_visitante == 1
    from backend.api.models.predicciones import PronosticoExperimental

    obs = db.query(PronosticoExperimental).filter_by(partido_id="P1").one()
    assert (obs.goles_local_real, obs.goles_visitante_real, obs.pick_correcto) == (2, 1, 1)
    assert correr(db, reloj, INICIO + timedelta(days=1))["revisadas"] == 0 and reloj.consultas == 2              # lo cerrado no se vuelve a consultar


def test_un_resultado_ya_conocido_en_la_base_cierra_sin_gastar_ninguna_fuente_externa(db):
    _pronosticos(db)
    db.add(ResultadoPartido(fixture_id="P1", local="Colo-Colo", visitante="Cobreloa", liga="Chile", goles_local=0, goles_visitante=0, ganador="empate", status_api="FT",
                            fecha_partido="2026-11-14", actualizado_en="2026-11-14 23:00:00"))
    db.commit()
    r = asyncio.run(v.procesar_vencidas(db, None, ahora=INICIO + timedelta(minutes=145), fuente=v.FuenteReal(db)))
    assert r["final"] == 1 and db.get(Verificacion, "P1").ultima_fuente == "base"


# ---------------------------------------------------------------- AU-4 y escenarios adversos
def test_un_backend_apagado_seis_horas_recupera_todo_en_una_corrida_sin_duplicar(db):
    for i in range(3):
        _encolar(db, pid=f"R{i}")
    reloj = Reloj([(INICIO, {"status": "FT", "goles_local": 1, "goles_visitante": 1, "liga": "Chile"})])
    r = correr(db, reloj, INICIO + timedelta(hours=9))
    assert r["final"] == 3 and db.query(ResultadoPartido).count() == 3
    assert correr(db, reloj, INICIO + timedelta(hours=10))["revisadas"] == 0 and db.query(ResultadoPartido).count() == 3


def test_una_fuente_caida_solo_cuenta_como_intento_y_se_reintenta_despues(db):
    _encolar(db)
    reloj = Reloj([(INICIO, RuntimeError("503 del proveedor")), (INICIO + timedelta(hours=4), {"status": "FT", "goles_local": 3, "goles_visitante": 0, "liga": "Chile"})])
    assert correr(db, reloj, INICIO + timedelta(minutes=145))["pendiente"] == 1
    fila = db.get(Verificacion, "P1")
    assert fila.intentos == 1 and "503" in (fila.ultimo_error or "") and fila.proximo_intento == "2026-11-14T23:45:00"
    assert correr(db, reloj, INICIO + timedelta(hours=5))["final"] == 1


def test_un_partido_aplazado_se_reprograma_cada_dia_y_se_cierra_cuando_se_juega(db):
    _encolar(db)
    reloj = Reloj([(INICIO, {"status": "PST"}), (INICIO + timedelta(days=2), {"status": "FT", "goles_local": 1, "goles_visitante": 2, "liga": "Chile"})])
    assert correr(db, reloj, INICIO + timedelta(minutes=145))["aplazado"] == 1
    fila = db.get(Verificacion, "P1")
    assert fila.estado == "aplazado" and fila.proximo_intento == "2026-11-15T23:25:00"
    assert correr(db, reloj, INICIO + timedelta(days=2, minutes=5))["final"] == 1


def test_un_partido_cancelado_se_cierra_sin_resultado_y_marca_el_comparativo(db):
    _pronosticos(db)
    reloj = Reloj([(INICIO, {"status": "CANC"})])
    assert correr(db, reloj, INICIO + timedelta(minutes=145))["sin_resultado"] == 1
    assert db.query(AnalisisComparativo).filter_by(partido_id="P1").one().resultado_real == "CANC" and db.query(ResultadoPartido).count() == 0


def test_tres_dias_sin_dato_cierran_como_sin_resultado_y_no_inventan_nada(db):
    _encolar(db)
    reloj = Reloj([(INICIO, None)])
    for minutos in (145, 170, 200, 260, 400, 700):
        correr(db, reloj, INICIO + timedelta(minutes=minutos))
    correr(db, reloj, INICIO + timedelta(days=4))
    fila = db.get(Verificacion, "P1")
    assert fila.estado == "sin_resultado" and fila.goles_local is None and db.query(ResultadoPartido).count() == 0


def test_la_cola_rescata_lo_que_quedo_sin_resultado_antes_de_existir(db):
    db.add(AnalisisComparativo(partido_id="VIEJO", fecha="2026-11-10", local="A", visitante="B", liga="x", pick_final="A", creado_en="2026-11-10 10:00:00"))
    db.commit()
    assert v.sembrar_pendientes(db, ahora=INICIO) == 1 and v.sembrar_pendientes(db, ahora=INICIO) == 0
    assert db.get(Verificacion, "VIEJO").estado == "pendiente"


def test_el_estado_de_la_cola_cuenta_las_atrasadas_para_el_health(db):
    _encolar(db)
    assert v.estado_cola(db, INICIO)["atrasadas"] == 0
    assert v.estado_cola(db, INICIO + timedelta(hours=6))["atrasadas"] == 1


def test_una_cola_rota_nunca_tumba_el_pronostico():
    s = Session(create_engine("sqlite://"))     # sin ninguna tabla
    assert v.encolar_seguro(s, partido_id="X", fecha_partido="2026-11-14", local="A", visitante="B") is False
    s.close()


def test_el_colector_deduce_el_inicio_utc_y_la_hora_de_chile_del_esd_de_livescore():
    from backend.api.services import colector_resultados as col

    stages = [{"Snm": "Serie A", "Cnm": "Italy", "Events": [{"Eid": "9", "Eps": "NS", "T1": [{"Nm": "Juventus"}], "T2": [{"Nm": "Napoli"}], "Esd": "20261102024500"}]}]
    partidos, _, _ = col.parsear_stages(stages, "2026-11-02")
    assert partidos[0]["kick_off_utc"] == "2026-11-01T19:45:00" and partidos[0]["hora_chile"] == "16:45"     # 20:45 en Turín = 16:45 en Chile (UTC−3)


# ---------------------------------------------------------------- fuentes reales (el exterior, simulado en el límite)
def _stages(local, visitante, eps, tr1=None, tr2=None, esd="20261115040000"):
    ev = {"Eid": "L1", "Eps": eps, "T1": [{"Nm": local}], "T2": [{"Nm": visitante}], "Esd": esd}
    if tr1 is not None:
        ev["Tr1"], ev["Tr2"] = str(tr1), str(tr2)
    return [{"Snm": "Primera", "Cnm": "Chile", "Events": [ev]}]


def test_livescore_por_fecha_cierra_varios_partidos_con_una_sola_peticion_y_prueba_el_dia_siguiente(db, monkeypatch):
    from backend.api.core.config import settings
    from backend.api.services import colector_resultados as col

    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "clave-falsa")
    pedidas = []

    async def pedir(client, fecha_raw):
        pedidas.append(fecha_raw)
        return (_stages("Colo-Colo", "Cobreloa", "FT", 2, 1) if fecha_raw == "20261115" else []), "99"      # un partido de la noche de Chile cae al día siguiente en LiveScore (UTC+7)

    monkeypatch.setattr(col, "pedir_livescore6", pedir)
    _encolar(db, pid="L1")
    fuente = v.FuenteReal(db)
    r = asyncio.run(v.procesar_vencidas(db, object(), ahora=INICIO + timedelta(minutes=145), fuente=fuente))
    fila = db.get(Verificacion, "L1")
    assert r["final"] == 1 and (fila.goles_local, fila.goles_visitante, fila.ultima_fuente) == (2, 1, "livescore")
    assert pedidas == ["20261114", "20261115"]


def test_livescore_respeta_el_tope_de_fechas_por_corrida_y_nunca_inventa_un_resultado(db, monkeypatch):
    from backend.api.core.config import settings
    from backend.api.services import colector_resultados as col

    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "clave-falsa")
    pedidas = []

    async def pedir(client, fecha_raw):
        pedidas.append(fecha_raw)
        return _stages("Otro", "Equipo", "NS"), "5"

    monkeypatch.setattr(col, "pedir_livescore6", pedir)
    monkeypatch.setattr(v.settings, "BSD_API_KEY", "", raising=False)
    for i in range(4):
        v.encolar(db, partido_id=f"T{i}", fecha_partido=f"2026-11-{10 + i}", local="Colo-Colo", visitante="Cobreloa", inicio_utc=f"2026-11-{10 + i}T21:00:00", ahora=INICIO - timedelta(days=6))
    asyncio.run(v.procesar_vencidas(db, object(), ahora=INICIO, fuente=v.FuenteReal(db, tope_apif=0)))
    assert len(pedidas) == v.MAX_FECHAS_LIVESCORE_POR_CORRIDA and db.query(ResultadoPartido).count() == 0


def test_api_football_gratis_recibe_un_solo_partido_por_id_y_no_por_ids():
    from backend.api.services import resultados as svc
    from backend.api.core.config import settings

    urls = []

    class Respuesta:
        status_code = 200
        headers: dict = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": [], "errors": []}

    class Cliente:
        async def get(self, url, **k):
            urls.append(url)
            return Respuesta()

    settings.SPORTS_API_KEY, anterior = "k", settings.SPORTS_API_KEY
    try:
        asyncio.run(svc._consultar_fixtures_apifootball(Cliente(), ["123"]))
        asyncio.run(svc._consultar_fixtures_apifootball(Cliente(), ["1", "2"]))
    finally:
        settings.SPORTS_API_KEY = anterior
    assert urls[0].endswith("fixtures?id=123") and urls[1].endswith("fixtures?ids=1-2")


# ---------------------------------------------------------------- cierres de esta ronda
def test_mutar_un_estado_no_cambia_el_artefacto_del_que_salio():
    from backend.api.ml.laplace import entrenamiento as ent

    art = {"elo": {"A": 1500.0}, "gf": {"A": 1.4}, "gc": {"A": 1.1}, "n": {"A": 5}, "media_local": 1.5, "media_visita": 1.1, "total_partidos": 10, "forma": {"A": 1.8}, "t_for": {"A": 11.0}}
    e = ent.EstadoLiga.de_dict(art)
    e.actualizar("A", "B", 3, 0)
    assert art["elo"] == {"A": 1500.0} and art["n"] == {"A": 5} and art["gf"] == {"A": 1.4} and art["forma"] == {"A": 1.8} and art["t_for"] == {"A": 11.0}
    assert ent.EstadoLiga.de_dict(art).elo == {"A": 1500.0}                      # un segundo recorrido parte del mismo punto


def test_las_cuotas_traen_cuando_se_consultaron_y_cuanto_falta_para_el_inicio(monkeypatch, db):
    from backend.api.services import odds_fetch

    async def cascada(*a, **k):
        return {"odds_local": 2.0, "odds_disponibles": True}

    monkeypatch.setattr(odds_fetch, "_cascada_odds", cascada)
    monkeypatch.setattr(odds_fetch, "utc_ahora", lambda: datetime(2026, 11, 14, 19, 0))
    r = asyncio.run(odds_fetch.obtener_odds_partido(None, db, "A", "B", None, None, "2026-11-14", INICIO_TXT))
    assert r["odds_consultadas_en"] == "2026-11-14T19:00:00" and r["odds_min_al_inicio"] == 120 and r["odds_local"] == 2.0
    assert asyncio.run(odds_fetch.obtener_odds_partido(None, db, "A", "B", None, None, "2026-11-14"))["odds_min_al_inicio"] is None


def test_el_aviso_de_verificaciones_atrasadas_sale_una_vez_al_dia_y_solo_con_varias(db, monkeypatch):
    from backend.api import main
    from backend.api.core.config import settings
    from backend.api.services import telegram_client

    enviados = []

    async def enviar(client, chat, texto, *a, **k):
        enviados.append(texto)
        return True

    monkeypatch.setattr(telegram_client, "enviar_mensaje", enviar)
    monkeypatch.setattr(settings, "SPORTS_ADMIN_ID", "1")
    asyncio.run(main._avisar_verificaciones_atrasadas(db, None, 4))
    assert enviados == []
    asyncio.run(main._avisar_verificaciones_atrasadas(db, None, 7))
    asyncio.run(main._avisar_verificaciones_atrasadas(db, None, 9))
    assert len(enviados) == 1 and "7 verificaciones" in enviados[0]


def test_el_laboratorio_acepta_el_reloj_simulado_al_encolar(db):
    lab.asegurar_experimentos_base(db)
    lab.registrar_pronostico(db, experimento_codigo=_experimento(db), partido_id="R1", fecha_partido="2026-11-14", local="A", visitante="B", fuente="t", variante="v",
                             corte_datos_en="2026-11-14T10:00:00Z", hora_kickoff=INICIO_TXT, pick="local", prob_local=0.5, prob_empate=0.25, prob_visitante=0.25, ahora=datetime(2020, 1, 1))
    assert db.get(Verificacion, "R1").creado_en == "2020-01-01T00:00:00"
