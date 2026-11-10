"""test_consistencia.py — detector de uniformidad de picks + trazabilidad de `fuente_goles`
(roadmap 2026-09-10, ver `laplace_agents/consistencia.py`). El caso real que motiva esto:
2026-09-10 se confirmó A MANO que el motor daba 92.6% "Empate" en un día real, con
probabilidades idénticas byte a byte entre partidos de ligas distintas — este módulo automatiza
ese chequeo."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.services import analisis_completo
from laplace_agents import consistencia


def _run(coro):
    return asyncio.run(coro)


def _detalle_analizado(pick_final: str, fuente_goles: str = "liga_generico", match_id: str = "1") -> dict:
    return {"match_id": match_id, "liga": "Liga X", "estado": "analizado",
            "pick_final": pick_final, "fuente_goles": fuente_goles}


def test_detectar_uniformidad_dispara_alerta_con_batch_sospechoso():
    """Batch real simulado: 8 partidos, 7 con el mismo pick "Empate" (87.5%) — exactamente el
    tipo de caso que motivó esta pieza (92.6% "Empate" el 2026-09-09)."""
    detalle = [_detalle_analizado("Empate", match_id=str(i)) for i in range(7)]
    detalle.append(_detalle_analizado("Local", match_id="8"))

    resultado = consistencia.detectar_uniformidad(detalle)

    assert resultado["total_analizados_con_pick"] == 8
    assert resultado["distribucion_picks"] == {"Empate": 7, "Local": 1}
    assert resultado["alerta_uniformidad"] is True
    assert resultado["pick_dominante_si_hay_alerta"] == "Empate"


def test_detectar_uniformidad_no_dispara_con_distribucion_pareja():
    detalle = (
        [_detalle_analizado("Local", match_id=f"L{i}") for i in range(3)]
        + [_detalle_analizado("Empate", match_id=f"E{i}") for i in range(3)]
        + [_detalle_analizado("Visitante", match_id=f"V{i}") for i in range(3)]
    )

    resultado = consistencia.detectar_uniformidad(detalle)

    assert resultado["total_analizados_con_pick"] == 9
    assert resultado["alerta_uniformidad"] is False
    assert resultado["pick_dominante_si_hay_alerta"] is None


def test_detectar_uniformidad_no_dispara_con_muestra_chica_aunque_sea_100_por_ciento_igual():
    """3 partidos, los 3 "Empate" (100%) — pero por debajo de `MUESTRA_MINIMA_PARA_ALERTA` (5),
    no hay muestra suficiente para que la alerta signifique algo real. Regla explícita del
    roadmap: no disparar falsos positivos con muestras chicas."""
    detalle = [_detalle_analizado("Empate", match_id=str(i)) for i in range(3)]

    resultado = consistencia.detectar_uniformidad(detalle)

    assert resultado["total_analizados_con_pick"] == 3
    assert resultado["alerta_uniformidad"] is False


def test_detectar_uniformidad_ignora_partidos_con_error_o_sin_pick():
    detalle = [
        {"match_id": "1", "liga": "X", "estado": "error", "fuente_goles": "desconocido"},
        {"match_id": "2", "liga": "X", "estado": "analizado", "pick_final": None, "fuente_goles": "h2h_real"},
        _detalle_analizado("Local", match_id="3"),
    ]

    resultado = consistencia.detectar_uniformidad(detalle)

    assert resultado["total_analizados_con_pick"] == 1
    assert resultado["distribucion_picks"] == {"Local": 1}


def test_detectar_uniformidad_reporta_distribucion_de_fuente_goles():
    detalle = [
        _detalle_analizado("Local", fuente_goles="h2h_real", match_id="1"),
        _detalle_analizado("Local", fuente_goles="stats_equipo_real", match_id="2"),
        _detalle_analizado("Empate", fuente_goles="liga_generico", match_id="3"),
        _detalle_analizado("Empate", fuente_goles="liga_generico", match_id="4"),
    ]

    resultado = consistencia.detectar_uniformidad(detalle)

    assert resultado["distribucion_fuente_goles"] == {
        "h2h_real": 1, "stats_equipo_real": 1, "liga_generico": 2,
    }


def test_obtener_fuente_goles_lee_el_campo_real_de_h2h_fetch(monkeypatch):
    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6,
                    league_id=None, season=None):
        return {"fuente_goles": "stats_equipo_real", "goles_local_avg": 1.5, "goles_visit_avg": 1.1,
                "goles_contra_local_avg": 1.1, "goles_contra_visit_avg": 1.5,
                "h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0,
                "h2h_total": 0, "h2h_resumen": ""}

    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)

    candidato = {
        "match_id": "1", "local": "River Plate", "visitante": "Boca Juniors", "liga": "Liga Profesional",
        "fixture_info": {"apifootball_league_id": 128, "apifootball_season": 2026,
                          "apifootball_team_home": 1, "apifootball_team_away": 2},
    }

    async def _go():
        async with httpx.AsyncClient() as client:
            return await consistencia.obtener_fuente_goles(None, client, candidato)

    assert _run(_go()) == "stats_equipo_real"


def test_obtener_fuente_goles_nunca_lanza_devuelve_desconocido_si_h2h_fetch_falla(monkeypatch):
    async def _h2h_que_falla(*args, **kwargs):
        raise RuntimeError("fallo de red simulado")

    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h_que_falla)

    candidato = {"match_id": "1", "local": "A", "visitante": "B", "liga": "Liga X", "fixture_info": {}}

    async def _go():
        async with httpx.AsyncClient() as client:
            return await consistencia.obtener_fuente_goles(None, client, candidato)

    assert _run(_go()) == "desconocido"
