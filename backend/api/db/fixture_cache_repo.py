"""db/fixture_cache_repo.py — Caché de mapeo match_id (LiveScore6/gateway) -> fixture_id de
api-football (`fixture_id_cache`), TTL 24h.

Port de `leer_fixture_cache`/`guardar_fixture_cache` de db_query.py — consumido
por `services/gateway.py` al resolver el fixture_id necesario para standings/odds/H2H.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.partidos import FixtureIdCache


def leer_fixture_cache(db: Session, match_id: str) -> dict:
    if not match_id:
        return {"hit": False}

    # Normalizado a UTC 2026-09-09 (ver jobs_repo._now_str) — `creado_en` de esta tabla se
    # escribe abajo con el mismo `utc_ahora()`, self-consistente.
    limite = (utc_ahora() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    fila = db.get(FixtureIdCache, match_id)
    if fila is None or fila.creado_en < limite:
        return {"hit": False}

    return {
        "hit": True,
        "apifootball_fixture_id": fila.apifootball_fixture_id,
        "league_id": fila.league_id,
        "season": fila.season,
        "team_home_id": fila.team_home_id,
        "team_away_id": fila.team_away_id,
    }


def guardar_fixture_cache(db: Session, match_id: str, fecha: str, apifootball_fixture_id,
                           league_id=None, season=None, team_home_id=None, team_away_id=None) -> dict:
    if not match_id or not apifootball_fixture_id:
        return {"guardado": False, "razon": "match_id y apifootball_fixture_id son requeridos"}

    ahora = utc_ahora().strftime("%Y-%m-%d %H:%M:%S")
    fila = db.get(FixtureIdCache, match_id)
    if fila is None:
        db.add(FixtureIdCache(match_id=match_id, fecha=fecha, apifootball_fixture_id=apifootball_fixture_id,
                               league_id=league_id, season=season, team_home_id=team_home_id,
                               team_away_id=team_away_id, creado_en=ahora))
    else:
        fila.apifootball_fixture_id = apifootball_fixture_id
        fila.league_id = league_id
        fila.season = season
        fila.team_home_id = team_home_id
        fila.team_away_id = team_away_id
        fila.creado_en = ahora
    db.commit()
    return {"guardado": True, "match_id": match_id, "fixture_id": apifootball_fixture_id}
