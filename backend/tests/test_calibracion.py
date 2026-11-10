"""test_calibracion.py — cálculo de métricas de winrate/calibración (`services/calibracion.py`),
con datos SINTÉTICOS de prueba controlados (permitido para tests unitarios, ver
`.claude/rules/empirical-verification-before-fix.md` — la regla de "no inventar datos" es sobre
el reporte real contra la BD real en `laplace_auditor.py`/`GET /admin/calibracion`, no sobre
tests).

Cubre: BD vacía (0 filas — no debe explotar por división por cero), umbral de muestra mínima
(confiable/no confiable), fallback de `analisis_modulos` vacía a las columnas anchas de
`analisis_comparativo`, preferencia por `analisis_modulos` cuando sí tiene filas, y el Brier
score multiclase con casos conocidos (predicción perfecta -> 0, predicción totalmente opuesta
-> 2)."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.api.models.predicciones import AnalisisComparativo, AnalisisModulo
from backend.api.services import calibracion


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


def test_bd_vacia_no_explota_y_marca_no_confiable(db_session):
    reporte = calibracion.calcular_metricas_calibracion(db_session)

    assert reporte["volumen_real"]["total_filas_analisis_comparativo"] == 0
    assert reporte["pick_final"]["evaluados"] == 0
    assert reporte["pick_final"]["winrate_pct"] is None
    assert reporte["pick_final"]["confiable"] is False
    assert reporte["brier_score_poisson"]["muestra"] == 0
    assert reporte["brier_score_poisson"]["brier_score"] is None


def test_winrate_pick_final_con_muestra_insuficiente(db_session):
    for i in range(5):
        _fila_comparativo(db_session, partido_id=f"p{i}", pick_correcto=1 if i < 3 else 0)

    reporte = calibracion.calcular_metricas_calibracion(db_session)
    bloque = reporte["pick_final"]
    assert bloque["evaluados"] == 5
    assert bloque["aciertos"] == 3
    assert bloque["winrate_pct"] == 60.0
    assert bloque["confiable"] is False  # 5 < MUESTRA_MINIMA_WINRATE (30)
    assert "insuficiente" in bloque["nota"].lower()


def test_winrate_pick_final_confiable_al_alcanzar_el_umbral(db_session):
    for i in range(calibracion.MUESTRA_MINIMA_WINRATE):
        _fila_comparativo(db_session, partido_id=f"p{i}", pick_correcto=1 if i % 2 == 0 else 0)

    reporte = calibracion.calcular_metricas_calibracion(db_session)
    bloque = reporte["pick_final"]
    assert bloque["evaluados"] == calibracion.MUESTRA_MINIMA_WINRATE
    assert bloque["confiable"] is True


def test_fallback_a_columnas_anchas_cuando_analisis_modulos_esta_vacia(db_session):
    _fila_comparativo(
        db_session, partido_id="p1", pick_python="Local", pick_python_correcto=1,
        pick_form="Empate", pick_form_correcto=0,
    )
    reporte = calibracion.calcular_metricas_calibracion(db_session)

    assert reporte["fuente_por_modulo"].startswith("analisis_comparativo")
    assert reporte["por_modulo"]["poisson"]["evaluados"] == 1
    assert reporte["por_modulo"]["poisson"]["aciertos"] == 1
    assert reporte["por_modulo"]["forma"]["evaluados"] == 1
    assert reporte["por_modulo"]["forma"]["aciertos"] == 0
    # h2h/odds/tabla/externo no tienen datos en esta fila -> 0 evaluados, no explota
    assert reporte["por_modulo"]["h2h"]["evaluados"] == 0


def test_usa_analisis_modulos_cuando_tiene_filas_reales(db_session):
    for i, correcto in enumerate([1, 1, 0]):
        db_session.add(AnalisisModulo(
            partido_id=f"p{i}", modulo="poisson", pick="Local", pick_correcto=correcto,
            creado_en=_now(),
        ))
    db_session.commit()

    reporte = calibracion.calcular_metricas_calibracion(db_session)
    assert reporte["fuente_por_modulo"] == "analisis_modulos"
    assert reporte["por_modulo"]["poisson"]["evaluados"] == 3
    assert reporte["por_modulo"]["poisson"]["aciertos"] == 2


@pytest.mark.parametrize(
    "prob_local,prob_empate,prob_visit,goles_local,goles_visitante,brier_esperado",
    [
        (1.0, 0.0, 0.0, 2, 0, 0.0),   # predicción perfecta (local, ganó local) -> 0
        (0.0, 0.0, 1.0, 2, 0, 2.0),   # predicción totalmente opuesta -> máximo error (2.0)
        (1 / 3, 1 / 3, 1 / 3, 2, 0, None),  # calculado abajo (uniforme vs local)
    ],
)
def test_brier_score_casos_conocidos(db_session, prob_local, prob_empate, prob_visit,
                                       goles_local, goles_visitante, brier_esperado):
    for i in range(calibracion.MUESTRA_MINIMA_BRIER):
        _fila_comparativo(
            db_session, partido_id=f"p{i}",
            prob_local_py=prob_local, prob_empate_py=prob_empate, prob_visit_py=prob_visit,
            goles_local=goles_local, goles_visitante=goles_visitante,
        )

    reporte = calibracion.calcular_metricas_calibracion(db_session)
    bloque = reporte["brier_score_poisson"]
    assert bloque["muestra"] == calibracion.MUESTRA_MINIMA_BRIER
    assert bloque["confiable"] is True
    if brier_esperado is not None:
        assert bloque["brier_score"] == pytest.approx(brier_esperado, abs=1e-4)
    else:
        # (1/3-1)^2 + (1/3-0)^2 + (1/3-0)^2 = 4/9 + 1/9 + 1/9 = 6/9 ≈ 0.6667
        assert bloque["brier_score"] == pytest.approx(2 / 3, abs=1e-4)


def test_brier_score_ignora_filas_sin_resultado_o_sin_probabilidades(db_session):
    _fila_comparativo(db_session, partido_id="sin_resultado",
                       prob_local_py=0.5, prob_empate_py=0.3, prob_visit_py=0.2)
    _fila_comparativo(db_session, partido_id="sin_probabilidades",
                       goles_local=1, goles_visitante=0)

    reporte = calibracion.calcular_metricas_calibracion(db_session)
    assert reporte["brier_score_poisson"]["muestra"] == 0
    assert reporte["brier_score_poisson"]["brier_score"] is None


def test_veredicto_honesto_siempre_presente(db_session):
    reporte = calibracion.calcular_metricas_calibracion(db_session)
    assert "advertencia_general" in reporte
    assert reporte["advertencia_general"]


def test_filas_del_motor_previo_al_corte_no_entran_en_las_metricas(db_session):
    """Regresión 2026-09-29: lo analizado antes del corte (motor que devolvía la misma tripleta
    para partidos distintos) se conserva en la BD pero no cuenta en winrate, Brier ni RPS."""
    from backend.api.services import backtesting

    _fila_comparativo(
        db_session, partido_id="viejo", creado_en="2026-09-20 10:00:00", pick_correcto=1,
        goles_local=1, goles_visitante=1, prob_local_py=0.2, prob_empate_py=0.6, prob_visit_py=0.2,
    )
    _fila_comparativo(db_session, partido_id="nuevo", pick_correcto=0)

    reporte = calibracion.calcular_metricas_calibracion(db_session)

    assert reporte["volumen_real"]["total_filas_analisis_comparativo"] == 2
    assert reporte["volumen_real"]["filas_validas_para_calibracion"] == 1
    assert reporte["volumen_real"]["filas_excluidas_por_motor_previo"] == 1
    assert reporte["pick_final"]["evaluados"] == 1
    assert reporte["pick_final"]["aciertos"] == 0
    assert reporte["brier_score_poisson"]["muestra"] == 0
    assert backtesting.calcular_track_record(db_session)["rps"]["muestra"] == 0


def test_corte_del_motor_esta_en_2026_10_19_y_excluye_los_motores_anteriores(db_session):
    """El motor cambió el 29-sep (pesos, historico), el 5-oct (topes, SOLO_<modulo>), el 6-oct (lambdas
    Poisson), el 7-oct (pesos orientados al mercado, confianza calibrada) y el 19-oct (un ancla basta para publicar,
    equipo sin historial, etiquetas por ancla): nada anterior al 2026-10-19 mide el motor vigente."""
    assert calibracion.CORTE_MOTOR_CON_PUERTA_CALIDAD == "2026-10-19"
    _fila_comparativo(db_session, partido_id="sep29", creado_en="2026-09-29 10:00:00", pick_correcto=1)
    _fila_comparativo(db_session, partido_id="oct05", creado_en="2026-10-05 23:59:59", pick_correcto=1)
    _fila_comparativo(db_session, partido_id="oct06", creado_en="2026-10-06 23:59:59", pick_correcto=1)
    _fila_comparativo(db_session, partido_id="oct18", creado_en="2026-10-18 23:59:59", pick_correcto=1)
    _fila_comparativo(db_session, partido_id="oct19", creado_en="2026-10-19 00:00:00", pick_correcto=0)
    reporte = calibracion.calcular_metricas_calibracion(db_session)
    assert reporte["volumen_real"]["filas_validas_para_calibracion"] == 1
    assert reporte["pick_final"]["evaluados"] == 1


def test_historico_y_bsd_ml_se_miden_desde_analisis_modulo(db_session):
    for i, (modulo, correcto) in enumerate([("historico", 1), ("historico", 0), ("bsd_ml", 1)]):
        db_session.add(AnalisisModulo(
            partido_id=f"m{i}", modulo=modulo, pick="Local", pick_correcto=correcto,
            creado_en="2026-10-19 12:00:00",
        ))
    db_session.commit()
    reporte = calibracion.calcular_metricas_calibracion(db_session)
    assert reporte["fuente_por_modulo"] == "analisis_modulos"
    assert reporte["por_modulo"]["historico"]["evaluados"] == 2
    assert reporte["por_modulo"]["historico"]["aciertos"] == 1
    assert reporte["por_modulo"]["bsd_ml"]["evaluados"] == 1


def test_fallback_de_columnas_anchas_declara_historico_y_bsd_sin_medir(db_session):
    reporte = calibracion.calcular_metricas_calibracion(db_session)
    for modulo in ("historico", "bsd_ml"):
        assert reporte["por_modulo"][modulo]["evaluados"] == 0
        assert reporte["por_modulo"][modulo]["confiable"] is False


def test_analisis_creado_despues_del_inicio_del_partido_no_cuenta(db_session):
    """Un pronóstico hecho después del pitazo no es una predicción (fuga): se excluye cuando se conoce la hora."""
    ahora = _now()
    _fila_comparativo(db_session, partido_id="antes", hora_kickoff="2999-01-01T20:00:00Z", pick_correcto=1)
    _fila_comparativo(db_session, partido_id="despues", hora_kickoff="2000-01-01T20:00:00+00:00",
                       creado_en=ahora, pick_correcto=1)
    _fila_comparativo(db_session, partido_id="desconocido", pick_correcto=0)

    reporte = calibracion.calcular_metricas_calibracion(db_session)

    assert reporte["volumen_real"]["filas_validas_para_calibracion"] == 2  # antes + desconocido
    assert reporte["pick_final"]["evaluados"] == 2 and reporte["pick_final"]["aciertos"] == 1
