"""Tabla de posiciones con los resultados propios: solo cuando se puede confiar en ella, con la forma de football-data.org y sin emparejar al equipo equivocado."""
from __future__ import annotations

import itertools
from datetime import date

import pytest

from backend.api.services import modelo_historico, standings_fetch, tabla_propia

EQUIPOS = [f"Eq{i}" for i in range(8)]


def _p(temporada, dia, local, visitante, gl, gv, liga="LIG"):
    return {"liga": liga, "temporada": temporada, "dia": dia, "fecha": date.fromordinal(dia), "local": local, "visitante": visitante, "gl": gl, "gv": gv}


def _temporada(temporada, inicio, equipos=EQUIPOS, solo=None):
    ps, dia = [], inicio
    for a, b in itertools.permutations(equipos, 2):
        dia += 1
        ps.append(_p(temporada, dia, a, b, 2 if a < b else 0, 1))
    return ps[:solo] if solo else ps


@pytest.fixture()
def liga_resuelta(monkeypatch):
    monkeypatch.setattr(modelo_historico, "_resolver", lambda d: ("LIG", None, "Eq0", "Eq1") if d["local"] in ("Eq0", "El Cero") and d["visitante"] in ("Eq1", "El Uno") else (None, "x"))


def _hoy(partidos):
    return date.fromordinal(max(p["dia"] for p in partidos) + 3)


def test_la_tabla_propia_se_arma_con_posiciones_puntos_y_forma_en_formato_football_data(liga_resuelta):
    partidos = _temporada("2025/2026", 739000) + _temporada("2026/2027", 739400, solo=30)
    t = tabla_propia.construir("El Cero", "El Uno", "Liga", hoy=_hoy(partidos), partidos=partidos)
    assert t and t["fuente"] == "resultados_propios" and t["temporada"] == "2026/2027"
    filas = t["standings"][0]["table"]
    assert [f["position"] for f in filas] == list(range(1, 9)) and sum(f["playedGames"] for f in filas) == 60
    assert all(f["points"] == 3 * f["won"] + f["draw"] and f["goalDifference"] == f["goalsFor"] - f["goalsAgainst"] for f in filas)
    assert all(set(f["form"].split(",")) <= {"W", "D", "L"} and len(f["form"].split(",")) <= 5 for f in filas if f["playedGames"])
    nombres = [f["team"]["name"] for f in filas]
    assert "El Cero" in nombres and "El Uno" in nombres and "Eq0" not in nombres, "los dos equipos del partido llevan el nombre del partido actual"
    puntos = [f["points"] for f in filas]
    assert puntos == sorted(puntos, reverse=True)


@pytest.mark.parametrize("caso", ["atrasada", "equipos_faltantes", "sin_temporada_anterior_completa", "liga_sin_datos", "equipo_no_resuelto"])
def test_sin_condiciones_de_confianza_no_hay_tabla_y_se_dice_con_none(liga_resuelta, caso):
    previa = _temporada("2025/2026", 739000)
    if caso == "equipos_faltantes":
        actual = _temporada("2026/2027", 739400, equipos=EQUIPOS[:6], solo=20)
    elif caso == "sin_temporada_anterior_completa":
        previa, actual = previa[:20], _temporada("2026/2027", 739400, solo=30)
    elif caso == "liga_sin_datos":
        previa, actual = [], []
    else:
        actual = _temporada("2026/2027", 739400, solo=30)
    partidos = previa + actual
    hoy = date.fromordinal(739400 + 400) if caso == "atrasada" else (date.fromordinal(max((p["dia"] for p in partidos), default=739000) + 3))
    local = "Desconocido" if caso == "equipo_no_resuelto" else "El Cero"
    assert tabla_propia.construir(local, "El Uno", "Liga", hoy=hoy, partidos=partidos) is None


def test_el_cruce_de_nombres_prefiere_el_exacto_y_no_empareja_al_equipo_equivocado():
    tabla = {"standings": [{"table": [{"position": 1, "team": {"name": "Real Betis"}, "points": 30}, {"position": 2, "team": {"name": "Real Madrid"}, "points": 28}]}]}
    pos, _victorias, texto = standings_fetch.extraer_posicion_y_forma(tabla, "Real Madrid")
    assert pos == 2 and "28 pts" in texto, "antes emparejaba con «Real Betis» por compartir «real»"
    pos, _v, _t = standings_fetch.extraer_posicion_y_forma(tabla, "Betis")
    assert pos == 1, "el cruce aproximado sigue funcionando cuando no hay nombre exacto"


def test_una_falla_interna_no_rompe_el_analisis(monkeypatch):
    monkeypatch.setattr(modelo_historico, "_resolver", lambda d: (_ for _ in ()).throw(RuntimeError("alias roto")))
    assert tabla_propia.construir("A", "B", "Liga", partidos=[]) is None
