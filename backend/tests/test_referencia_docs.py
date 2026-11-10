"""Las referencias técnicas de `docs/backend/referencia/` se generan del código: si cambia una ruta, una tabla, un script o un trabajo programado y no se regenera, esta prueba falla.

Para arreglarla: `python backend/scripts/generar_referencia_docs.py`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def generador():
    spec = importlib.util.spec_from_file_location("generar_referencia_docs_prueba", RAIZ / "backend" / "scripts" / "generar_referencia_docs.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_las_referencias_tecnicas_estan_al_dia(generador):
    for nombre, esperado in generador.construir().items():
        archivo = RAIZ / "docs" / "backend" / "referencia" / nombre
        assert archivo.exists(), f"falta {nombre}: corre python backend/scripts/generar_referencia_docs.py"
        assert archivo.read_bytes().decode("utf-8").replace("\r\n", "\n") == esperado, f"{nombre} está desactualizado: corre python backend/scripts/generar_referencia_docs.py"


def test_la_salida_es_determinista_y_sin_datos_de_la_maquina(generador):
    primera, segunda = generador.construir(), generador.construir()
    assert primera == segunda
    for nombre, texto in primera.items():
        assert "C:\\Users" not in texto and "/home/" not in texto, nombre


def test_la_referencia_de_la_api_cubre_todas_las_rutas_y_dice_quien_puede_llamarlas(generador):
    from backend.api.main import app

    texto = generador.referencia_api()
    rutas = {r.path for r in app.routes if hasattr(r, "dependant") and getattr(r, "include_in_schema", True)}
    assert all(f"`{ruta}`" in texto for ruta in rutas)
    assert "admin (JWT con rol admin)" in texto and "público" in texto and "app Android" in texto


def test_la_referencia_de_trabajos_lista_todos_los_trabajos_del_planificador(generador):
    texto = generador.referencia_jobs()
    fuente = (RAIZ / "backend" / "api" / "main.py").read_text(encoding="utf-8")
    assert texto.count("| `") - 0 >= fuente.count("add_job(") - 1
    for id_ in ("wfd_top_picks", "colector_resultados", "reajuste_modelos", "purga_datos_viejos"):
        assert f"`{id_}`" in texto


def test_la_referencia_de_scripts_no_lista_los_scripts_de_desarrollo(generador):
    texto = generador.referencia_scripts()
    assert "doctor.py" in texto and "create_admin.py" in texto
    assert "qa_agent" not in texto and "sandbox_" not in texto and "benchmark_" not in texto
