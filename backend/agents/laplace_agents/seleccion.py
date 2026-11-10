"""laplace_agents/seleccion.py — puntúa y prioriza partidos por RIQUEZA DE DATOS disponible,
no por precisión histórica.

Por qué "riqueza de datos" y no "precisión por liga" (regla dura de esta pieza, ver
`README.md` del roadmap): con el volumen real de partidos verificados todavía muy bajo
(confirmado 2026-09-10 contra `backend/db/bot_deportivo.db`: pocas decenas de filas reales con
`resultado_real IS NOT NULL` en `analisis_comparativo`), cualquier score de "qué tan buena es
esta liga prediciendo" sería ruido estadístico, no señal — mismo principio que ya se aplicó a
la calibración del motor completo (`services/calibracion.py`). Lo único que se puede puntuar
hoy de forma honesta es cuánta DATA REAL existe para analizar el partido, no si esa data
produce mejores o peores aciertos.

Dos niveles de señal, ambos ya existentes en el backend (no se reimplementan, solo se
consultan):
1. Nivel liga (`score_riqueza_liga`) — `services/ligas.py::LIGAS` ya distingue, por liga, si
   hay promedio de gol real (`avg_goles`, garantizado si `es_liga_conocida` es True — todo
   candidato que llega acá ya pasó ese filtro en `core.py::_partidos_candidatos`), tabla de
   posiciones curada (`tabla`) y odds key curada (`odds`) — más fuentes reales mapeadas para
   esa liga = más riqueza. Puro, estático, sin I/O.
2. Nivel partido (`_enriquecer_uno`/`priorizar_candidatos`) — dentro de una misma liga, dos
   partidos pueden tener distinta riqueza real: si `gateway.buscar_fixture_id` resuelve los ids
   numéricos de api-football para ESE partido específico, se habilita el fallback de
   `team_stats_fetch.py` (promedio real de temporada de cada equipo) en vez de caer directo al
   promedio genérico de liga (ver el registro de decisiones del proyecto 2026-09-09, hallazgo de uniformidad).
   Reusa `gateway.buscar_fixture_id` tal cual ya lo llama `services/analisis_completo.py::
   _enriquecer_partido` — no se reimplementa esa resolución, y como esa función ya cachea por
   `match_id` (`fixture_cache_repo`), llamarla acá primero no duplica costo real de red: cuando
   `analizar_y_persistir` la vuelva a llamar más abajo en el pipeline, encuentra el HIT.

`CAP_PARTIDOS_POR_CORRIDA` (`core.py`) casi nunca se alcanza con el volumen real de hoy
(~3-30 partidos/día en ligas conocidas) — así que en la práctica esto es sobre todo
PRIORIZACIÓN (analizar primero lo más rico en datos), no exclusión dura: si el volumen crece
algún día y el cap sí se alcanza, los partidos ya analizados son los de mejor cobertura real,
no los primeros que devolvió la cascada de fixtures."""
from __future__ import annotations

import asyncio

import httpx
from sqlalchemy.orm import Session

from backend.api.services import gateway, ligas

# Puntaje base: liga conocida siempre tiene avg_goles real (lo garantiza `es_liga_conocida`,
# ya filtrado antes de llegar acá) — +1 por cada fuente curada adicional (tabla/odds).
PUNTOS_LIGA_CONOCIDA = 1
PUNTOS_TABLA_MAPEADA = 1
PUNTOS_ODDS_MAPEADA = 1
# Señal a nivel partido (no liga): ids de api-football resueltos para ESTE partido habilitan
# el fallback de stats reales por equipo — ver docstring del módulo.
PUNTOS_IDS_RESUELTOS = 1


def score_riqueza_liga(liga: str) -> int:
    """Riqueza de datos DISPONIBLE para esta liga — NO es una medida de qué tan buenos son los
    picks de esta liga (ver docstring del módulo). 0 si la liga no está en `ligas.LIGAS`
    (`es_liga_conocida` ya la habría filtrado en `core.py`, pero esta función es pura y no
    asume ese filtro); 1-3 según cuántas fuentes curadas tiene mapeadas."""
    if not ligas.es_liga_conocida(liga):
        return 0
    tabla, odds = ligas.mapear_liga(liga)
    score = PUNTOS_LIGA_CONOCIDA
    if tabla:
        score += PUNTOS_TABLA_MAPEADA
    if odds:
        score += PUNTOS_ODDS_MAPEADA
    return score


def _ids_resueltos(fixture_info: dict) -> bool:
    return bool(
        fixture_info.get("apifootball_team_home")
        and fixture_info.get("apifootball_team_away")
        and fixture_info.get("apifootball_league_id")
        and fixture_info.get("apifootball_season")
    )


async def _enriquecer_uno(db: Session, client: httpx.AsyncClient, candidato: dict, fecha_bd: str) -> dict:
    fixture_info = await gateway.buscar_fixture_id(
        db, client, candidato["match_id"], candidato["local"], candidato["visitante"], fecha_bd,
    )
    ids_resueltos = _ids_resueltos(fixture_info)
    score = score_riqueza_liga(candidato["liga"]) + (PUNTOS_IDS_RESUELTOS if ids_resueltos else 0)
    return {**candidato, "fixture_info": fixture_info, "ids_resueltos": ids_resueltos, "score_riqueza": score}


async def priorizar_candidatos(
    db: Session, client: httpx.AsyncClient, candidatos: list[dict], fecha_bd: str,
) -> list[dict]:
    """Puntúa cada candidato (en paralelo — `gateway.buscar_fixture_id` es independiente por
    partido) y devuelve la lista ordenada de mayor a menor `score_riqueza`. Orden estable: entre
    candidatos con el mismo score, se conserva el orden real en que vinieron de la cascada de
    fixtures — no es arbitrario, solo no hay señal adicional para desempatar."""
    if not candidatos:
        return []
    enriquecidos = await asyncio.gather(*(_enriquecer_uno(db, client, c, fecha_bd) for c in candidatos))
    return sorted(enriquecidos, key=lambda c: c["score_riqueza"], reverse=True)
