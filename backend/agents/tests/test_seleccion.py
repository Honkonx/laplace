"""test_seleccion.py — score de RIQUEZA DE DATOS por liga/partido (roadmap 2026-09-10, ver
`laplace_agents/seleccion.py`). Confirma con casos reales de `services/ligas.py::LIGAS` que el
score mide cobertura de fuentes (avg_goles/tabla/odds), no precisión histórica — y que
`priorizar_candidatos` deja los partidos de mayor riqueza primero, antes de aplicar el cap."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.services import analisis_completo
from laplace_agents import seleccion


def _run(coro):
    return asyncio.run(coro)


def test_score_riqueza_liga_conocida_con_tabla_y_odds_es_maximo():
    """"laliga" tiene avg_goles + tabla (PD) + odds (soccer_spain_la_liga) mapeados en
    `ligas.LIGAS` — máxima riqueza real disponible hoy (3 puntos)."""
    assert seleccion.score_riqueza_liga("LaLiga") == 3


def test_score_riqueza_liga_conocida_sin_tabla_ni_odds_es_minimo():
    """"segunda division" está en `ligas.LIGAS` (avg_goles real) pero sin tabla ni odds
    mapeados — riqueza mínima de una liga igual conocida (1 punto, no 0: sigue siendo mejor que
    una liga totalmente desconocida)."""
    assert seleccion.score_riqueza_liga("Segunda Division") == 1


def test_score_riqueza_liga_con_solo_odds_mapeadas():
    """"serie b" tiene odds mapeadas (soccer_brazil_serie_b) pero no tabla — 2 puntos."""
    assert seleccion.score_riqueza_liga("Serie B") == 2


def test_score_riqueza_liga_desconocida_es_cero():
    assert seleccion.score_riqueza_liga("Liga Completamente Inventada FC") == 0


def test_priorizar_candidatos_ordena_por_score_riqueza_antes_del_cap(monkeypatch):
    """3 candidatos: uno de liga rica con ids de api-football resueltos (score máximo), uno de
    liga rica sin ids resueltos, uno de liga pobre — confirma que quedan en ese orden, sin
    importar el orden de llegada de la cascada de fixtures (acá llegan a propósito en el orden
    contrario al esperado)."""
    candidatos = [
        {"match_id": "1", "local": "A", "visitante": "B", "liga": "Segunda Division"},  # score 1
        {"match_id": "2", "local": "C", "visitante": "D", "liga": "LaLiga"},  # score 3 o 4 (ids)
        {"match_id": "3", "local": "E", "visitante": "F", "liga": "Serie B"},  # score 2
    ]

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        if match_id == "2":
            return {"apifootball_fixture_id": 555, "apifootball_league_id": 140,
                     "apifootball_season": 2026, "apifootball_team_home": 1, "apifootball_team_away": 2}
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await seleccion.priorizar_candidatos(None, client, candidatos, "20260601")

    priorizados = _run(_go())

    assert [c["match_id"] for c in priorizados] == ["2", "3", "1"]
    assert priorizados[0]["ids_resueltos"] is True
    assert priorizados[0]["score_riqueza"] == 4  # 3 (liga) + 1 (ids resueltos)
    assert priorizados[1]["score_riqueza"] == 2
    assert priorizados[2]["score_riqueza"] == 1


def test_priorizar_candidatos_lista_vacia_no_llama_red(monkeypatch):
    llamado = {"n": 0}

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        llamado["n"] += 1
        return {}

    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await seleccion.priorizar_candidatos(None, client, [], "20260601")

    resultado = _run(_go())
    assert resultado == []
    assert llamado["n"] == 0
