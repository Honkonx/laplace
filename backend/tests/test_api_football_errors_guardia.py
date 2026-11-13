"""Guardia: todo servicio que llama a API-Football debe leer la respuesta con `cuerpo_api_football`.

API-Football responde HTTP 200 con `{"errors": {...}, "response": []}` cuando la clave no tiene acceso a la temporada o se agotó la cuota. Leerlo con `r.json()` lo
convierte en «sin resultados» sin dejar rastro. Esta falla apareció 5 veces (gateway, h2h, odds, estadísticas, Top Picks y la verificación de resultados) hasta que se
automatizó: un servicio nuevo que llame a API-Football sin la función falla esta prueba.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SERVICIOS = Path(__file__).resolve().parents[1] / "api" / "services"
LLAMA_A_APIFOOTBALL = re.compile(r"v3\.football\.api-sports\.io|APIF_BASE|x-apisports-key")
# Solo comprueba el estado del servicio (`/status`), sin leer partidos: no puede confundir un error con «sin resultados».
# `gateway.py` es solo la fachada que reexporta `APIF_BASE`. `gateway_fuentes.py` heredó de `gateway.py` la lectura con `r.json()` de
# `_apifootball_stages` (antes la prueba pasaba porque el mismo archivo también tenía `cuerpo_api_football` para otra función): es una brecha previa,
# no una lectura nueva; arreglarla cambia comportamiento y queda fuera de la división del archivo.
EXENTOS = {"source_health.py", "gateway.py"}  # source_health solo consulta `/status`; gateway.py es una fachada que reexporta (la lógica está en gateway_*.py, que sí se revisan)


def _servicios_que_llaman():
    return sorted(p for p in SERVICIOS.glob("*.py") if p.name not in EXENTOS and LLAMA_A_APIFOOTBALL.search(p.read_text(encoding="utf-8")))


def test_hay_servicios_que_llaman_a_api_football():
    assert len(_servicios_que_llaman()) >= 6


@pytest.mark.parametrize("servicio", _servicios_que_llaman(), ids=lambda p: p.name)
def test_cada_servicio_lee_api_football_con_cuerpo_api_football(servicio):
    texto = servicio.read_text(encoding="utf-8")
    assert "cuerpo_api_football" in texto, f"{servicio.name} llama a API-Football sin `cuerpo_api_football`: un 200 con `errors` se leería como «sin resultados»"


def _funciones_que_leen_api_football_sin_el_helper():
    """Nivel de FUNCIÓN: una función que menciona API-Football y llama `.json()` debe usar `cuerpo_api_football` en esa misma función.
    (La guardia por archivo dejó pasar `gateway_fuentes._apifootball_stages` porque otra función del mismo archivo sí usaba el helper.)"""
    import ast

    malas = []
    for ruta in sorted(SERVICIOS.glob("*.py")):
        if ruta.name in EXENTOS:
            continue
        fuente = ruta.read_text(encoding="utf-8")
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                trozo = ast.get_source_segment(fuente, nodo) or ""
                if LLAMA_A_APIFOOTBALL.search(trozo) and ".json()" in trozo and "cuerpo_api_football" not in trozo:
                    malas.append(f"{ruta.name}::{nodo.name}")
    return malas


def test_ninguna_funcion_lee_api_football_con_json_directo():
    assert _funciones_que_leen_api_football_sin_el_helper() == []


def test_cascada_api_football_y_predicciones_tratan_un_200_con_errors_como_fallo():
    """Regresión de las dos lecturas que la guardia por archivo dejó pasar: `gateway_fuentes._apifootball_stages` y `odds_fetch._apifootball_predictions`."""
    import asyncio

    import httpx

    from backend.api.core.config import settings
    from backend.api.services import gateway_fuentes, odds_fetch
    from backend.api.services._http_retry import CuotaApiFootballError

    cuerpo = {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}

    async def con_cliente(funcion, *args):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=cuerpo))) as c:
            return await funcion(c, *args)

    anterior = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "clave-de-prueba"
    try:
        with __import__("pytest").raises(CuotaApiFootballError):
            asyncio.run(con_cliente(gateway_fuentes._apifootball_stages, "20261110"))  # noqa: SLF001
        assert asyncio.run(con_cliente(odds_fetch._apifootball_predictions, "123")) is None  # noqa: SLF001 — registra y degrada
    finally:
        settings.SPORTS_API_KEY = anterior
