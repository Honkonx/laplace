"""test_backtesting.py — `services/backtesting.py` (RPS + track record), mismo patrón de datos
sintéticos controlados que `test_calibracion.py` (permitido para tests unitarios, ver
`.claude/rules/empirical-verification-before-fix.md`)."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services import backtesting


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fila_comparativo(db, **overrides) -> AnalisisComparativo:
    base = dict(
        partido_id="p1", fecha="2026-09-09", local="A", visitante="B", liga="Test",
        pick_final="Local", creado_en=_now(),
    )
    base.update(overrides)
    fila = AnalisisComparativo(**base)
    db.add(fila)
    db.commit()
    return fila


def test_rps_sin_datos_no_explota_y_marca_no_confiable(db_session):
    reporte = backtesting._rps_promedio(db_session)
    assert reporte["muestra"] == 0
    assert reporte["rps_promedio"] is None
    assert reporte["confiable"] is False


@pytest.mark.parametrize(
    "prob_local,prob_empate,prob_visit,goles_local,goles_visitante,rps_esperado",
    [
        (1.0, 0.0, 0.0, 2, 0, 0.0),   # predicción perfecta (ganó local, 100% local) -> RPS 0
        (0.0, 0.0, 1.0, 2, 0, 1.0),   # predicción totalmente opuesta -> RPS máximo (1.0)
    ],
)
def test_rps_casos_conocidos(db_session, prob_local, prob_empate, prob_visit,
                              goles_local, goles_visitante, rps_esperado):
    for i in range(backtesting.MUESTRA_MINIMA_RPS):
        _fila_comparativo(
            db_session, partido_id=f"p{i}",
            prob_local_py=prob_local, prob_empate_py=prob_empate, prob_visit_py=prob_visit,
            goles_local=goles_local, goles_visitante=goles_visitante,
        )

    reporte = backtesting._rps_promedio(db_session)
    assert reporte["muestra"] == backtesting.MUESTRA_MINIMA_RPS
    assert reporte["confiable"] is True
    assert reporte["rps_promedio"] == pytest.approx(rps_esperado, abs=1e-4)


def test_rps_uniforme_vs_resultado_local():
    """(1/3, 1/3, 1/3) contra un resultado Local: cumP1=1/3, cumP2=2/3; cumO1=1, cumO2=1.
    RPS = 0.5*[(1/3-1)^2 + (2/3-1)^2] = 0.5*[4/9 + 1/9] = 0.5*(5/9) = 5/18 ≈ 0.2778."""
    rps = backtesting._rps_partido(1 / 3, 1 / 3, 1 / 3, 1.0, 0.0, 0.0)
    assert rps == pytest.approx(5 / 18, abs=1e-4)


def test_rps_ignora_filas_sin_resultado_o_sin_probabilidades(db_session):
    _fila_comparativo(db_session, partido_id="sin_resultado",
                       prob_local_py=0.5, prob_empate_py=0.3, prob_visit_py=0.2)
    _fila_comparativo(db_session, partido_id="sin_probabilidades",
                       goles_local=1, goles_visitante=0)

    reporte = backtesting._rps_promedio(db_session)
    assert reporte["muestra"] == 0
    assert reporte["rps_promedio"] is None


def test_calcular_track_record_estructura_completa_y_honesta_con_bd_vacia(db_session):
    reporte = backtesting.calcular_track_record(db_session)

    assert reporte["volumen_real"]["total_filas_analisis_comparativo"] == 0
    assert reporte["pick_final"]["confiable"] is False
    assert reporte["brier_score"]["muestra"] == 0
    assert reporte["rps"]["muestra"] == 0
    assert "metodologia" in reporte
    assert "advertencia_general" in reporte and reporte["advertencia_general"]


def test_calcular_track_record_con_muestra_real_moderada(db_session):
    for i in range(10):
        _fila_comparativo(
            db_session, partido_id=f"p{i}", pick_correcto=1 if i < 6 else 0,
            prob_local_py=0.6, prob_empate_py=0.25, prob_visit_py=0.15,
            goles_local=2, goles_visitante=0,
        )

    reporte = backtesting.calcular_track_record(db_session)
    assert reporte["pick_final"]["evaluados"] == 10
    assert reporte["pick_final"]["aciertos"] == 6
    assert reporte["pick_final"]["winrate_pct"] == 60.0
    assert reporte["pick_final"]["confiable"] is False  # 10 < MUESTRA_MINIMA_WINRATE (30)
    assert reporte["rps"]["muestra"] == 10
    assert reporte["rps"]["rps_promedio"] is not None
