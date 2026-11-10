"""test_alertas_cuota.py — alerta de créditos bajos de The Odds API: umbral y una sola vez al día."""
from __future__ import annotations

import pytest

from backend.api.services.alertas_cuota import debe_alertar_creditos


def test_alerta_con_pocos_creditos(db_session):
    assert debe_alertar_creditos(db_session, 40) is True


@pytest.mark.parametrize("restante", [100, 60, "100", None, "x"])
def test_no_alerta_con_creditos_suficientes_o_sin_dato(db_session, restante):
    assert debe_alertar_creditos(db_session, restante) is False


def test_alerta_una_sola_vez_al_dia(db_session):
    assert debe_alertar_creditos(db_session, 40) is True
    assert debe_alertar_creditos(db_session, 30) is False


def test_job_emite_la_alerta_solo_una_vez(db_session, monkeypatch):
    from backend.api import main
    from backend.api.services import alerting, odds_fetch

    emitidas = []
    monkeypatch.setattr(alerting, "emitir_alerta", lambda evento, detalle: emitidas.append((evento, detalle)) or True)
    monkeypatch.setattr(odds_fetch, "consumo_odds_hoy", lambda db: {"restante_api": "40"})
    main._alertar_creditos_odds(db_session)
    main._alertar_creditos_odds(db_session)
    assert emitidas == [("odds_creditos_bajos", {"restante": "40"})]
