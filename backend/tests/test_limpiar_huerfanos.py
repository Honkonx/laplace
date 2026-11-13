"""limpiar_huerfanos.py: retira solo los datos de prueba y las fechas basura conocidas, con respaldo verificado y archivo; idempotente; sin --aplicar no escribe."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def modulo():
    spec = importlib.util.spec_from_file_location("limpiar_huerfanos_prueba", RAIZ / "backend" / "scripts" / "limpiar_huerfanos.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def base(tmp_path):
    ruta = tmp_path / "t.db"
    c = sqlite3.connect(ruta)
    c.executescript("""
        create table jobs(job_id text, device_id_app text, match_id text, fecha_partido text);
        create table uso_diario_app(device_id text, fecha text, predicciones_usadas integer);
        create table partidos_dia(fecha text, match_id text);
        insert into jobs values('j1','verificacion-real','m1','2026-09-09'),('j2','verificacion-real','m2','2026-09-09'),
                               ('j3','dispositivo-real','m3','2026-09-09'),('j4','dispositivo-sin-usuario','m9','2026-09-09');
        insert into uso_diario_app values('verificacion-real','2026-09-09',12),('dispositivo-real','2026-09-09',3);
        insert into partidos_dia values('2026-11-10','a'),('20261110','b'),('2026--0-9-','c'),('2026--1-0-','d');
    """)
    c.commit()
    c.close()
    return ruta


def _contar(ruta, tabla):
    c = sqlite3.connect(ruta)
    n = c.execute(f"select count(*) from {tabla}").fetchone()[0]
    c.close()
    return n


def test_cuenta_solo_lo_conocido(modulo, base):
    c = sqlite3.connect(base)
    por = {g["tabla"]: g["filas"] for g in modulo.contar(c)}
    assert por == {"jobs": 2, "uso_diario_app": 1, "partidos_dia": 2}


def test_aplicar_respalda_archiva_y_borra_solo_eso(modulo, base, tmp_path):
    r = modulo.aplicar(base, tmp_path / "copias")
    assert r["quedan"] == 0 and r["retiradas"] == {"jobs": 2, "uso_diario_app": 1, "partidos_dia": 2}
    # lo que no es de prueba ni basura queda: incluidos los jobs de un dispositivo real y de uno sin usuario
    assert _contar(base, "jobs") == 2 and _contar(base, "uso_diario_app") == 1 and _contar(base, "partidos_dia") == 2
    # el respaldo es la base de antes, íntegra, y su huella coincide
    assert _contar(r["respaldo"], "jobs") == 4 and _contar(r["respaldo"], "partidos_dia") == 4
    assert len(r["sha256"]) == 64
    lineas = [json.loads(x) for x in Path(r["archivo"]).read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == 5 and {x["tabla"] for x in lineas} == {"jobs", "uso_diario_app", "partidos_dia"}
    assert any(x["fila"].get("fecha") == "2026--0-9-" for x in lineas)


def test_es_idempotente(modulo, base, tmp_path):
    modulo.aplicar(base, tmp_path / "copias")
    c = sqlite3.connect(base)
    assert sum(g["filas"] for g in modulo.contar(c)) == 0
    c.close()
    segunda = modulo.aplicar(base, tmp_path / "copias2")
    assert segunda["retiradas"] == {"jobs": 0, "uso_diario_app": 0, "partidos_dia": 0} and segunda["quedan"] == 0


def test_sin_aplicar_no_escribe_nada(modulo, base, tmp_path, monkeypatch, capsys):
    antes = base.read_bytes()
    monkeypatch.setattr("sys.argv", ["x", "--db", str(base), "--carpeta", str(tmp_path / "nada")])
    assert modulo.main() == 0
    assert base.read_bytes() == antes and not (tmp_path / "nada").exists()
    assert "simulación" in capsys.readouterr().out


def test_tablas_ausentes_no_rompen(modulo, tmp_path):
    ruta = tmp_path / "vacia.db"
    sqlite3.connect(ruta).close()
    c = sqlite3.connect(ruta)
    assert all(g["filas"] == 0 for g in modulo.contar(c))
