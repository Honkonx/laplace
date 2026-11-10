"""Contrato del laboratorio: sombra, corte temporal y métricas reproducibles."""
from __future__ import annotations

import pytest

from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import laboratorio_pronosticos as laboratorio


def _registrar(db_session, **extra):
    base = {
        "experimento_codigo": "python_baseline", "partido_id": "fixture-1", "fecha_partido": "2026-10-01",
        "local": "River", "visitante": "Boca", "liga": "Liga Profesional", "fuente": "laplace",
        "variante": "python_baseline", "corte_datos_en": "2026-10-01T12:00:00Z",
        "hora_kickoff": "2026-10-01T18:00:00Z", "modelo_version": "test-v1", "datos": {"forma": "congelada"},
        "pick": "Local", "prob_local": 0.55, "prob_empate": 0.25, "prob_visitante": 0.20,
        "marcador_probable": "2-1", "goles_local_esperados": 1.7, "goles_visitante_esperados": 1.0,
        "rango_goles_total": "2-4", "prob_empate_90": 0.25,
    }
    base.update(extra)
    return laboratorio.registrar_pronostico(db_session, **base)


def test_registrar_y_evaluar_comparador_prepartido(db_session):
    fila = _registrar(db_session)
    db_session.commit()
    assert fila.id
    assert db_session.query(PronosticoExperimental).count() == 1

    assert laboratorio.evaluar_partido(db_session, partido_id="fixture-1", goles_local=2, goles_visitante=1) == 1
    db_session.commit()
    db_session.refresh(fila)
    assert fila.pick_correcto == 1
    assert fila.brier_score is not None and fila.log_loss is not None and fila.rps is not None


def test_rechaza_prediccion_generada_despues_del_kickoff(db_session):
    with pytest.raises(ValueError, match="anterior al inicio"):
        _registrar(db_session, corte_datos_en="2026-10-01T19:00:00Z")


def test_reporte_mantiene_variantes_en_sombra(db_session):
    _registrar(db_session)
    db_session.commit()
    reporte = laboratorio.reporte_laboratorio(db_session)
    experimento = next(item for item in reporte["experimentos"] if item["codigo"] == "python_baseline")
    assert experimento["permite_consenso"] is False
    assert reporte["comparadores"][0]["evaluados"] == 0


def test_referencia_humana_se_guarda_en_sombra_y_se_puede_evaluar(db_session):
    fila = laboratorio.registrar_referencia_humana(
        db_session, partido_id="fixture-humano", fecha_partido="2099-10-02", local="River",
        visitante="Boca", liga="Liga Profesional", hora_kickoff="2099-10-02T18:00:00Z",
        actor_id="admin-1", alias="Amigo A", pick="local", razon="mejor forma", marcador_probable="2-0",
    )
    db_session.commit()
    assert fila.experimento_codigo == "human_reference"
    assert fila.fuente == "humano:amigoa"
    assert laboratorio.evaluar_partido(db_session, partido_id="fixture-humano", goles_local=2, goles_visitante=0) == 1
    assert fila.pick_correcto == 1


def test_referencia_api_football_no_duplica_el_mismo_partido_pendiente(db_session):
    kwargs = dict(partido_id="fixture-api", fecha_partido="2099-10-02", local="River", visitante="Boca",
                  liga="Liga Profesional", hora_kickoff="2099-10-02T18:00:00Z",
                  respuesta={"predictions": {"winner": {"name": "River"}, "percent": {"home": "55%", "draw": "25%", "away": "20%"}}})
    laboratorio.registrar_referencia_api_football(db_session, **kwargs)
    laboratorio.registrar_referencia_api_football(db_session, **kwargs)
    assert db_session.query(PronosticoExperimental).filter(PronosticoExperimental.partido_id == "fixture-api").count() == 1


def test_motor_no_duplica_la_variante_pendiente_en_un_reintento(db_session):
    kwargs = dict(partido_id="fixture-motor", fecha_partido="2099-10-02", local="River", visitante="Boca",
                  liga="Liga Profesional", hora_kickoff="2099-10-02T18:00:00Z", datos={"forma": "W"},
                  poisson={"motor": "poisson", "pick": "Local", "prob_local": 0.55, "prob_empate": 0.25,
                           "prob_visitante": 0.20, "marcador_probable": "2-1"}, combinado=None)
    laboratorio.registrar_desde_motor(db_session, **kwargs)
    laboratorio.registrar_desde_motor(db_session, **kwargs)
    assert db_session.query(PronosticoExperimental).filter(PronosticoExperimental.partido_id == "fixture-motor").count() == 1


def test_reconciliacion_evalua_observacion_si_el_resultado_ya_existe(db_session):
    from backend.api.models.partidos import ResultadoPartido
    _registrar(db_session, partido_id="fixture-reconciliar")
    db_session.add(ResultadoPartido(
        fixture_id="fixture-reconciliar", local="River", visitante="Boca", liga="Liga Profesional",
        goles_local=1, goles_visitante=0, ganador="local", status_api="FT",
        fecha_partido="2026-10-01", actualizado_en="2026-10-01 20:00:00",
    ))
    db_session.commit()
    resultado = laboratorio.reconciliar_resultados_experimentales(db_session)
    db_session.commit()
    fila = db_session.query(PronosticoExperimental).filter_by(partido_id="fixture-reconciliar").one()
    assert resultado["filas_evaluadas"] == 1
    assert fila.resultado_real == "1-0"


def test_api_football_normaliza_equipo_al_pick_canonico(db_session):
    laboratorio.registrar_referencia_api_football(
        db_session, partido_id="fixture-api-normalizado", fecha_partido="2099-10-02", local="River", visitante="Boca",
        liga="Liga Profesional", hora_kickoff="2099-10-02T18:00:00Z",
        respuesta={"predictions": {"winner": {"name": "River"}, "percent": {"home": "55%", "draw": "25%", "away": "20%"}}},
    )
    fila = db_session.query(PronosticoExperimental).filter_by(partido_id="fixture-api-normalizado").one()
    assert fila.pick == "local"


def test_sanitiza_secreto_de_error_http():
    from backend.api.services.ai_metrics import sanitizar_error
    assert "secreto" not in sanitizar_error("GET https://x.test/path?key=secreto&x=1")
    assert "[REDACTED]" in sanitizar_error("Bearer secreto")


def test_historico_se_registra_en_sombra_y_se_evalua_con_el_resultado(db_session):
    historico = {"ok": True, "pick": "Local", "metodo": "dixon_coles", "prob_local": 0.5, "prob_empate": 0.27,
                 "prob_visitante": 0.23, "lambda_local": 1.6, "lambda_visit": 1.1}
    laboratorio.registrar_historico(
        db_session, partido_id="fixture-9", fecha_partido="2026-10-01", local="Arsenal", visitante="Chelsea",
        liga="Premier League", hora_kickoff="2099-01-01T18:00:00Z", datos={"contexto": 1}, historico=historico)
    laboratorio.registrar_historico(  # módulo omitido: no debe crear un placeholder vacío
        db_session, partido_id="fixture-10", fecha_partido="2026-10-01", local="A", visitante="B",
        liga="Liga X", hora_kickoff=None, datos={}, historico={"ok": False, "razon": "fuera de cobertura"})
    db_session.commit()

    filas = db_session.query(PronosticoExperimental).all()
    assert [f.experimento_codigo for f in filas] == ["dixon_coles_historico"]
    assert laboratorio.evaluar_partido(db_session, partido_id="fixture-9", goles_local=2, goles_visitante=0) == 1
    db_session.commit()
    db_session.refresh(filas[0])
    assert filas[0].pick_correcto == 1 and filas[0].rps is not None


def _registrar_hist(db, historico, partido="fx-h", datos=None):
    laboratorio.registrar_historico(
        db, partido_id=partido, fecha_partido="2026-10-06", local="Arsenal", visitante="Chelsea",
        liga="Premier League", hora_kickoff="2099-01-01T18:00:00Z", datos=datos or {}, historico=historico)
    db.commit()
    return {f.variante: f for f in db.query(PronosticoExperimental).filter(PronosticoExperimental.partido_id == partido)}


def test_historico_solo_dc_registra_unicamente_la_variante_pura(db_session):
    historico = {"ok": True, "pick": "Local", "metodo": "dixon_coles", "prob_local": 0.5, "prob_empate": 0.27,
                 "prob_visitante": 0.23, "lambda_local": 1.6, "lambda_visit": 1.1}
    filas = _registrar_hist(db_session, historico)
    assert set(filas) == {"dixon_coles_historico"}
    assert filas["dixon_coles_historico"].prob_local == 0.5


def test_historico_apilado_separa_dc_puro_y_dc_mas_mercado(db_session):
    """Con cuotas el módulo devuelve las probabilidades apiladas; el DC puro se reconstruye desde
    los λ y se guarda aparte para medir qué aporta el mercado."""
    historico = {"ok": True, "pick": "Local", "metodo": "dc_mas_mercado", "prob_local": 0.60, "prob_empate": 0.24,
                 "prob_visitante": 0.16, "lambda_local": 1.5, "lambda_visit": 1.2}
    filas = _registrar_hist(db_session, historico)
    assert set(filas) == {"dixon_coles_historico", "dc_mas_mercado_historico"}
    apilada, pura = filas["dc_mas_mercado_historico"], filas["dixon_coles_historico"]
    assert apilada.prob_local == 0.60 and apilada.experimento_codigo == "dc_mas_mercado_historico"
    # el DC puro NO es la mezcla con el mercado: viene de los λ del modelo
    assert pura.prob_local != apilada.prob_local
    assert abs(pura.prob_local + pura.prob_empate + pura.prob_visitante - 1.0) < 0.02
    assert pura.pick in {"Local", "Empate", "Visitante"}


def test_historico_es_idempotente_mientras_la_observacion_esta_pendiente(db_session):
    historico = {"ok": True, "pick": "Local", "metodo": "dc_mas_mercado", "prob_local": 0.60, "prob_empate": 0.24,
                 "prob_visitante": 0.16, "lambda_local": 1.5, "lambda_visit": 1.2}
    _registrar_hist(db_session, historico)
    filas = _registrar_hist(db_session, historico)
    assert len(filas) == 2
    assert db_session.query(PronosticoExperimental).count() == 2


def test_comparadores_del_motor_registra_poisson_bsd_e_historico(db_session):
    """El punto único (usado por análisis individual, exploratorio y Top Picks) congela todo."""
    modulos = {
        "poisson": {"ok": True, "pick": "Local", "prob_local": 0.5, "prob_empate": 0.28, "prob_visitante": 0.22,
                    "lambda_local": 1.5, "lambda_visit": 1.1, "motor": "math"},
        "bsd_ml": {"ok": True, "pick": "Local", "prob_local": 0.55, "prob_empate": 0.25, "prob_visitante": 0.2},
        "historico": {"ok": True, "pick": "Local", "metodo": "dixon_coles", "prob_local": 0.5, "prob_empate": 0.27,
                      "prob_visitante": 0.23, "lambda_local": 1.6, "lambda_visit": 1.1},
    }
    kwargs = dict(partido_id="fx-all", fecha_partido="2026-10-06", local="A", visitante="B", liga="L",
                  hora_kickoff="2099-01-01T18:00:00Z", datos={}, modulos=modulos)
    laboratorio.registrar_comparadores_del_motor(db_session, **kwargs)
    laboratorio.registrar_comparadores_del_motor(db_session, **kwargs, combinado=None)  # reintento
    db_session.commit()
    variantes = sorted(f.variante for f in db_session.query(PronosticoExperimental).all())
    assert variantes == ["bsd_catboost", "dixon_coles_historico", "python_baseline"]


def test_experimentos_base_incluyen_dc_mas_mercado_historico(db_session):
    laboratorio.asegurar_experimentos_base(db_session)
    codigos = {e.codigo for e in db_session.query(laboratorio.ExperimentoPronostico).all()}
    assert {"dixon_coles_historico", "dc_mas_mercado_historico"} <= codigos
