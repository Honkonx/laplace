"""MS-5: seguir un campeonato desde el chat (tabla propia, última jornada y simulación solo para pro/max y administradores). Base de las migraciones reales, agente real y una temporada SINTÉTICA
(los datos históricos reales no se publican); lo único simulado es el origen de los partidos (`simulador_propio._partidos`)."""
from __future__ import annotations

import asyncio
import random

import pytest

from backend.api.db import bot_memoria_repo, usuarios_repo
from backend.api.models.usuarios import Usuario
from backend.api.services import agent_campeonato, agent_runtime, simulador_propio

EQUIPOS = ["Arsenal", "Brighton", "Chelsea", "Everton", "Fulham", "Leeds", "Newcastle", "Wolves"]


def _temporada(temporada: str, dia0: int, ida_y_vuelta: bool, semilla: int) -> list[dict]:
    rng = random.Random(semilla)
    ps, dia = [], dia0
    for a in EQUIPOS:
        for b in EQUIPOS:
            if a == b or (not ida_y_vuelta and EQUIPOS.index(a) > EQUIPOS.index(b)):
                continue
            dia += 1
            ps.append({"liga": "E0", "temporada": temporada, "dia": dia, "local": a, "visitante": b, "gl": rng.randint(0, 3), "gv": rng.randint(0, 2), "resultado": "H", "tl": None, "tv": None, "al": None, "av": None})
    return ps


@pytest.fixture(autouse=True)
def _datos_sinteticos(monkeypatch):
    partidos = _temporada("2425", 738000, True, 1) + _temporada("2526", 738400, False, 2)   # una temporada anterior completa y la actual a medias
    simulador_propio.limpiar_cache()
    monkeypatch.setattr(simulador_propio, "_partidos", lambda: partidos)
    yield
    simulador_propio.limpiar_cache()


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


def _usuario(db, sub: str, plan: str) -> None:
    db.add(Usuario(device_id=sub, activo=1, plan=plan, nickname=sub, origen="telegram", creado_en="2026-11-20T00:00:00"))
    db.commit()


@pytest.mark.parametrize("frase, herramienta", [("tabla de la premier", "agent.campeonato"), ("clasificacion de la premier league", "agent.campeonato"), ("posiciones de la liga espanola", "agent.campeonato"),
                                                ("quien lidera la serie a", "agent.campeonato"), ("como van mis ligas", "agent.campeonato"), ("resumen de la jornada", "agent.campeonato"),
                                                ("tabla de la liga chilena", "agent.tabla_no_disponible"), ("clasificacion de la liga", "agent.tabla_no_disponible")])
def test_el_enrutador_manda_la_tabla_de_una_liga_conocida_al_campeonato_y_el_resto_sigue_igual(frase, herramienta):
    assert agent_runtime._respuesta_reglas(agent_runtime._normalizar_humano(frase), False)[2] == herramienta


def test_la_tabla_propia_ordena_por_puntos_y_trae_la_ultima_jornada(db):
    t = agent_campeonato.resumen(db, "telegram:1", "tabla de la premier")
    lineas = t.split("\n")
    assert lineas[0].startswith("Premier League 2526") and "28 jugados, 28 por jugar" in lineas[0]
    pts = [int(l.split(" pts")[0].rsplit(" ", 1)[1]) for l in lineas if l[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert len(pts) == 5 and pts == sorted(pts, reverse=True)
    assert any(l.startswith("Último día jugado") for l in lineas)


def test_la_simulacion_es_solo_de_pro_max_y_administradores(db):
    _usuario(db, "10", "free")
    _usuario(db, "11", "pro")
    _usuario(db, "12", "max")
    libre = agent_campeonato.resumen(db, "telegram:10", "tabla de la premier")
    assert "planes pro y max" in libre and "simulaciones" not in libre and "Campeón" not in libre
    for uid in ("telegram:11", "telegram:12"):
        r = agent_campeonato.resumen(db, uid, "tabla de la premier")
        assert "1.000 simulaciones" in r and "Campeón:" in r and "Estimación, no certeza" in r and "planes pro y max" not in r
    admin = agent_campeonato.resumen(db, "telegram:99", "tabla de la premier", es_admin=True)
    assert "Campeón:" in admin
    assert "Campeón:" not in agent_campeonato.resumen(db, "sin-registro", "tabla de la premier")     # quien no está registrado cuenta como free


def test_sin_liga_mencionada_usa_las_que_sigue_y_si_no_sigue_ninguna_orienta(db):
    assert "sigue una con" in agent_campeonato.resumen(db, "telegram:20", "como van mis ligas")
    _usuario(db, "21", "pro")
    bot_memoria_repo.aceptar(db, "21")
    assert usuarios_repo.agregar_favorito_liga(db, "21", "Premier League")["agregado"]
    r = agent_campeonato.resumen(db, "telegram:21", "como van mis ligas")
    assert r.startswith("Premier League 2526") and "Campeón:" in r


def test_una_liga_sin_datos_dice_por_que_en_vez_de_inventar_una_tabla(db):
    r = agent_campeonato.resumen(db, "telegram:30", "tabla de la liga espanola")
    assert r.startswith("La Liga: ") and "no tiene datos propios todavía" in r


def test_de_punta_a_punta_con_el_agente_real(db):
    _usuario(db, "40", "free")
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "telegram:40", "tabla de la premier", None, "telegram_agent", False, False))
    assert r["herramienta"] == "agent.campeonato" and "pts (PJ" in r["respuesta"] and "planes pro y max" in r["respuesta"]
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "telegram:40", "tabla de la liga chilena", None, "telegram_agent", False, False))
    assert r["herramienta"] == "agent.tabla_no_disponible"


def test_si_el_simulador_falla_el_chat_no_se_rompe(db, monkeypatch):
    def roto(*_a, **_k):
        raise RuntimeError("sin datos")

    monkeypatch.setattr(simulador_propio, "preparar", roto)
    assert "No pude armar el resumen" in agent_campeonato.resumen(db, "telegram:50", "tabla de la premier")


@pytest.mark.parametrize("texto, slug", [("tabla de la liga chilena", None), ("simula la liga argentina", None), ("la liga de colombia", None), ("la liga inglesa", "premier"), ("la liga de espana", "laliga"),
                                         ("la liga espanola", "laliga"), ("laliga", "laliga"), ("premier league", "premier")])
def test_la_liga_a_secas_ya_no_se_come_las_ligas_de_otros_paises(texto, slug):
    """Antes «la liga chilena» se resolvía como La Liga de España (el alias «la liga» la capturaba)."""
    assert simulador_propio.liga_de_texto(texto) == slug


def test_en_el_chat_la_liga_a_secas_es_ambigua_y_no_se_adivina():
    assert agent_campeonato.liga_explicita("clasificacion de la liga") is None and agent_campeonato.liga_explicita("clasificacion de laliga") == "laliga"
