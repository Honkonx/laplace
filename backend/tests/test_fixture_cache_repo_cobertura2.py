"""Pruebas de `db/fixture_cache_repo.py` contra SQLite en memoria: guardar, leer, TTL de 24 h, actualizar y ausencias."""
from __future__ import annotations

from datetime import timedelta

from backend.api.core.tiempo import utc_ahora
from backend.api.db import fixture_cache_repo as repo
from backend.api.models.partidos import FixtureIdCache


def _formato(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def test_leer_sin_match_id_es_miss(db_session):
    assert repo.leer_fixture_cache(db_session, "") == {"hit": False}
    assert repo.leer_fixture_cache(db_session, None) == {"hit": False}


def test_leer_ausente_es_miss(db_session):
    assert repo.leer_fixture_cache(db_session, "no-existe") == {"hit": False}


def test_guardar_requiere_match_id_y_fixture(db_session):
    r1 = repo.guardar_fixture_cache(db_session, "", "2026-11-10", "123")
    r2 = repo.guardar_fixture_cache(db_session, "m1", "2026-11-10", None)
    r3 = repo.guardar_fixture_cache(db_session, "m1", "2026-11-10", "")
    for r in (r1, r2, r3):
        assert r["guardado"] is False
        assert "requeridos" in r["razon"]
    assert db_session.query(FixtureIdCache).count() == 0


def test_guardar_y_leer_ida_y_vuelta(db_session):
    res = repo.guardar_fixture_cache(db_session, "m1", "2026-11-10", "987", league_id=39, season=2026,
                                     team_home_id=10, team_away_id=20)
    assert res == {"guardado": True, "match_id": "m1", "fixture_id": "987"}

    fila = db_session.get(FixtureIdCache, "m1")
    assert fila.fecha == "2026-11-10"
    assert fila.creado_en <= _formato(utc_ahora())

    assert repo.leer_fixture_cache(db_session, "m1") == {
        "hit": True, "apifootball_fixture_id": "987", "league_id": 39, "season": 2026,
        "team_home_id": 10, "team_away_id": 20,
    }


def test_guardar_con_opcionales_nulos(db_session):
    repo.guardar_fixture_cache(db_session, "m2", "2026-11-10", "55")
    leido = repo.leer_fixture_cache(db_session, "m2")
    assert leido["hit"] is True
    assert leido["apifootball_fixture_id"] == "55"
    assert leido["league_id"] is None and leido["season"] is None
    assert leido["team_home_id"] is None and leido["team_away_id"] is None


def test_guardar_existente_actualiza_sin_duplicar_y_renueva_ttl(db_session):
    repo.guardar_fixture_cache(db_session, "m3", "2026-11-10", "1", league_id=1, season=2025,
                               team_home_id=1, team_away_id=2)
    fila = db_session.get(FixtureIdCache, "m3")
    fila.creado_en = _formato(utc_ahora() - timedelta(hours=30))
    db_session.commit()
    assert repo.leer_fixture_cache(db_session, "m3") == {"hit": False}

    repo.guardar_fixture_cache(db_session, "m3", "2026-11-10", "2", league_id=2, season=2026,
                               team_home_id=3, team_away_id=4)
    assert db_session.query(FixtureIdCache).count() == 1
    assert repo.leer_fixture_cache(db_session, "m3") == {
        "hit": True, "apifootball_fixture_id": "2", "league_id": 2, "season": 2026,
        "team_home_id": 3, "team_away_id": 4,
    }


def test_actualizar_sin_opcionales_los_deja_nulos(db_session):
    repo.guardar_fixture_cache(db_session, "m4", "2026-11-10", "1", league_id=9, season=2026,
                               team_home_id=1, team_away_id=2)
    repo.guardar_fixture_cache(db_session, "m4", "2026-11-10", "7")
    leido = repo.leer_fixture_cache(db_session, "m4")
    assert leido["apifootball_fixture_id"] == "7"
    assert leido["league_id"] is None and leido["team_home_id"] is None


def test_expira_pasadas_24_horas(db_session):
    repo.guardar_fixture_cache(db_session, "viejo", "2026-11-09", "1")
    repo.guardar_fixture_cache(db_session, "reciente", "2026-11-10", "2")
    db_session.get(FixtureIdCache, "viejo").creado_en = _formato(utc_ahora() - timedelta(hours=25))
    db_session.get(FixtureIdCache, "reciente").creado_en = _formato(utc_ahora() - timedelta(hours=23))
    db_session.commit()

    assert repo.leer_fixture_cache(db_session, "viejo") == {"hit": False}
    assert repo.leer_fixture_cache(db_session, "reciente")["hit"] is True
    # La fila expirada no se borra: solo deja de contar como acierto.
    assert db_session.get(FixtureIdCache, "viejo") is not None


def test_reprogramar_un_partido_actualiza_su_fecha(db_session):
    from backend.api.db import fixture_cache_repo as repo
    from backend.api.models.partidos import FixtureIdCache

    repo.guardar_fixture_cache(db_session, "m1", "2026-11-10", 111)
    repo.guardar_fixture_cache(db_session, "m1", "2026-11-12", 111)
    assert db_session.get(FixtureIdCache, "m1").fecha == "2026-11-12"
