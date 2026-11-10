"""Backfill de resultados desde `partidos_dia` hacia `resultados_partidos` sin fuga del futuro."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.models.predicciones import AnalisisComparativo, PronosticoExperimental

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_resultados_laboratorio.py"


def _modulo():
    spec = importlib.util.spec_from_file_location("backfill_resultados_laboratorio", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _partido(db, fecha, match_id, status="FT", gl=2, gv=1, kick="2026-10-01T20:00:00", hora="17:00"):
    db.add(PartidoDia(fecha=fecha, match_id=match_id, liga_nombre="Liga X", local=f"L{match_id}", visitante=f"V{match_id}",
                      status=status, goles_local=gl, goles_visitante=gv, hora_chile=hora, kick_off_utc=kick,
                      creado_en="2026-10-01 10:00:00", cache_invalidado=0))


def _comparativo(db, match_id, creado_en):
    db.add(AnalisisComparativo(partido_id=match_id, fecha="2026-10-01", local=f"L{match_id}", visitante=f"V{match_id}",
                               liga="Liga X", pick_final="Local", creado_en=creado_en))


def test_planificar_solo_cuenta_terminados_validos_y_no_escribe(db_session):
    mod = _modulo()
    _partido(db_session, "2026-10-01", "1")
    _partido(db_session, "2026-10-01", "2", status="scheduled", gl=None, gv=None)
    _partido(db_session, "2026-10-01", "3", status="AWD")
    _partido(db_session, "2026--1-0-", "4")  # fecha basura: se excluye
    _partido(db_session, "2026-10-01", "5", gl=None, gv=None)  # terminado sin marcador
    db_session.add(ResultadoPartido(fixture_id="9", goles_local=0, goles_visitante=0, actualizado_en="x"))
    _partido(db_session, "2026-10-01", "9")  # ya está en el ledger
    db_session.commit()

    plan = mod.planificar(db_session)

    assert plan["filas_que_anadiria_a_resultados_partidos"] == 1
    assert plan["ya_en_resultados_partidos"] == 1
    assert plan["excluidos"]["fecha_invalida"] == 1 and plan["excluidos"]["sin_marcador"] == 1
    assert db_session.query(ResultadoPartido).count() == 1  # dry-run: nada nuevo


def test_aplicar_califica_analisis_previo_al_kickoff_y_excluye_el_posterior(db_session):
    mod = _modulo()
    _partido(db_session, "2026-10-01", "1")  # kickoff 2026-10-01T20:00Z
    _partido(db_session, "2026-10-01", "2")
    _comparativo(db_session, "1", "2026-10-01 12:00:00")   # antes del partido: se califica
    _comparativo(db_session, "2", "2026-10-01 21:30:00")   # después del inicio: fuga, no se califica
    db_session.add(PronosticoExperimental(
        experimento_codigo="e", partido_id="1", fecha_partido="2026-10-01", local="L1", visitante="V1",
        fuente="x", variante="v", corte_datos_en="2026-10-01T12:00:00Z", input_hash="h", datos_json="{}",
        pick="local", prob_local=0.5, prob_empate=0.3, prob_visitante=0.2, creado_en="2026-10-01T12:00:00Z"))
    db_session.commit()

    plan = mod.planificar(db_session)
    assert plan["comparativos_que_calificaria"] == 1
    assert plan["comparativos_sin_calificar_por_fuga_o_kickoff_desconocido"] == 1
    assert plan["partidos_con_analisis_contaminado"] == 1

    resultado = mod.aplicar(db_session, plan)

    assert resultado["copiados_a_resultados_partidos"] == 2
    assert db_session.query(ResultadoPartido).count() == 2
    limpio = db_session.query(AnalisisComparativo).filter_by(partido_id="1").one()
    sucio = db_session.query(AnalisisComparativo).filter_by(partido_id="2").one()
    assert limpio.resultado_real == "2-1" and limpio.pick_correcto == 1
    assert sucio.resultado_real is None  # excluido de las métricas
    assert db_session.query(PronosticoExperimental).one().resultado_real == "2-1"


def test_aplicar_es_idempotente_y_no_borra(db_session):
    mod = _modulo()
    _partido(db_session, "2026-10-01", "1")
    db_session.commit()
    mod.aplicar(db_session, mod.planificar(db_session))
    plan2 = mod.planificar(db_session)
    assert plan2["filas_que_anadiria_a_resultados_partidos"] == 0
    mod.aplicar(db_session, plan2)
    assert db_session.query(ResultadoPartido).count() == 1
    assert db_session.query(PartidoDia).count() == 1


def test_kickoff_estimado_con_hora_chile_cuando_falta_kick_off_utc(db_session):
    mod = _modulo()
    _partido(db_session, "2026-10-01", "1", kick="", hora="17:00")  # 17:00 Chile (UTC-3 en octubre) = 20:00Z
    _comparativo(db_session, "1", "2026-10-01 19:00:00")
    db_session.commit()
    assert mod.planificar(db_session)["comparativos_que_calificaria"] == 1
    _comparativo(db_session, "1", "2026-10-01 20:30:00")
    db_session.commit()
    assert mod.planificar(db_session)["comparativos_sin_calificar_por_fuga_o_kickoff_desconocido"] == 1


def test_main_aplicar_sin_confirmo_aborta(tmp_path, capsys):
    mod = _modulo()
    ruta = tmp_path / "x.db"
    sqlite3.connect(ruta).close()
    assert mod.main(["--db", str(ruta), "--aplicar"]) == 2
    assert "ABORTADO" in capsys.readouterr().err
