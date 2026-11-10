"""test_colector_resultados.py — colector diario de resultados (sin red: la fuente se simula).

Cubre: persistencia del día completo, registro solo de ligas con modelo, idempotencia, que un estado
terminado no retroceda, `cache_invalidado` respetado, tope diario de peticiones, fechas inválidas,
fallo de la fuente y el job de `main.py` (registra la corrida y nunca rompe el backend).
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api import main
from backend.api.core.config import settings
from backend.api.db import partidos_repo, scheduler_repo
from backend.api.db.session import Base
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.routers import scheduler as scheduler_router
from backend.api.services import colector_resultados as colector

AHORA = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("America/Santiago"))


def _evento(eid, local, visitante, eps="FT", tr1="1", tr2="0", esd="20261006193000"):
    ev = {"Eid": str(eid), "Eps": eps, "T1": [{"Nm": local}], "T2": [{"Nm": visitante}], "Esd": int(esd)}
    if tr1 is not None:
        ev["Tr1"], ev["Tr2"] = tr1, tr2
    return ev


def _stage(nombre, pais, *eventos):
    return {"Snm": nombre, "Cnm": pais, "Events": list(eventos)}


def _dia_tipico(base=0, chile_eps="FT"):
    return [
        _stage("Primera A: Clausura", "Colombia",
               _evento(base + 1001, "Millonarios", "Junior", "FT", "2", "1"),
               _evento(base + 1002, "Santa Fe", "Nacional", "FT", "0", "0")),
        _stage("Premier League", "Jamaica", _evento(base + 2001, "Harbour View", "Portmore", "FT", "3", "1")),
        _stage("Primera División", "Chile", _evento(base + 3001, "Colo Colo", "Huachipato", chile_eps, "1", "0")),
    ]


def _clasificador(nombre, pais, local, visitante):
    # Misma lógica que el real: la liga debe coincidir en país; Jamaica no tiene modelo.
    if (nombre, pais) == ("Primera A: Clausura", "Colombia"):
        return "COL1", local != "Santa Fe"
    if (nombre, pais) == ("Primera División", "Chile"):
        return "CHL1", True
    return None, False


class FuenteSimulada:
    def __init__(self, por_fecha=None, falla_en=()):
        self.por_fecha = por_fecha or {}
        self.falla_en = set(falla_en)
        self.llamadas: list[str] = []

    async def __call__(self, client, fecha_raw):
        self.llamadas.append(fecha_raw)
        if fecha_raw in self.falla_en:
            raise RuntimeError("fuente caída")
        # Cada fecha trae ids propios (como la fuente real); 20261006 usa los ids 1001... de los tests.
        base = 0 if fecha_raw == "20261006" else int(fecha_raw[-2:]) * 100000
        return self.por_fecha.get(fecha_raw, _dia_tipico(base)), "400"


@pytest.fixture()
def sesion():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with fabrica() as db:
        db.fabrica = fabrica
        yield db


def _ejecutar(db, fuente, **kwargs):
    kwargs.setdefault("clasificar", _clasificador)
    return asyncio.run(colector.ejecutar_colector(db, None, ahora=AHORA, fuente=fuente, **kwargs))


# ─── estado y parseo ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("eps,esperado", [
    ("FT", "finished"), ("NS", "scheduled"), ("HT", "HT"), ("AET", "AET"), ("AP", "PEN"), ("Aband.", "ABD"),
    ("Postp.", "PST"), ("Canc.", "CANC"), ("23'", "1H"), ("45+2'", "1H"), ("67'", "2H"), ("90+3'", "2H"), ("???", "SUSP"),
])
def test_estado_desde_eps(eps, esperado):
    assert colector.estado_desde_eps(eps) == esperado


def test_parsear_descarta_terminado_sin_marcador_y_sin_id():
    stages = [_stage("Liga", "Chile", _evento(1, "A", "B", "FT", None, None), _evento("", "C", "D"), _evento(3, "E", "F", "NS", None))]
    partidos, meta, descartes = colector.parsear_stages(stages, "2026-10-06")
    assert [p["match_id"] for p in partidos] == ["3"]
    assert partidos[0]["status"] == "scheduled" and partidos[0]["goles_local"] is None
    assert descartes["terminado_sin_marcador"] == 1 and descartes["sin_id"] == 1
    assert meta[0]["pais"] == "Chile"


# ─── persistencia y ligas con modelo ─────────────────────────────────────────


def test_persiste_el_dia_completo_y_registra_solo_terminados_de_ligas_con_modelo(sesion):
    fuente = FuenteSimulada({"20261006": _dia_tipico(chile_eps="45'")})
    resumen = _ejecutar(sesion, fuente)

    assert resumen["ok"] is True and resumen["peticiones"] == 5
    filas = {(p.fecha, p.match_id): p for p in sesion.query(PartidoDia).all()}
    # El día completo queda en partidos_dia (incluida Jamaica), con goles y estado normalizado.
    assert filas[("2026-10-06", "1001")].status == "finished" and filas[("2026-10-06", "1001")].goles_local == 2
    assert filas[("2026-10-06", "2001")].goles_visitante == 1
    assert filas[("2026-10-06", "3001")].status == "1H"
    # Solo los terminados de ligas con modelo van a resultados_partidos, con la liga calificada por país.
    resultados = sesion.query(ResultadoPartido).filter(ResultadoPartido.fecha_partido == "2026-10-06").all()
    assert sorted(r.fixture_id for r in resultados) == ["1001", "1002"]
    assert {r.liga for r in resultados} == {"Primera A: Clausura (Colombia)"}
    assert {r.status_api for r in resultados} == {"FT"}
    assert resumen["por_liga"]["COL1"] == 2 * 5 and "JAM" not in resumen["por_liga"] and resumen["terminados_sin_modelo"] >= 5
    assert "COL1: Santa Fe" in resumen["equipos_sin_resolver"]


def test_aet_y_penales_no_se_registran_como_resultado(sesion):
    dia = [_stage("Primera A: Clausura", "Colombia", _evento(1, "A", "B", "AET", "2", "2"), _evento(2, "C", "D", "AP", "1", "1"))]
    resumen = _ejecutar(sesion, FuenteSimulada({"20261006": dia}), fechas=["2026-10-06"])
    assert resumen["resultados_registrados"] == 0
    assert {p.status for p in sesion.query(PartidoDia).all()} == {"AET", "PEN"}


def test_idempotente_segunda_corrida_no_duplica_ni_cambia_nada(sesion):
    _ejecutar(sesion, FuenteSimulada())
    antes = (sesion.query(PartidoDia).count(), sesion.query(ResultadoPartido).count())
    fuente2 = FuenteSimulada()
    resumen2 = _ejecutar(sesion, fuente2)

    assert (sesion.query(PartidoDia).count(), sesion.query(ResultadoPartido).count()) == antes
    assert resumen2["resultados_registrados"] == 0
    # Fechas pasadas ya selladas y mañana ya pedido: solo se vuelve a pedir "hoy".
    assert fuente2.llamadas == ["20261007"]
    assert resumen2["selladas_omitidas"] == 3 and resumen2["programada_ya_pedida"] == 1
    assert resumen2["partidos_dia"]["insertados"] == 0 and resumen2["partidos_dia"]["actualizados"] == 0


def test_repetir_la_misma_fecha_forzada_es_idempotente(sesion):
    resumen1 = _ejecutar(sesion, FuenteSimulada(), fechas=["2026-10-07"])
    resumen2 = _ejecutar(sesion, FuenteSimulada(), fechas=["2026-10-07"])
    assert resumen1["partidos_dia"]["insertados"] == 4
    assert resumen2["partidos_dia"] == {"insertados": 0, "actualizados": 0, "sin_cambio": 4, "no_retrocedidos": 0, "conflictos_marcador": 0}


def test_un_terminado_no_retrocede_a_programado_ni_cambia_su_marcador(sesion):
    sesion.add(PartidoDia(fecha="2026-10-06", match_id="1001", liga_nombre="Primera A: Clausura", local="Millonarios",
                          visitante="Junior", status="finished", goles_local=2, goles_visitante=1, cache_invalidado=1))
    sesion.add(PartidoDia(fecha="2026-10-06", match_id="1002", liga_nombre="Primera A: Clausura", local="Santa Fe",
                          visitante="Nacional", status="finished", goles_local=0, goles_visitante=0, cache_invalidado=1))
    sesion.commit()
    dia = [_stage("Primera A: Clausura", "Colombia",
                  _evento(1001, "Millonarios", "Junior", "NS", None),          # retroceso a programado
                  _evento(1002, "Santa Fe", "Nacional", "FT", "4", "4"))]      # marcador distinto
    resumen = _ejecutar(sesion, FuenteSimulada({"20261006": dia}), fechas=["2026-10-06"])

    a, b = sesion.get(PartidoDia, ("2026-10-06", "1001")), sesion.get(PartidoDia, ("2026-10-06", "1002"))
    assert (a.status, a.goles_local, a.goles_visitante) == ("finished", 2, 1)
    assert (b.status, b.goles_local, b.goles_visitante) == ("finished", 0, 0)
    assert resumen["partidos_dia"]["no_retrocedidos"] == 1 and resumen["partidos_dia"]["conflictos_marcador"] == 1


def test_un_programado_o_en_juego_avanza_a_terminado_y_se_invalida(sesion):
    sesion.add(PartidoDia(fecha="2026-10-06", match_id="1001", liga_nombre="x", local="Millonarios", visitante="Junior",
                          status="2H", goles_local=1, goles_visitante=1, cache_invalidado=0))
    sesion.commit()
    _ejecutar(sesion, FuenteSimulada(), fechas=["2026-10-06"])
    fila = sesion.get(PartidoDia, ("2026-10-06", "1001"))
    assert (fila.status, fila.goles_local, fila.goles_visitante, fila.cache_invalidado) == ("finished", 2, 1, 1)
    assert fila.liga_nombre == "x"  # lo ya guardado no se pisa


def test_cache_invalidado_no_se_resetea_en_filas_existentes_y_las_pasadas_nacen_invalidadas(sesion):
    sesion.add(PartidoDia(fecha="2026-10-08", match_id="9", liga_nombre="x", local="a", visitante="b",
                          status="scheduled", cache_invalidado=1))
    sesion.commit()
    partidos_repo.guardar_partidos_sin_retroceso(sesion, "2026-10-08", [
        {"match_id": "9", "status": "scheduled", "local": "a", "visitante": "b"}])
    assert sesion.get(PartidoDia, ("2026-10-08", "9")).cache_invalidado == 1
    partidos_repo.guardar_partidos_sin_retroceso(sesion, "2020-01-01", [
        {"match_id": "p", "status": "scheduled", "local": "a", "visitante": "b"}])
    assert sesion.get(PartidoDia, ("2020-01-01", "p")).cache_invalidado == 1


def test_resultado_con_id_en_colision_o_ya_registrado_con_otro_id_no_se_pisa(sesion):
    sesion.add(ResultadoPartido(fixture_id="1001", local="Otro", visitante="Distinto", liga="x", goles_local=5, goles_visitante=5,
                                ganador="empate", status_api="FT", fecha_partido="2026-09-01", actualizado_en="2026-09-01 00:00:00"))
    sesion.add(ResultadoPartido(fixture_id="1555555", local="Santa Fe", visitante="Nacional", liga="x", goles_local=0,
                                goles_visitante=0, ganador="empate", status_api="FT", fecha_partido="2026-10-06",
                                actualizado_en="2026-10-06 23:00:00"))
    sesion.commit()
    resumen = _ejecutar(sesion, FuenteSimulada(), fechas=["2026-10-06"])
    assert resumen["colisiones_id"] == 1 and resumen["resultados_ya_registrados"] == 1
    assert sesion.query(ResultadoPartido).filter_by(fixture_id="1001").one().local == "Otro"
    assert sesion.query(ResultadoPartido).count() == 3  # + el de Chile (nuevo); ni 1001 ni 1002 se duplican
    assert sesion.query(ResultadoPartido).filter_by(fixture_id="1002").count() == 0


# ─── presupuesto, fechas, fallos ─────────────────────────────────────────────


def test_tope_diario_limita_peticiones_y_persiste_entre_corridas(sesion, monkeypatch):
    monkeypatch.setenv(colector.ENV_MAX_PETICIONES, "2")
    fuente = FuenteSimulada()
    resumen = _ejecutar(sesion, fuente)
    assert resumen["peticiones"] == 2 and resumen["omitidas_por_tope"] == 3
    # Prioridad: ayer y hoy primero.
    assert fuente.llamadas == ["20261006", "20261007"]
    fuente2 = FuenteSimulada()
    resumen2 = _ejecutar(sesion, fuente2)
    assert resumen2["peticiones"] == 0 and fuente2.llamadas == []
    assert colector.consumo_colector_hoy(sesion, "2026-10-07")["peticiones"] == 2


def test_tope_cero_o_invalido(sesion, monkeypatch):
    monkeypatch.setenv(colector.ENV_MAX_PETICIONES, "0")
    assert _ejecutar(sesion, FuenteSimulada())["peticiones"] == 0
    monkeypatch.setenv(colector.ENV_MAX_PETICIONES, "abc")
    assert colector.tope_peticiones_dia() == colector.MAX_PETICIONES_DIA_DEFECTO


def test_fechas_invalidas_se_rechazan_sin_gastar_cuota(sesion):
    fuente = FuenteSimulada()
    resumen = _ejecutar(sesion, fuente, fechas=["2026-02-30", "basura", "2026--0-9-", "2025-01-01", "2026-12-31", "20261007"])
    assert fuente.llamadas == ["20261007"]
    assert resumen["peticiones"] == 1
    assert {r["fecha"] for r in resumen["fechas_rechazadas"]} == {"2026-02-30", "basura", "2026--0-9-", "2025-01-01", "2026-12-31"}
    assert sesion.query(PartidoDia).filter(PartidoDia.fecha.like("%--%")).count() == 0


def test_fuente_que_falla_no_lanza_y_no_sella_ni_bloquea_otras_fechas(sesion):
    fuente = FuenteSimulada(falla_en={"20261006"})
    resumen = _ejecutar(sesion, fuente)
    assert resumen["ok"] is False and resumen["fallidas"] == 1 and resumen["fechas_fallidas"] == ["2026-10-06"]
    assert "2026-10-07" in resumen["fechas_pedidas"]
    assert colector.leer_stats_cache(sesion, "colector:sellada:2026-10-06") is None
    # La corrida siguiente reintenta esa fecha.
    fuente2 = FuenteSimulada()
    _ejecutar(sesion, fuente2)
    assert "20261006" in fuente2.llamadas


def test_respuesta_vacia_no_sella_la_fecha(sesion):
    _ejecutar(sesion, FuenteSimulada({"20261006": None}), fechas=["2026-10-06"])
    assert colector.leer_stats_cache(sesion, "colector:sellada:2026-10-06") is None


def test_sin_clave_livescore_la_fuente_real_falla_sin_red(sesion, monkeypatch):
    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "")
    resumen = asyncio.run(colector.ejecutar_colector(sesion, None, ahora=AHORA, clasificar=_clasificador))
    assert resumen["ok"] is False and resumen["fallidas"] == 5 and sesion.query(PartidoDia).count() == 0


# ─── job de main.py ──────────────────────────────────────────────────────────


def test_job_registra_la_corrida_y_no_rompe_si_la_fuente_falla(sesion, monkeypatch):
    monkeypatch.setattr(main, "SessionLocal", sesion.fabrica)
    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "")  # la fuente real lanza antes de cualquier red
    monkeypatch.setattr(colector, "exportar_capa_vivo", lambda: {"ok": True, "exportado": False, "detalle": "sin exportar"})
    asyncio.run(main._job_colectar_resultados())  # no lanza
    with sesion.fabrica() as db:
        ultimo = scheduler_repo.ultimo_run(db, scheduler_router.JOB_COLECTOR_RESULTADOS)
        assert ultimo is not None and ultimo.ok is False and "fallidas" in ultimo.detalle


def test_job_ok_con_fuente_simulada_registra_ok(sesion, monkeypatch):
    monkeypatch.setattr(main, "SessionLocal", sesion.fabrica)

    original = colector.ejecutar_colector

    async def _fake(db, client, **kwargs):
        return await original(db, client, ahora=AHORA, fuente=FuenteSimulada(), clasificar=_clasificador)

    monkeypatch.setattr(colector, "ejecutar_colector", _fake)
    monkeypatch.setattr(colector, "exportar_capa_vivo", lambda: {"ok": True, "exportado": True, "detalle": "capa en vivo: 3 filas (+3)"})
    asyncio.run(main._job_colectar_resultados())
    with sesion.fabrica() as db:
        ultimo = scheduler_repo.ultimo_run(db, scheduler_router.JOB_COLECTOR_RESULTADOS)
        assert ultimo.ok is True and "capa en vivo" in ultimo.detalle
        assert db.query(ResultadoPartido).count() > 0


def test_job_excepcion_inesperada_se_registra_sin_propagar(sesion, monkeypatch):
    monkeypatch.setattr(main, "SessionLocal", sesion.fabrica)

    async def _explota(db, client, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(colector, "ejecutar_colector", _explota)
    asyncio.run(main._job_colectar_resultados())
    with sesion.fabrica() as db:
        assert scheduler_repo.ultimo_run(db, scheduler_router.JOB_COLECTOR_RESULTADOS).ok is False


def test_job_desactivado_por_entorno_no_hace_nada(sesion, monkeypatch):
    monkeypatch.setattr(main, "SessionLocal", sesion.fabrica)
    monkeypatch.setenv(colector.ENV_ACTIVO, "0")
    asyncio.run(main._job_colectar_resultados())
    with sesion.fabrica() as db:
        assert scheduler_repo.ultimo_run(db, scheduler_router.JOB_COLECTOR_RESULTADOS) is None


def test_el_lifespan_agenda_el_colector_dos_veces_al_dia_y_status_lo_conoce():
    fuente = inspect.getsource(main.lifespan)
    assert 'id="colector_resultados"' in fuente and 'hour="2,12"' in fuente and "_job_colectar_resultados" in fuente
    assert scheduler_router.JOB_COLECTOR_RESULTADOS in scheduler_router.VENTANA_MINUTOS
    # La ventana cubre el hueco más largo entre corridas (02:30 -> 12:30 = 10h; 12:30 -> 02:30 = 14h).
    assert scheduler_router.VENTANA_MINUTOS[scheduler_router.JOB_COLECTOR_RESULTADOS] > 14 * 60


def test_disparo_manual_exige_admin_y_rechaza_fechas_invalidas(sesion, monkeypatch):
    assert any(dep.dependency.__name__ == "requerir_admin" for dep in scheduler_router.router.dependencies)

    original = colector.ejecutar_colector

    async def _con_fuente_simulada(db, client, fechas=None):
        return await original(db, client, ahora=AHORA, fuente=FuenteSimulada(), clasificar=_clasificador, fechas=fechas)

    monkeypatch.setattr(scheduler_router.colector_resultados, "ejecutar_colector", _con_fuente_simulada)
    resumen = asyncio.run(scheduler_router.disparar_colector_resultados(fechas=["2026-02-30", "2026-10-06"], exportar=False, db=sesion))
    assert resumen["peticiones"] == 1 and len(resumen["fechas_rechazadas"]) == 1 and resumen["exportacion"] is None
    assert scheduler_repo.ultimo_run(sesion, scheduler_router.JOB_COLECTOR_RESULTADOS).detalle.startswith("disparo_manual")
