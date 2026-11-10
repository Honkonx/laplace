"""test_http_retry.py — manejo de 429/Retry-After compartido por los módulos de fetch
(gateway.py, odds_fetch.py, standings_fetch.py, h2h_fetch.py, team_stats_fetch.py).

Hallazgo real de la auditoría 2026-09-09: ninguno de esos módulos leía `Retry-After` ni
reintentaba un 429 — caía directo al siguiente fallback de la cascada. Estos tests prueban el
helper compartido `_http_retry.get_con_reintento_429` de forma aislada (headers `Retry-After:
"0"` para no bloquear la suite con sleeps reales)."""
from __future__ import annotations

import asyncio
import logging

import httpx

from backend.api.services._http_retry import ESPERA_MAXIMA_SEGUNDOS, _segundos_retry_after, get_con_reintento_429


def test_segundos_retry_after_respeta_header():
    assert _segundos_retry_after("2") == 2.0


def test_segundos_retry_after_topea_al_maximo():
    assert _segundos_retry_after("120") == ESPERA_MAXIMA_SEGUNDOS


def test_segundos_retry_after_sin_header_usa_default_corto():
    assert _segundos_retry_after(None) == 1.0


def test_segundos_retry_after_valor_invalido_usa_default():
    assert _segundos_retry_after("no-numerico") == 1.0


def test_reintenta_una_vez_tras_429_y_devuelve_200():
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_con_reintento_429(
                client, "https://api.example.com/x", log=logging.getLogger("test"), fuente="test-fuente"
            )

    r = asyncio.run(_run())

    assert llamadas["n"] == 2, "debe haber reintentado exactamente una vez tras el 429"
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_429_persistente_no_reintenta_mas_de_una_vez():
    """Si el 429 persiste tras el único reintento, el helper devuelve esa respuesta 429 tal
    cual (no reintenta infinitamente) — el caller sigue llamando raise_for_status() y cae al
    siguiente fallback de la cascada normal, mismo comportamiento de antes de este cambio."""
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_con_reintento_429(
                client, "https://api.example.com/x", log=logging.getLogger("test"), fuente="test-fuente"
            )

    r = asyncio.run(_run())

    assert llamadas["n"] == 2, "solo debe reintentar UNA vez, no repetir indefinidamente"
    assert r.status_code == 429


def test_sin_429_no_reintenta():
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(200, json={"ok": True})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_con_reintento_429(
                client, "https://api.example.com/x", log=logging.getLogger("test"), fuente="test-fuente"
            )

    r = asyncio.run(_run())

    assert llamadas["n"] == 1
    assert r.status_code == 200


def test_429_logea_en_warning_no_en_debug(caplog):
    """Requisito explícito: un 429 debe quedar visible en producción (nivel warning), no
    silenciado en debug — antes de este helper, varios `except` de estos módulos solo
    dejaban rastro en `debug`."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_con_reintento_429(
                client, "https://api.example.com/x", log=logging.getLogger("test.http_retry"), fuente="test-fuente"
            )

    with caplog.at_level(logging.WARNING, logger="test.http_retry"):
        asyncio.run(_run())

    mensajes_429 = [r.message for r in caplog.records if "429" in r.message]
    assert len(mensajes_429) >= 1
    assert all(r.levelno == logging.WARNING for r in caplog.records if "429" in r.message)


def test_limitador_de_api_football_espera_cuando_la_ventana_esta_llena(monkeypatch):
    """Plan gratis: 10 peticiones/min. Con la ventana llena el turno espera (con tope) en vez de provocar un 429."""
    import asyncio
    import time

    from backend.api.services import _http_retry

    monkeypatch.setattr(_http_retry, "LIMITE_API_FOOTBALL_POR_MINUTO", 2)
    monkeypatch.setattr(_http_retry, "ESPERA_MAXIMA_LIMITADOR_SEGUNDOS", 0.3)
    _http_retry._ventana_api_football.clear()

    async def _run():
        inicio = time.monotonic()
        for _ in range(3):
            await _http_retry._esperar_turno_api_football()
        return time.monotonic() - inicio

    transcurrido = asyncio.run(_run())
    assert 0.25 <= transcurrido < 2.0  # el tercer turno esperó hasta el tope y siguió


def test_cuerpo_api_football_con_errors_es_un_fallo_no_una_lista_vacia():
    import httpx
    import pytest

    from backend.api.services._http_retry import CuotaApiFootballError, cuerpo_api_football

    ok = httpx.Response(200, json={"errors": [], "response": [1]})
    assert cuerpo_api_football(ok)["response"] == [1]
    malo = httpx.Response(200, json={"errors": {"requests": "limit reached"}, "response": []})
    with pytest.raises(CuotaApiFootballError):
        cuerpo_api_football(malo)
