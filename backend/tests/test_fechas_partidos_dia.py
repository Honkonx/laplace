"""Fechas basura en `partidos_dia` (auditoría 2026-10-06): validación en esquema y repo, y script
de diagnóstico/reparación (dry-run por defecto, nunca DELETE)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pydantic
import pytest

from backend.api.db import partidos_repo
from backend.api.schemas.app_gateway import GuardarPartidosParams, JuegosParams, PrediccionParams
from backend.api.services.fechas_bd import FechaBdInvalida, normalizar_fecha_bd

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reparar_fechas_partidos_dia.py"


def _cargar_script():
    spec = importlib.util.spec_from_file_location("reparar_fechas_partidos_dia", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize("valida", ["2026-09-27", "20260927", " 2026-09-27 "])
def test_normalizar_acepta_iso_y_compacta(valida):
    assert normalizar_fecha_bd(valida) == "2026-09-27"


@pytest.mark.parametrize("basura", ["2026--0-9-", "2026--1-0-", "2026-02-30", "", "hoy", "2026-9-7", None])
def test_normalizar_rechaza_basura(basura):
    with pytest.raises(FechaBdInvalida):
        normalizar_fecha_bd(basura)


def test_repo_rechaza_fecha_basura_y_no_guarda(db_session):
    from backend.api.models.partidos import PartidoDia

    with pytest.raises(FechaBdInvalida):
        partidos_repo.guardar_ligas_cache(db_session, "2026--0-9-", [{"match_id": "1", "local": "A", "visitante": "B"}])
    with pytest.raises(FechaBdInvalida):
        partidos_repo.guardar_partidos_dia(db_session, "2026--0-9-", [{"match_id": "1"}])
    assert db_session.query(PartidoDia).count() == 0
    assert partidos_repo.guardar_ligas_cache(db_session, "20260927", [{"match_id": "1", "local": "A", "visitante": "B"}]) == 1
    assert db_session.query(PartidoDia).one().fecha == "2026-09-27"


def test_esquema_rechaza_fecha_basura_pero_tolera_vacia_y_formatos_validos():
    assert JuegosParams(date="").date == ""
    assert JuegosParams(date="2026-09-27").date == "2026-09-27"
    assert GuardarPartidosParams(fecha="20260927").fecha == "20260927"
    for modelo, campo in ((JuegosParams, "date"), (GuardarPartidosParams, "fecha")):
        with pytest.raises(pydantic.ValidationError):
            modelo(**{campo: "2026--0-9-"})
    with pytest.raises(pydantic.ValidationError):
        PrediccionParams(match_id="1", date="2026-13-40")


def _bd_con_filas(ruta: Path) -> None:
    conn = sqlite3.connect(ruta)
    conn.execute(
        "CREATE TABLE partidos_dia (fecha TEXT, match_id TEXT, local TEXT, visitante TEXT, kick_off_utc TEXT, "
        "cache_invalidado INTEGER DEFAULT 0, PRIMARY KEY (fecha, match_id))"
    )
    conn.executemany(
        "INSERT INTO partidos_dia VALUES (?,?,?,?,?,?)",
        [
            ("2026-09-27", "10", "A", "B", "2026-09-27T20:00:00", 0),     # válida
            ("2026--0-9-", "10", "A", "B", "", 0),                         # duplicado de válida
            ("2026--0-9-", "20", "C", "D", "2026-09-28T03:30:00", 0),     # reparable: 00:30 Chile del 28 (UTC-3)
            ("2026--1-0-", "30", "E", "F", "", 0),                         # irreparable
            ("2026--1-0-", "31", "G", "H", "", 1),                         # irreparable ya en cuarentena
        ],
    )
    conn.commit()
    conn.close()


def test_script_dry_run_no_escribe_y_clasifica(tmp_path):
    mod = _cargar_script()
    ruta = tmp_path / "t.db"
    _bd_con_filas(ruta)
    conn = mod._abrir(ruta, escritura=False)
    clasif = mod.clasificar_filas(conn)
    por_id = {f["match_id"]: f for f in clasif}
    assert por_id["10"]["clase"] == "duplicado_de_fila_valida"
    assert por_id["20"]["clase"] == "reparable_por_kickoff" and por_id["20"]["fecha_destino"] == "2026-09-28"
    assert por_id["30"]["clase"] == "irreparable"
    resumen = mod.resumir(clasif)
    assert resumen["filas_invalidas"] == 4 and resumen["filas_que_cambiaria_aplicar"] == 3
    with pytest.raises(sqlite3.OperationalError):  # abierta en solo lectura
        conn.execute("UPDATE partidos_dia SET cache_invalidado=1")
    conn.close()


def test_script_main_dry_run_por_defecto_y_aplicar_exige_confirmo(tmp_path, capsys):
    mod = _cargar_script()
    ruta = tmp_path / "t.db"
    _bd_con_filas(ruta)
    assert mod.main(["--db", str(ruta)]) == 0
    assert '"modo": "dry-run"' in capsys.readouterr().out
    assert mod.main(["--db", str(ruta), "--aplicar"]) == 2
    conn = sqlite3.connect(ruta)
    assert conn.execute("SELECT COUNT(*) FROM partidos_dia WHERE cache_invalidado=1").fetchone()[0] == 1
    conn.close()


def test_script_aplicar_es_idempotente_y_nunca_borra(tmp_path):
    mod = _cargar_script()
    ruta = tmp_path / "t.db"
    _bd_con_filas(ruta)
    assert mod.main(["--db", str(ruta), "--aplicar", "--confirmo"]) == 0
    conn = sqlite3.connect(ruta)
    assert conn.execute("SELECT COUNT(*) FROM partidos_dia").fetchone()[0] == 5  # nada borrado
    assert conn.execute("SELECT fecha FROM partidos_dia WHERE match_id='20'").fetchone()[0] == "2026-09-28"
    assert conn.execute("SELECT cache_invalidado FROM partidos_dia WHERE match_id='30'").fetchone()[0] == 1
    conn.close()
    conn2 = mod._abrir(ruta, escritura=False)
    resumen = mod.resumir(mod.clasificar_filas(conn2))
    assert resumen["filas_que_cambiaria_aplicar"] == 0  # segunda pasada: nada que hacer
    conn2.close()


def test_gateway_convierte_yyyymmdd_a_iso_y_rechaza_basura():
    from backend.api.services import gateway
    from backend.api.services.fechas_bd import FechaBdInvalida

    assert gateway._yyyymmdd_to_bd("20260927") == "2026-09-27"
    assert gateway._yyyymmdd_to_bd("2026-09-27") == "2026-09-27"
    with pytest.raises(FechaBdInvalida):
        gateway._yyyymmdd_to_bd("2026--0-9-")
