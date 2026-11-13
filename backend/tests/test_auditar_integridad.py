"""auditar_integridad.py: cuenta huérfanos de las relaciones lógicas sin tocar la base (solo lectura)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def modulo():
    spec = importlib.util.spec_from_file_location("auditar_integridad_prueba", RAIZ / "backend" / "scripts" / "auditar_integridad.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def base(tmp_path):
    ruta = tmp_path / "t.db"
    c = sqlite3.connect(ruta)
    c.executescript("""
        create table usuarios(device_id text); create table partidos_dia(match_id text);
        create table jobs(device_id_app text, match_id text);
        insert into usuarios values('u1'); insert into partidos_dia values('m1');
        insert into jobs values('u1','m1'); insert into jobs values('fantasma','m1'); insert into jobs values('', 'm9'); insert into jobs values(NULL, 'm1');
    """)
    c.commit()
    c.close()
    return ruta


def test_cuenta_huerfanos_e_ignora_vacios_y_nulos(modulo, base):
    por = {f["relacion"]: f for f in modulo.auditar(base)}
    d = por["jobs.device_id_app → usuarios.device_id"]
    assert (d["con_valor"], d["huerfanos"], d["porcentaje"]) == (2, 1, 50.0)
    m = por["jobs.match_id → partidos_dia.match_id"]
    assert (m["con_valor"], m["huerfanos"], m["informativa"]) == (4, 1, True)   # partidos_dia se purga: informativa, no cuenta como aviso
    assert d["informativa"] is False


def test_omite_relaciones_cuyas_tablas_no_existen(modulo, base):
    nombres = {f["relacion"] for f in modulo.auditar(base)}
    assert all(not n.startswith(("agent_", "uso_diario_app", "analisis_comparativo")) for n in nombres)


def test_es_solo_lectura(modulo, base):
    antes = base.read_bytes()
    modulo.auditar(base)
    assert base.read_bytes() == antes
    with pytest.raises(sqlite3.OperationalError):
        c = sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True)
        c.execute("insert into usuarios values('x')")


def test_el_modo_estricto_sale_con_1_si_hay_huerfanos(modulo, base, monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", "--estricto", "--db", str(base)])
    assert modulo.main() == 1
    monkeypatch.setattr("sys.argv", ["x", "--db", str(base)])
    assert modulo.main() == 0


def test_resumen_dice_cuando_no_hay_huerfanos(modulo):
    assert "sin huérfanos" in modulo.resumen([{"relacion": "a", "con_valor": 3, "huerfanos": 0, "porcentaje": 0.0}])


def test_los_huerfanos_informativos_no_cuentan_ni_en_el_resumen_ni_en_estricto(modulo, tmp_path, monkeypatch):
    assert "sin huérfanos" in modulo.resumen([{"relacion": "a", "con_valor": 3, "huerfanos": 2, "porcentaje": 66.7, "informativa": True}])
    ruta = tmp_path / "t.db"
    c = sqlite3.connect(ruta)
    c.executescript("create table partidos_dia(match_id text); create table jobs(device_id_app text, match_id text); insert into jobs values(NULL,'purgado');")
    c.commit()
    c.close()
    monkeypatch.setattr("sys.argv", ["x", "--estricto", "--db", str(ruta)])
    assert modulo.main() == 0    # el único huérfano es por retención: --estricto no falla
