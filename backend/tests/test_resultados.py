"""test_resultados.py — verifica _pick_acerto y el guardado real del resultado (recalcula
pick_correcto/over25_correcto/btts_correcto en analisis_comparativo, idéntico a
actualizar_resultados.py:guardar_resultado_db)."""
from __future__ import annotations

from datetime import datetime

from backend.api.models.predicciones import AnalisisComparativo, AnalisisModulo
from backend.api.services import laboratorio_pronosticos
from backend.api.services import resultados


def test_pick_acerto_local():
    assert resultados._pick_acerto("Local", "local", "River", "Boca") is True
    assert resultados._pick_acerto("Visitante", "local", "River", "Boca") is False


def test_pick_acerto_empate_variantes():
    assert resultados._pick_acerto("empate", "empate", "River", "Boca") is True
    assert resultados._pick_acerto("draw", "empate", "River", "Boca") is True
    assert resultados._pick_acerto("x", "empate", "River", "Boca") is True


def test_guardar_resultado_actualiza_analisis_comparativo(db_session):
    fila = AnalisisComparativo(
        partido_id="fx1", fecha="2026-06-01", local="River", visitante="Boca",
        liga="Liga Profesional", pick_final="Local", pick_python="Local", pick_form="Visitante",
        over25_pred=0.65, btts_pred=0.30,
        creado_en=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db_session.add(fila)
    modulo = AnalisisModulo(partido_id="fx1", modulo="poisson", pick="Local", creado_en=datetime.now().isoformat())
    db_session.add(modulo)
    db_session.commit()

    resultado = resultados._guardar_resultado(
        db_session, "fx1", "River", "Boca", "Liga Profesional",
        goles_local=2, goles_visitante=0, status_api="FT", fecha_partido="2026-06-01",
    )

    assert resultado["ganador"] == "local"
    assert resultado["over25_real"] == 0  # 2 goles totales, no > 2
    assert resultado["btts_real"] == 0    # Boca no anotó

    db_session.refresh(fila)
    assert fila.resultado_real == "2-0"
    assert fila.pick_correcto == 1        # pick_final="Local", ganó Local
    assert fila.pick_python_correcto == 1  # pick_python="Local"
    assert fila.pick_form_correcto == 0    # pick_form="Visitante", perdió
    # over25_pred=0.65 >= 0.55 predecía Over -> real fue Under (0) -> incorrecto
    assert fila.over25_correcto == 0
    # btts_pred=0.30 <= 0.45 predecía No BTTS -> real fue No BTTS (0) -> correcto
    assert fila.btts_correcto == 1
    db_session.refresh(modulo)
    assert modulo.pick_correcto == 1


def test_guardar_resultado_califica_laboratorio(db_session):
    laboratorio_pronosticos.registrar_pronostico(
        db_session, experimento_codigo="python_baseline", partido_id="fx-lab", fecha_partido="2026-06-01",
        local="River", visitante="Boca", fuente="laplace", variante="python_baseline",
        corte_datos_en="2026-06-01T10:00:00Z", hora_kickoff="2026-06-01T18:00:00Z",
        prob_local=0.6, prob_empate=0.2, prob_visitante=0.2, pick="Local",
    )
    db_session.commit()
    resultado = resultados._guardar_resultado(
        db_session, "fx-lab", "River", "Boca", "Liga", 1, 0, "FT", "2026-06-01",
    )
    assert resultado["experimentales"] == 1
