"""Instalación SIN modelo ni datos históricos propios (el caso del repo público): los trabajos programados no deben romperse ni tumbar el backend.

Regresión de la auditoría del 2026-11-09: `exportar_resultados_vivos.construir_resolver` lanzaba `SystemExit` sin artefacto, `except Exception` no lo atrapaba y el
trabajo del colector (02:30 y 12:30) lo dejaba escapar: un SystemExit dentro de una tarea de asyncio puede detener el bucle de eventos, o sea el backend entero.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from backend.api.ml import datos, job_reajuste
from backend.api.services import colector_resultados

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture()
def script_vivo():
    spec = importlib.util.spec_from_file_location("exportar_resultados_vivos_prueba", RAIZ / "backend" / "scripts" / "exportar_resultados_vivos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_sin_artefacto_el_resolver_lanza_una_excepcion_normal_no_un_systemexit(script_vivo):
    # El conftest aísla `ml/artefactos/`: aquí no hay modelo, como en una instalación nueva.
    assert not issubclass(script_vivo.SinArtefacto, (SystemExit, KeyboardInterrupt))
    with pytest.raises(script_vivo.SinArtefacto, match="Sin artefacto"):
        script_vivo.construir_resolver()


def test_en_la_linea_de_comandos_la_falta_de_artefacto_si_termina_con_el_mensaje(script_vivo, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["exportar_resultados_vivos.py", "--db", str(tmp_path / "no_importa.db")])
    monkeypatch.setattr(script_vivo, "exportar", lambda *a, **k: (_ for _ in ()).throw(script_vivo.SinArtefacto("Sin artefacto de prueba")))
    with pytest.raises(SystemExit, match="Sin artefacto de prueba"):
        script_vivo.main()


def test_exportar_la_capa_en_vivo_sin_modelo_no_lanza_y_no_cuenta_como_fallo():
    resultado = colector_resultados.exportar_capa_vivo()      # antes: SystemExit
    assert resultado["ok"] is True and resultado["exportado"] is False and "sin modelo" in resultado["detalle"]


def test_un_systemexit_dentro_de_la_exportacion_nunca_escapa_del_job(monkeypatch):
    from backend.api.services import modelo_historico

    falso = lambda: {"ligas": {}}   # noqa: E731 — parece que hay modelo...
    falso.cache_clear = lambda: None   # el conftest llama cache_clear() al terminar
    monkeypatch.setattr(modelo_historico, "_artefactos", falso)
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: (_ for _ in ()).throw(SystemExit("explota")))
    resultado = colector_resultados.exportar_capa_vivo()
    assert resultado["ok"] is False and resultado["exportado"] is False


def _corrida_que_falla(error: str):
    def correr(cmd, **_):
        if cmd[1] == "-c":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", error)
    return correr


def test_el_reajuste_sin_datos_propios_no_es_un_fallo_y_lo_explica(monkeypatch, tmp_path):
    monkeypatch.setattr(job_reajuste, "python_ml", lambda: "python")
    monkeypatch.setattr(datos, "RUTA_DATOS", tmp_path / "no_existe")
    r = job_reajuste.ejecutar_reajuste(ejecutar=_corrida_que_falla("FileNotFoundError: [Errno 2] No such file or directory: 'x'"))
    assert r["ok"] is True and r["reemplazado"] is False and "no aplica" in r["detalle"]


def test_un_filenotfound_con_datos_presentes_sigue_siendo_un_fallo_real(monkeypatch, tmp_path):
    monkeypatch.setattr(job_reajuste, "python_ml", lambda: "python")
    monkeypatch.setattr(datos, "RUTA_DATOS", tmp_path)       # la carpeta existe: el error NO es «faltan datos», no se oculta
    r = job_reajuste.ejecutar_reajuste(ejecutar=_corrida_que_falla("FileNotFoundError: [Errno 2] No such file or directory: 'x'"))
    assert r["ok"] is False and "FileNotFoundError" in r["detalle"]
