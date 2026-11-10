"""test_ml_vivo.py — capa de resultados en vivo (`ml/vivo.py`, `ml/datos.cargar_partidos_con_vivo`).

Sin red ni numpy: BD sqlite temporal y resolvedor simulado."""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from backend.api.ml import datos, vivo

HOY = date(2026, 10, 7)
METAS = {
    "COL1": {"nombre": "Primera A", "pais": "colombia", "europea": False},
    "E0": {"nombre": "Premier League", "pais": "england", "europea": True},
}


def resolver_falso(c: dict) -> tuple:
    if c["liga"] == "Primera A":
        if c["local"] == "Equipo Nuevo":
            return None, "equipo_desconocido", "COL1: Equipo Nuevo"
        return "COL1", c["local"].replace("FC ", ""), c["visitante"].replace("FC ", "")
    if c["liga"] == "Premier League":
        return "E0", c["local"], c["visitante"]
    return None, "liga_sin_modelo", c["liga"]


def crudo(**kw) -> dict:
    base = {"origen": "resultados_partidos", "fecha": "2026-10-05", "local": "FC Junior", "visitante": "Millonarios",
            "gl": 2, "gv": 1, "liga": "Primera A", "liga_id": "239", "estado": "ft", "fixture_id": "1"}
    return {**base, **kw}


def test_acepta_fila_valida_con_esquema_del_maestro():
    filas, descartes = vivo.clasificar([crudo()], resolver_falso, METAS, hoy=HOY)
    assert not descartes
    f = filas[0]
    assert set(f) == set(vivo.CAMPOS)
    assert (f["liga_codigo"], f["temporada"], f["fuente"], f["resultado"]) == ("COL1", "2026", "laplace_vivo", "H")
    assert (f["local_canon"], f["visitante_canon"], f["goles_local"], f["goles_visitante"]) == ("Junior", "Millonarios", 2, 1)


def test_temporada_europea_cruza_el_anio():
    filas, _ = vivo.clasificar(
        [crudo(liga="Premier League", fecha="2027-02-01"), crudo(liga="Premier League", fecha="2026-10-05", local="A", visitante="B")],
        resolver_falso, METAS, hoy=date(2027, 3, 1))
    assert {f["temporada"] for f in filas} == {"2026/2027"}


@pytest.mark.parametrize("cambio,razon", [
    ({"fecha": "20261005"}, "fecha_invalida"), ({"fecha": "2026--1-0-"}, "fecha_invalida"), ({"fecha": ""}, "fecha_invalida"),
    ({"fecha": "2026-12-31"}, "fecha_invalida"), ({"gl": None}, "marcador_invalido"), ({"gl": -1}, "marcador_invalido"),
    ({"gv": 99}, "marcador_invalido"), ({"estado": "2h"}, "estado_no_terminado"), ({"estado": "pen"}, "estado_no_terminado"),
    ({"liga": "Liga Desconocida"}, "liga_sin_modelo"), ({"local": "Equipo Nuevo"}, "equipo_desconocido"),
    ({"visitante": "FC Junior"}, "equipos_invalidos"),
])
def test_descarta_lo_dudoso_con_razon(cambio, razon):
    filas, descartes = vivo.clasificar([crudo(**cambio)], resolver_falso, METAS, hoy=HOY)
    assert filas == [] and [d["razon"] for d in descartes] == [razon]


def test_deduplica_entre_fuentes_y_tolera_un_dia_de_diferencia():
    a = crudo()
    b = crudo(origen="partidos_dia", fixture_id="x", estado="finished")  # mismo partido, otra tabla
    c = crudo(origen="partidos_dia", fecha="2026-10-06", estado="finished")  # fecha local vs UTC
    filas, descartes = vivo.clasificar([b, a, c], resolver_falso, METAS, hoy=HOY)
    assert len(filas) == 1 and [d["razon"] for d in descartes] == ["duplicado", "duplicado"]


def test_marcador_en_conflicto_se_descarta_y_se_reporta():
    filas, descartes = vivo.clasificar([crudo(), crudo(origen="partidos_dia", gl=0, estado="finished")], resolver_falso, METAS, hoy=HOY)
    assert len(filas) == 1 and filas[0]["goles_local"] == 2
    assert descartes[0]["razon"] == "marcador_en_conflicto"


def test_la_capa_es_acumulativa_y_la_escritura_idempotente(tmp_path):
    ruta = tmp_path / "vivo" / "resultados_vivos.csv.gz"
    filas, _ = vivo.clasificar([crudo()], resolver_falso, METAS, hoy=HOY)
    vivo.escribir_csv_gz(filas, ruta)
    primera = ruta.read_bytes()
    filas2, _ = vivo.clasificar([crudo()], resolver_falso, METAS, vivo.leer_csv_gz(ruta), hoy=HOY)
    vivo.escribir_csv_gz(filas2, ruta)
    assert ruta.read_bytes() == primera  # misma entrada, mismos bytes
    # la fuente original desaparece (purga de partidos_dia): lo exportado antes se conserva
    filas3, _ = vivo.clasificar([crudo(fecha="2026-10-06", local="Otro", visitante="Otro2")], resolver_falso, METAS,
                                vivo.leer_csv_gz(ruta), hoy=HOY)
    assert len(filas3) == 2 and not list(ruta.parent.glob("*.tmp"))


def _bd(tmp_path):
    ruta = tmp_path / "t.db"
    con = sqlite3.connect(ruta)
    con.executescript("""
    CREATE TABLE partidos_dia (fecha TEXT, match_id TEXT, apifootball_fixture_id TEXT, liga_nombre TEXT, liga_codigo TEXT,
        local TEXT, visitante TEXT, goles_local INT, goles_visitante INT, status TEXT, cache_invalidado INT);
    CREATE TABLE resultados_partidos (fixture_id TEXT, local TEXT, visitante TEXT, liga TEXT, goles_local INT,
        goles_visitante INT, status_api TEXT, fecha_partido TEXT);
    INSERT INTO partidos_dia VALUES ('2026-10-05','1','900','Primera A','239','FC Junior','Millonarios',2,1,'finished',1);
    INSERT INTO partidos_dia VALUES ('2026--1-0-','2','901','Primera A','239','A','B',1,0,'finished',1);
    INSERT INTO partidos_dia VALUES ('2026-10-05','3',NULL,'Primera A','239','C','D',NULL,NULL,'scheduled',0);
    INSERT INTO resultados_partidos VALUES ('900','FC Junior','Millonarios','',2,1,'FT','2026-10-05');
    """)
    con.commit()
    con.close()
    return ruta


def test_lee_la_bd_en_solo_lectura_y_hereda_la_liga(tmp_path):
    ruta = _bd(tmp_path)
    antes = ruta.read_bytes()
    crudos = vivo.leer_crudos_bd(ruta)
    assert ruta.read_bytes() == antes  # no se escribió nada
    res = next(c for c in crudos if c["origen"] == "resultados_partidos")
    assert (res["liga"], res["liga_id"]) == ("Primera A", "239")  # liga vacía en resultados: se hereda del fixture
    filas, descartes = vivo.clasificar(crudos, resolver_falso, METAS, hoy=HOY)
    assert len(filas) == 1 and "fecha_invalida" in {d["razon"] for d in descartes}
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):  # el modo es realmente de solo lectura
        con.execute("INSERT INTO partidos_dia (fecha) VALUES ('x')")
    con.close()


def _escribir(ruta, filas):
    vivo.escribir_csv_gz([{**dict.fromkeys(vivo.CAMPOS, ""), **f} for f in filas], ruta)


def _fila(liga, fecha, local, visitante, gl, gv, fuente):
    return {"liga_codigo": liga, "liga_nombre": "L", "temporada": "2026", "fecha": fecha, "local": local, "visitante": visitante,
            "local_canon": local, "visitante_canon": visitante, "goles_local": gl, "goles_visitante": gv,
            "resultado": "H" if gl > gv else "A" if gv > gl else "D", "fuente": fuente}


def test_cargador_comun_no_duplica_partidos_del_maestro(tmp_path):
    maestro, capa = tmp_path / "m.csv.gz", tmp_path / "v.csv.gz"
    _escribir(maestro, [_fila("COL1", "2026-10-05", "Junior", "Millonarios", 2, 1, "api-football")])
    _escribir(capa, [
        _fila("COL1", "2026-10-05", "Junior", "Millonarios", 2, 1, "laplace_vivo"),  # igual: duplicado
        _fila("COL1", "2026-10-06", "Junior", "Millonarios", 2, 1, "laplace_vivo"),  # +1 día: duplicado
        _fila("COL1", "2026-10-12", "Junior", "Millonarios", 0, 0, "laplace_vivo"),  # revancha real: nuevo
    ])
    partidos, info = datos.cargar_partidos_con_vivo(maestro, capa)
    assert len(partidos) == 2 and info["vivos_duplicados"] == 2 and info["vivos_nuevos"] == {"COL1": 1}
    assert [p.get("vivo", False) for p in partidos] == [False, True]
    assert len(info["vivos_todos"]) == 3
    assert len(datos.cargar_partidos_con_vivo(maestro, tmp_path / "no_existe.csv.gz")[0]) == 1  # sin capa: solo maestro
