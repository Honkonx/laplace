"""Ligas homónimas de países distintos (H-027): «Premier League» de Inglaterra y de Egipto, «Serie B» de Brasil y de Italia no se mezclan al guardar, leer, mostrar en Telegram ni en el catálogo web.

Base construida con las migraciones reales; manejadores y rutas reales; solo el exterior (Telegram, fuentes de datos) simulado. La medición que motivó esto (base real, 2026-11-12): «premier-league»
juntaba 280 equipos distintos, «super-league» 101 y «ligue-1» 68 porque el identificador se armaba solo con el nombre y se descartaba el país que sí manda la fuente.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import inspect, text

from backend.api.bot import laplace_bot_callbacks, ligas as ligas_bot
from backend.api.db import partidos_repo
from backend.api.routers import web_catalog
from backend.api.services import gateway, ligas_ident
from backend.api.services.gateway_cascada import guardar_stages_en_cache

HOY = datetime.now().strftime("%Y%m%d")
HOY_BD = f"{HOY[:4]}-{HOY[4:6]}-{HOY[6:]}"


def _ev(eid: str, local: str, visitante: str) -> dict:
    return {"Eid": eid, "Eps": "NS", "T1": [{"Nm": local}], "T2": [{"Nm": visitante}], "Esd": f"{HOY}2000"}


STAGES = [
    {"Snm": "Premier League", "Cnm": "Inglaterra", "Events": [_ev("1", "Arsenal", "Chelsea"), _ev("2", "Liverpool", "Everton")]},
    {"Snm": "Premier League", "Cnm": "Egipto", "Events": [_ev("3", "El Zamalek", "Pyramids FC")]},
    {"Snm": "Serie B", "Cnm": "Brasil", "Events": [_ev("4", "Sao Bernardo", "Athletic Club")]},
    {"Snm": "Serie B", "Cnm": "Italia", "Events": [_ev("5", "Palermo", "Pisa")]},
]


@pytest.fixture()
def entorno(base_migrada, monkeypatch):
    fabrica = base_migrada("head")
    monkeypatch.setattr(laplace_bot_callbacks, "SessionLocal", fabrica)
    monkeypatch.setattr(laplace_bot_callbacks.telegram_client, "responder_callback", AsyncMock())
    monkeypatch.setattr(ligas_bot, "_evento_cubierto", lambda stage, ev: False)
    with fabrica() as db:
        guardar_stages_en_cache(db, HOY, STAGES, "livescore6")
    return fabrica


def test_la_migracion_agrega_la_columna_del_pais(entorno):
    with entorno() as db:
        assert "liga_pais" in {c["name"] for c in inspect(db.get_bind()).get_columns("partidos_dia")}


def test_dos_ligas_homonimas_se_guardan_con_identificadores_y_pais_distintos(entorno):
    with entorno() as db:
        filas = db.execute(text("select match_id, liga_slug, liga_nombre, liga_pais from partidos_dia order by match_id")).all()
    por_id = {f[0]: f for f in filas}
    assert por_id["1"][1] == por_id["2"][1] == "premier-league-england" and por_id["1"][3] == "Inglaterra"
    assert por_id["3"][1] == "premier-league-egypt" and por_id["3"][1] != por_id["1"][1]
    assert por_id["4"][1] != por_id["5"][1] and {por_id["4"][3], por_id["5"][3]} == {"Brasil", "Italia"}
    assert all(f[2] in ("Premier League", "Serie B") for f in filas), "el nombre sigue siendo el de la fuente"


def test_leer_una_liga_por_su_identificador_no_trae_los_partidos_de_la_homonima(entorno):
    with entorno() as db:
        r = partidos_repo.leer_partidos_dia_agrupado(db, HOY_BD, "premier-league-england")
        assert sorted(b["local"] for b in r["buttons"]) == ["Arsenal", "Liverpool"]
        egipto = partidos_repo.leer_partidos_dia_agrupado(db, HOY_BD, "premier-league-egypt")
        assert [b["local"] for b in egipto["buttons"]] == ["El Zamalek"]
        ligas = partidos_repo.leer_ligas_cache(db, HOY_BD)["ligas"]
        assert ligas["premier-league-england"]["pais"] == "Inglaterra" and ligas["serie-b-italy"]["pais"] == "Italia"


def test_el_menu_de_telegram_ofrece_cada_pais_por_separado_y_el_boton_trae_solo_sus_partidos(entorno):
    with entorno() as db:
        stages, fuente = asyncio.run(gateway.obtener_fixtures_cascada(db, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))), HOY))
    assert fuente == "bd" and all(s.get("Cnm") for s in stages), "el país hace el viaje de ida y vuelta por la base"
    menu = ligas_bot.ligas_con_partidos(stages, solo_prioritarias=False)
    nombres = {l["nombre"]: l for l in menu}
    assert {"Premier League (Inglaterra)", "Premier League (Egipto)", "Serie B (Brasil)", "Serie B (Italia)"} <= set(nombres)
    assert nombres["Premier League (Inglaterra)"]["partidos"] == 2 and nombres["Premier League (Egipto)"]["partidos"] == 1

    u = MagicMock()
    u.effective_user.id = 7001
    u.callback_query.id = "cbq"
    u.callback_query.data = f"LEAGUE_{HOY}_{nombres['Serie B (Italia)']['slug']}"
    u.callback_query.message.reply_html = AsyncMock()
    c = MagicMock()
    c.application.bot_data = {"http_client": httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))}
    asyncio.run(laplace_bot_callbacks.callback_liga(u, c))
    cuerpo = " ".join(str(x) for call in u.callback_query.message.reply_html.call_args_list for x in call.args) + str(u.callback_query.message.reply_html.call_args_list)
    assert "Palermo" in cuerpo and "Sao Bernardo" not in cuerpo and "Serie B (Italia)" in cuerpo


def test_el_catalogo_web_muestra_el_pais_y_separa_las_ligas_homonimas(entorno):
    with entorno() as db:
        r = asyncio.run(web_catalog.fixtures(date=HOY, scope="all", league=None, q=None, status=None, limit=100, offset=0, db=db))
        nombres = {x["name"] for x in r["leagues"]}
        assert {"Premier League (Inglaterra)", "Premier League (Egipto)", "Serie B (Brasil)", "Serie B (Italia)"} <= nombres
        solo = asyncio.run(web_catalog.fixtures(date=HOY, scope="all", league="premier-league-egypt", q=None, status=None, limit=100, offset=0, db=db))
        assert [f["home"]["name"] for f in solo["fixtures"]] == ["El Zamalek"] and solo["fixtures"][0]["league"]["name"] == "Premier League (Egipto)"
        assert solo["fixtures"][0]["league"]["country"] == "Egipto"


def test_las_filas_viejas_sin_pais_siguen_leyendose_con_su_identificador_de_siempre(entorno):
    with entorno() as db:
        db.execute(text("insert into partidos_dia (fecha, match_id, liga_slug, liga_nombre, local, visitante, status, creado_en, cache_invalidado) values (:f, '99', 'premier-league', 'Premier League', 'Viejo A', 'Viejo B', 'scheduled', '2026-11-12 10:00:00', 0)"), {"f": HOY_BD})
        db.commit()
        r = asyncio.run(web_catalog.fixtures(date=HOY, scope="all", league="premier-league", q=None, status=None, limit=100, offset=0, db=db))
        assert [f["home"]["name"] for f in r["fixtures"]] == ["Viejo A"] and r["fixtures"][0]["league"]["name"] == "Premier League" and r["fixtures"][0]["league"]["country"] is None


@pytest.mark.parametrize("nombre,pais,slug,visible", [
    ("Premier League", "Inglaterra", "premier-league-england", "Premier League (Inglaterra)"),
    ("Premier League", "England", "premier-league-england", "Premier League (England)"),
    ("Serie B", "Brasil", "serie-b-brazil", "Serie B (Brasil)"),
    ("Primera Division Argentina", "Argentina", "primera-division-argentina-argentina", "Primera Division Argentina"),
    ("Cup", None, "cup", "Cup"),
    ("", "", "otras", "Liga"),
    ("💥" * 50, "💥", "otras", None),
])
def test_identificador_y_nombre_visible(nombre, pais, slug, visible):
    assert ligas_ident.slug_competicion(nombre, pais) == slug or slug == "otras"
    if visible is not None:
        assert ligas_ident.nombre_visible(nombre, pais) == visible
    assert len(ligas_ident.slug_competicion("x" * 200, "y" * 200)) <= 43, "cabe en el callback_data de Telegram junto con la fecha"


def test_el_identificador_cabe_en_el_callback_de_telegram():
    peor = f"LEAGUE_{HOY}_{ligas_ident.slug_competicion('a' * 200, 'b' * 200)}"
    assert len(peor.encode("utf-8")) <= 64


# ---- reclasificador de filas viejas --------------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def base_con_filas_viejas(entorno, tmp_path):
    filas = [("10", "premier-league", "Premier League", "Arsenal", "Chelsea"), ("11", "premier-league", "Premier League", "El Zamalek", "Pyramids FC"), ("12", "serie-b", "Serie B", "Palermo", "Pisa")]
    with entorno() as db:
        db.execute(text("delete from partidos_dia"))
        for mid, slug, nombre, local, visitante in filas:
            db.execute(text("insert into partidos_dia (fecha, match_id, liga_slug, liga_nombre, local, visitante, status, creado_en, cache_invalidado) values (:f, :m, :s, :n, :l, :v, 'scheduled', '2026-11-12 10:00:00', 0)"),
                       {"f": HOY_BD, "m": mid, "s": slug, "n": nombre, "l": local, "v": visitante})
        db.commit()
        ruta = db.get_bind().url.database
    return ruta


def _resolutor_falso(d):
    equipos = {"Arsenal": ("E0", "Chelsea"), "Palermo": ("I2", "Pisa")}
    codigo = equipos.get(d["local"])
    return (codigo[0], None, d["local"], d["visitante"]) if codigo else (None, "fuera de cobertura")


def test_el_reclasificador_por_defecto_solo_informa_y_no_cambia_nada(base_con_filas_viejas, monkeypatch, capsys):
    from backend.scripts import reclasificar_partidos_dia as rc

    monkeypatch.setattr(rc.modelo_historico, "_resolver", _resolutor_falso)
    monkeypatch.setattr(rc, "paises_por_codigo", lambda: {"E0": "England", "I2": "Italy"})
    assert rc.main.__module__ and _correr_rc(rc, ["--db", base_con_filas_viejas]) == 0
    assert "se pueden clasificar: 2" in capsys.readouterr().out
    import sqlite3

    assert sqlite3.connect(base_con_filas_viejas).execute("select count(*) from partidos_dia where liga_pais is not null").fetchone()[0] == 0, "sin --aplicar no escribe nada"


def test_con_aplicar_clasifica_solo_lo_resuelto_hace_copia_y_es_idempotente(base_con_filas_viejas, monkeypatch):
    import sqlite3
    from pathlib import Path

    from backend.scripts import reclasificar_partidos_dia as rc

    monkeypatch.setattr(rc.modelo_historico, "_resolver", _resolutor_falso)
    monkeypatch.setattr(rc, "paises_por_codigo", lambda: {"E0": "England", "I2": "Italy"})
    assert _correr_rc(rc, ["--db", base_con_filas_viejas, "--aplicar", "--si"]) == 0
    assert list(Path(base_con_filas_viejas).parent.glob("*.antes_de_reclasificar.db")), "copia de seguridad antes de escribir"
    con = sqlite3.connect(base_con_filas_viejas)
    filas = {m: (p, s) for m, p, s in con.execute("select match_id, liga_pais, liga_slug from partidos_dia")}
    assert filas["10"] == ("England", "premier-league-england") and filas["12"] == ("Italy", "serie-b-italy")
    assert filas["11"] == (None, "premier-league"), "la que no se pudo resolver queda sin país: no se inventa"
    assert _correr_rc(rc, ["--db", base_con_filas_viejas, "--aplicar", "--si"]) == 0
    assert {m: (p, s) for m, p, s in con.execute("select match_id, liga_pais, liga_slug from partidos_dia")} == filas, "segunda corrida: sin cambios"


def test_si_la_base_no_tiene_la_columna_el_reclasificador_lo_dice(tmp_path, capsys):
    import sqlite3

    from backend.scripts import reclasificar_partidos_dia as rc

    ruta = tmp_path / "vieja.db"
    sqlite3.connect(ruta).execute("create table partidos_dia (fecha text, match_id text, liga_slug text, liga_nombre text, local text, visitante text)").connection.commit()
    assert _correr_rc(rc, ["--db", str(ruta)]) == 3 and "aún no tiene la columna" in capsys.readouterr().out


def _correr_rc(modulo, argumentos):
    import sys

    anterior = sys.argv
    sys.argv = ["reclasificar_partidos_dia.py", *argumentos]
    try:
        return modulo.main()
    finally:
        sys.argv = anterior


@pytest.mark.parametrize("espanol,ingles", [("Egipto", "Egypt"), ("Sudáfrica", "South Africa"), ("Emiratos Árabes Unidos", "United Arab Emirates"), ("República Checa", "Czech Republic"), ("Costa de Marfil", "Ivory Coast"), ("Inglaterra", "England")])
def test_dos_fuentes_que_escriben_el_pais_en_idiomas_distintos_dan_el_mismo_identificador(espanol, ingles):
    ligas_ident.limpiar_cache()
    assert ligas_ident.slug_competicion("Premier League", espanol) == ligas_ident.slug_competicion("Premier League", ingles)


def test_los_nombres_largos_que_solo_difieren_al_final_no_colisionan_y_el_identificador_es_estable():
    """Medido en la base real: «Primera Division RFEF: Group 1» y «Group 2» (y las de Australia y la Euro U19) compartían identificador por el truncado."""
    a = ligas_ident.slug_competicion("Primera Division RFEF: Group 1", "Spain")
    b = ligas_ident.slug_competicion("Primera Division RFEF: Group 2", "Spain")
    assert a != b and a == ligas_ident.slug_competicion("Primera Division RFEF: Group 1", "Spain"), "distintos entre sí y estables entre corridas"
    assert len(a) <= 43 and len(f"LEAGUE_{HOY}_{a}".encode()) <= 64
    largos = [f"Australian Championship 2026: Group {c}" for c in "ABCD"] + [f"EURO U19 Qualification Round 2 League A Group {i}" for i in range(1, 5)]
    assert len({ligas_ident.slug_competicion(n, "Australia") for n in largos}) == len(largos)
    assert ligas_ident.slug_competicion("Premier League", "England") == "premier-league-england", "los nombres cortos no cambian"


def test_el_reclasificador_tambien_recalcula_el_identificador_de_filas_que_ya_tienen_pais(base_con_filas_viejas, monkeypatch):
    import sqlite3

    from backend.scripts import reclasificar_partidos_dia as rc

    con = sqlite3.connect(base_con_filas_viejas)
    con.execute("update partidos_dia set liga_pais='Spain', liga_slug='primera-division-rfef-group-spain', liga_nombre='Primera Division RFEF: Group 1' where match_id='10'")
    con.commit()
    monkeypatch.setattr(rc.modelo_historico, "_resolver", lambda d: (None, "x"))
    monkeypatch.setattr(rc, "paises_por_codigo", lambda: {})
    assert _correr_rc(rc, ["--db", base_con_filas_viejas, "--aplicar", "--si"]) == 0
    esperado = ligas_ident.slug_competicion("Primera Division RFEF: Group 1", "Spain")
    assert sqlite3.connect(base_con_filas_viejas).execute("select liga_slug from partidos_dia where match_id='10'").fetchone()[0] == esperado
