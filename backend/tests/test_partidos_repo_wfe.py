"""test_partidos_repo_wfe.py — extensiones de partidos_repo agregadas para WF-E
(invalidar_cache_dia_anterior, leer_pendientes_ventana)."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.api.db import partidos_repo
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import AnalisisComparativo


def test_invalidar_cache_dia_anterior(db_session):
    db_session.add(PartidoDia(fecha="2026-06-01", match_id="m1", status="finished",
                               creado_en="2026-06-01 10:00:00", cache_invalidado=0))
    db_session.add(PartidoDia(fecha="2026-06-02", match_id="m2", status="finished",
                               creado_en="2026-06-02 10:00:00", cache_invalidado=0))
    db_session.commit()

    n = partidos_repo.invalidar_cache_dia_anterior(db_session, "2026-06-01")

    assert n == 1
    db_session.refresh(db_session.get(PartidoDia, ("2026-06-01", "m1")))
    assert db_session.get(PartidoDia, ("2026-06-01", "m1")).cache_invalidado == 1
    assert db_session.get(PartidoDia, ("2026-06-02", "m2")).cache_invalidado == 0


def test_guardar_ligas_cache_reactiva_partido_invalidado_tras_refetch_real(db_session):
    """Bug real corregido 2026-09-09 (confirmado empíricamente antes del fix, ver
    docstring de `guardar_ligas_cache`): una vez invalidada una fecha/partido, un re-fetch
    real de la MISMA fecha/match_id debía volver a dejarlo disponible en caché (cache_
    invalidado=0, creado_en refrescado con el timestamp del re-fetch) — antes del fix, la
    fila quedaba invalidada para siempre y esa fecha nunca más pegaba en BD."""
    partido = [{"match_id": "m1", "liga_slug": "epl", "liga_nombre": "EPL", "local": "Arsenal",
                "visitante": "Chelsea", "hora_chile": "12:00", "kick_off_utc": "2026-06-01T16:00:00"}]
    partidos_repo.guardar_ligas_cache(db_session, "2026-06-01", partido)
    creado_en_original = db_session.get(PartidoDia, ("2026-06-01", "m1")).creado_en

    n_invalidados = partidos_repo.invalidar_cache_dia_anterior(db_session, "2026-06-01")
    assert n_invalidados == 1
    assert partidos_repo.leer_ligas_cache(db_session, "2026-06-01")["hit"] is False

    partidos_repo.guardar_ligas_cache(db_session, "2026-06-01", partido)

    fila = db_session.get(PartidoDia, ("2026-06-01", "m1"))
    assert fila.cache_invalidado == 0, "el re-fetch real debe reactivar la caché de este match_id"
    assert fila.creado_en >= creado_en_original, "creado_en debe reflejar el momento del re-fetch real"
    assert partidos_repo.leer_ligas_cache(db_session, "2026-06-01")["hit"] is True


def test_leer_pendientes_ventana_incluye_partido_en_ventana(db_session):
    ahora = datetime.utcnow()
    kickoff = ahora - timedelta(minutes=150)  # dentro de [105, 240]
    db_session.add(PartidoDia(fecha="2026-06-01", match_id="f1", kick_off_utc=kickoff.isoformat(),
                               creado_en="2026-06-01 10:00:00"))
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-01", local="River", visitante="Boca", liga="L",
        creado_en="2026-06-01 10:00:00",
    ))
    db_session.commit()

    pendientes = partidos_repo.leer_pendientes_ventana(db_session, "2026-06-01")

    assert len(pendientes) == 1
    assert pendientes[0]["fixture_id"] == "f1"
    assert pendientes[0]["en_ventana"] is True


def test_leer_pendientes_ventana_excluye_fuera_de_ventana(db_session):
    ahora = datetime.utcnow()
    kickoff = ahora - timedelta(minutes=10)  # recién empezó, fuera de ventana
    db_session.add(PartidoDia(fecha="2026-06-01", match_id="f1", kick_off_utc=kickoff.isoformat(),
                               creado_en="2026-06-01 10:00:00"))
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-01", local="River", visitante="Boca", liga="L",
        creado_en="2026-06-01 10:00:00",
    ))
    db_session.commit()

    assert partidos_repo.leer_pendientes_ventana(db_session, "2026-06-01") == []


def test_leer_pendientes_ventana_sin_kickoff_se_incluye_igual(db_session):
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-01", local="River", visitante="Boca", liga="L",
        creado_en="2026-06-01 10:00:00",
    ))
    db_session.commit()

    pendientes = partidos_repo.leer_pendientes_ventana(db_session, "2026-06-01")

    assert len(pendientes) == 1
    assert pendientes[0]["en_ventana"] is None


def test_leer_pendientes_ventana_ignora_con_resultado_real(db_session):
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-01", local="River", visitante="Boca", liga="L",
        resultado_real="2-0", creado_en="2026-06-01 10:00:00",
    ))
    db_session.commit()

    assert partidos_repo.leer_pendientes_ventana(db_session, "2026-06-01") == []


# ─── leer_kick_off_utc (2026-09-09) ─────────────────────────────────────────────────────────


def test_leer_kick_off_utc_encuentra_por_match_id(db_session):
    db_session.add(PartidoDia(
        fecha="2026-09-09", liga_slug="premier", match_id="123", apifootball_fixture_id=None,
        local="A", visitante="B", kick_off_utc="2026-09-09T18:00:00Z", creado_en="2026-09-09 10:00:00",
    ))
    db_session.commit()

    assert partidos_repo.leer_kick_off_utc(db_session, "123", "2026-09-09") == "2026-09-09T18:00:00Z"


def test_leer_kick_off_utc_encuentra_por_apifootball_fixture_id(db_session):
    db_session.add(PartidoDia(
        fecha="2026-09-09", liga_slug="premier", match_id="999", apifootball_fixture_id="123",
        local="A", visitante="B", kick_off_utc="2026-09-09T18:00:00Z", creado_en="2026-09-09 10:00:00",
    ))
    db_session.commit()

    assert partidos_repo.leer_kick_off_utc(db_session, "123", "2026-09-09") == "2026-09-09T18:00:00Z"


def test_leer_kick_off_utc_sin_match_devuelve_none(db_session):
    assert partidos_repo.leer_kick_off_utc(db_session, "no-existe", "2026-09-09") is None
