"""test_normalizacion_simulador.py — `services/normalizacion.py` (nombres de equipos) y el orquestador y los
helpers de red de `services/simulador_liga.py` (api-football sustituida, sin red ni claves)."""
from __future__ import annotations

import asyncio

import pytest

from backend.api.services import normalizacion as nz
from backend.api.services import simulador_liga as sim


def _correr(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ normalizacion
@pytest.mark.parametrize("entrada,esperado", [
    (None, ""), ("", ""), ("  Atlético   Madrid ", "atletico madrid"), ("São Paulo F.C.", "sao paulo fc"),
    ("Bayern München", "bayern munchen"), ("Ñublense", "nublense"), (1234, "1234"),
])
def test_normalizar_nombre(entrada, esperado):
    assert nz.normalizar_nombre(entrada) == esperado


@pytest.mark.parametrize("a,b,esperado", [
    ("", "x", 0), ("x", "", 0), ("real madrid", "real madrid", 100),
    ("real madrid", "real", 80),            # 1 de 2 tokens (50) pero `b` está contenido en `a`: sube a 80
    ("madrid", "real madrid cf", 100.0),    # contenido: 1/1 tokens => 100
    ("real", "realejo fc", 80),             # subcadena sube a 80 mínimo
    ("boca", "river", 0.0),
])
def test_score_similitud(a, b, esperado):
    assert nz.score_similitud(a, b) == esperado


def test_score_similitud_subcadena_sin_tokens_comunes_vale_80():
    assert nz.score_similitud("man", "manchester") == 80


@pytest.mark.parametrize("api,entrada,esperado", [
    ("Real Madrid", "real madrid", True),                 # igual normalizado
    ("Manchester United", "Man United", False),            # tokens distintos, sin contención ni primera palabra
    ("Manchester United FC", "Manchester United", True),   # contención
    ("Atlético Madrid", "Atletico de Madrid", True),       # misma primera palabra larga
    ("River Plate", "Boca Juniors", False),
    ("Bo", "Bochum", False),                               # corto y primera palabra distinta
    ("", "", True),                                        # ambos vacíos normalizan igual
    ("Inter", "Inter Miami", True),                        # contención con 5+ letras
])
def test_coincide_nombre(api, entrada, esperado):
    assert nz.coincide_nombre(api, entrada) is esperado


@pytest.mark.parametrize("campo,esperado", [
    ({"name": "Boca"}, "Boca"), ({"name": None}, ""), ({}, ""), ("River", "River"), (None, ""), (5, ""), (["x"], ""),
])
def test_nombre_equipo_bsd_acepta_dict_o_string(campo, esperado):
    assert nz.nombre_equipo_bsd(campo) == esperado


@pytest.mark.parametrize("nombre,esperado", [
    ("Barcelona W", "Barcelona"), ("Ajax U19", "Ajax"), ("Ajax u21", "Ajax"), ("Betis B", "Betis"),
    ("Real Madrid II", "Real Madrid"), ("Espanyol Reserves", "Espanyol"), ("Real Madrid", "Real Madrid"),
    ("Newcastle", "Newcastle"),
])
def test_limpiar_sufijos(nombre, esperado):
    assert nz.limpiar_sufijos(nombre) == esperado


# ------------------------------------------------------------------ simulador: helpers puros
def test_resultado_ponderado_probabilidades_degeneradas():
    import random

    rng = random.Random(1)
    assert sim._resultado_ponderado(rng, 1.0, 0.0, 0.0) == "local"
    assert sim._resultado_ponderado(rng, 0.0, 0.0, 1.0) == "visitante"
    assert sim._resultado_ponderado(rng, -1.0, 2.0, -3.0) == "empate"  # negativos se tratan como 0
    assert sim._resultado_ponderado(rng, 0, 0, 0) in {"local", "empate", "visitante"}  # dato roto: equiprobable, no lanza


def test_construir_payload_motor_con_y_sin_datos():
    fixture = {"fixture": {"id": 99}, "teams": {"home": {"name": "A"}, "away": {"name": "B"}}}
    p = sim._construir_payload_motor(fixture, "Liga X", {"A": 2, "B": 7},
                                     {"A": {"favor": 1.8, "contra": 0.9}, "B": {"favor": 1.1, "contra": 1.4}})
    assert (p["local"], p["visitante"], p["partido_id"], p["liga"]) == ("A", "B", "99", "Liga X")
    assert (p["goles_local_avg"], p["goles_contra_visit_avg"], p["pos_local"], p["pos_visit"]) == (1.8, 1.4, 2, 7)
    assert p["h2h_disponible"] is False and p["odds_disponibles"] is False

    vacio = sim._construir_payload_motor({}, "L", {}, {})
    assert (vacio["local"], vacio["visitante"], vacio["partido_id"]) == ("Local", "Visitante", "")
    assert vacio["goles_local_avg"] is None and vacio["pos_local"] == 10


# ------------------------------------------------------------------ simulador: fuentes (api-football falsa)
def _fila(equipo, puntos, rank, jugados):
    return {"team": {"name": equipo}, "points": puntos, "rank": rank, "all": {"played": jugados}}


def _standings(*filas):
    return {"response": [{"league": {"standings": [list(filas)]}}]}


@pytest.fixture()
def apif(monkeypatch):
    """`_apif_get` falso: responde según el endpoint pedido y registra las llamadas."""
    respuestas: dict[str, dict] = {}
    llamadas: list[str] = []

    async def falso(client, endpoint):
        llamadas.append(endpoint)
        for fragmento, cuerpo in respuestas.items():
            if fragmento in endpoint:
                return cuerpo
        return {}

    monkeypatch.setattr(sim, "_apif_get", falso)
    falso.respuestas, falso.llamadas = respuestas, llamadas
    return falso


def test_tabla_y_posiciones_lee_standings(apif):
    apif.respuestas["standings?league=39"] = _standings(_fila("A", 30, 1, 10), _fila("B", 20, 2, 10), {"points": 1})
    tabla, pos, jugados = _correr(sim._tabla_y_posiciones(None, 39, 2026))
    assert tabla == {"A": 30, "B": 20} and pos == {"A": 1, "B": 2} and jugados == {"A": 10, "B": 10}


@pytest.mark.parametrize("cuerpo", [{}, {"response": []}, {"response": [{"league": {"standings": []}}]},
                                    {"response": [{"league": {"standings": [[]]}}]}])
def test_tabla_y_posiciones_sin_datos(apif, cuerpo):
    apif.respuestas["standings"] = cuerpo
    assert _correr(sim._tabla_y_posiciones(None, 39, 2026)) == ({}, {}, {})


def test_historial_multi_temporada_suma_temporadas_previas(apif):
    apif.respuestas["season=2025"] = _standings(_fila("A", 50, 1, 25), _fila("B", 30, 2, 25))
    apif.respuestas["season=2024"] = _standings(_fila("A", 40, 1, 25), {"team": {}, "points": 9})
    # 2023 no está en el plan => respuesta vacía, se salta en silencio
    h = _correr(sim._historial_multi_temporada(None, 128, 2026, 3))
    assert h == {"A": {"puntos": 90, "partidos": 50}, "B": {"puntos": 30, "partidos": 25}}
    assert len(apif.llamadas) == 3


def test_goles_avg_por_equipo(monkeypatch):
    async def stats(db, client, team_id, league_id, season):
        return {1: {"goals": {"for": {"average": {"total": "1.5"}}, "against": {"average": {"total": "0"}}}},
                2: None}.get(team_id)

    monkeypatch.setattr(sim, "_team_stats_cacheado", stats)
    r = _correr(sim._goles_avg_por_equipo(None, None, {"A": 1, "B": 2, "C": 0}, 39, 2026))
    assert r == {"A": {"favor": 1.5, "contra": 0.0}}  # B sin stats y C sin id se omiten


# ------------------------------------------------------------------ simulador: orquestador
def _fixture(fid, local, id_local, visita, id_visita, liga="Premier League"):
    return {"fixture": {"id": fid}, "league": {"name": liga},
            "teams": {"home": {"name": local, "id": id_local}, "away": {"name": visita, "id": id_visita}}}


@pytest.fixture()
def liga_completa(apif, monkeypatch):
    async def stats(db, client, team_id, league_id, season):
        return {"goals": {"for": {"average": {"total": "1.6"}}, "against": {"average": {"total": "1.1"}}}}

    monkeypatch.setattr(sim, "_team_stats_cacheado", stats)
    apif.respuestas["standings?league=39"] = _standings(_fila("A", 30, 1, 10), _fila("B", 20, 2, 10), _fila("C", 10, 3, 10))
    apif.respuestas["fixtures?league=39"] = {"response": [_fixture(1, "A", 11, "B", 12), _fixture(2, "C", 13, "A", 11)]}
    return apif


def test_simular_liga_slug_desconocido():
    r = _correr(sim.simular_liga_actual(None, None, "no_existe"))
    assert r == {"ok": False, "razon": "liga_slug desconocido: no_existe"}


def test_simular_liga_sin_standings_o_sin_fixtures(apif):
    r = _correr(sim.simular_liga_actual(None, None, "premier", n_simulaciones=10))
    assert r["ok"] is False and "standings" in r["razon"]
    apif.respuestas["standings?league=39"] = _standings(_fila("A", 30, 1, 10))
    r = _correr(sim.simular_liga_actual(None, None, "premier", n_simulaciones=10))
    assert r["ok"] is False and "partidos pendientes" in r["razon"]


def test_simular_liga_premier_devuelve_tabla_sin_capa_de_promedio(liga_completa):
    r = _correr(sim.simular_liga_actual(None, None, "premier", n_simulaciones=200, posiciones_copa=1, posiciones_descenso=1))
    assert r["ok"] is True and r["liga_nombre"] == "Premier League" and r["partidos_pendientes"] == 2
    assert set(r["tabla"]) == {"A", "B", "C"}
    assert sum(t["prob_campeon"] for t in r["tabla"].values()) == pytest.approx(1.0, abs=0.01)
    assert all("prob_descenso_por_promedio" not in t for t in r["tabla"].values())
    assert "n_temporadas_historial" not in r  # solo la Liga Profesional lleva la capa de promedio


def test_simular_liga_argentina_sin_historial_avisa(liga_completa, monkeypatch):
    anio = sim.datetime.now().year
    liga_completa.respuestas.clear()
    liga_completa.respuestas[f"standings?league=128&season={anio}"] = _standings(_fila("A", 30, 1, 10), _fila("B", 20, 2, 10))
    liga_completa.respuestas["fixtures?league=128"] = {"response": [_fixture(1, "A", 11, "B", 12, "Liga Profesional")]}
    r = _correr(sim.simular_liga_actual(None, None, sim.LIGA_ARGENTINA_SLUG, n_simulaciones=20))
    assert r["ok"] is True and r["descenso_por_promedio_multi_temporada"] is False
    assert "prob_descenso_por_promedio no se calculó" in r["aviso_descenso_por_promedio"]


def test_simular_liga_argentina_con_historial_calcula_prob_por_promedio(liga_completa):
    anio = sim.datetime.now().year
    liga_completa.respuestas.clear()
    liga_completa.respuestas[f"standings?league=128&season={anio}"] = _standings(_fila("A", 30, 1, 10), _fila("B", 20, 2, 10))
    liga_completa.respuestas[f"standings?league=128&season={anio - 1}"] = _standings(_fila("A", 60, 1, 30), _fila("B", 15, 2, 30))
    liga_completa.respuestas["fixtures?league=128"] = {"response": [_fixture(1, "A", 11, "B", 12, "Liga Profesional")]}
    r = _correr(sim.simular_liga_actual(None, None, sim.LIGA_ARGENTINA_SLUG, n_simulaciones=50,
                                        posiciones_descenso=1, n_temporadas_historial=1))
    assert r["descenso_por_promedio_multi_temporada"] is True
    assert r["tabla"]["B"]["prob_descenso_por_promedio"] == 1.0  # promedio claramente peor
    assert r["tabla"]["A"]["prob_descenso_por_promedio"] == 0.0
