"""test_circuit_breaker.py — `services/circuit_breaker.py`, unitario puro (sin red) + su
integración real con `services/gateway.py` contra fallos consecutivos simulados con
`httpx.MockTransport` (mismo patrón que `test_gateway.py`).

`conftest.py::_resetear_estado_global_entre_tests` (autouse) limpia el registro global de
breakers antes/después de cada test — evita que un test contamine el siguiente."""
from __future__ import annotations

import asyncio
import time

import httpx

from backend.api.core.config import settings
from backend.api.services import gateway
from backend.api.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerAbiertoError,
    EstadoCircuitBreaker,
    obtener_circuit_breaker,
    resetear_todos,
)


def test_arranca_closed_y_permite_llamadas():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=3, timeout_recuperacion_segundos=60)
    assert breaker.estado == EstadoCircuitBreaker.CLOSED
    assert breaker.permite_llamada() is True


def test_se_abre_tras_alcanzar_el_umbral_de_fallos_consecutivos():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=3, timeout_recuperacion_segundos=60)
    breaker.registrar_fallo()
    breaker.registrar_fallo()
    assert breaker.estado == EstadoCircuitBreaker.CLOSED  # todavía no llegó al umbral
    breaker.registrar_fallo()
    assert breaker.estado == EstadoCircuitBreaker.OPEN
    assert breaker.permite_llamada() is False


def test_exito_antes_del_umbral_resetea_el_contador_de_fallos():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=3, timeout_recuperacion_segundos=60)
    breaker.registrar_fallo()
    breaker.registrar_fallo()
    breaker.registrar_exito()
    breaker.registrar_fallo()
    breaker.registrar_fallo()
    assert breaker.estado == EstadoCircuitBreaker.CLOSED  # el éxito cortó la racha, no llegó a 3 seguidos


def test_pasa_a_half_open_tras_el_timeout_y_permite_una_llamada_de_prueba():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=1, timeout_recuperacion_segundos=0.05)
    breaker.registrar_fallo()
    assert breaker.estado == EstadoCircuitBreaker.OPEN
    assert breaker.permite_llamada() is False  # todavía dentro del timeout

    time.sleep(0.06)
    assert breaker.permite_llamada() is True
    assert breaker.estado == EstadoCircuitBreaker.HALF_OPEN


def test_half_open_exitoso_cierra_el_breaker():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=1, timeout_recuperacion_segundos=0.05)
    breaker.registrar_fallo()
    time.sleep(0.06)
    breaker.permite_llamada()  # transición a HALF_OPEN
    breaker.registrar_exito()
    assert breaker.estado == EstadoCircuitBreaker.CLOSED
    assert breaker.permite_llamada() is True


def test_half_open_fallido_vuelve_a_open():
    breaker = CircuitBreaker("test-fuente", umbral_fallos=1, timeout_recuperacion_segundos=0.05)
    breaker.registrar_fallo()
    time.sleep(0.06)
    breaker.permite_llamada()  # transición a HALF_OPEN
    breaker.registrar_fallo()
    assert breaker.estado == EstadoCircuitBreaker.OPEN
    assert breaker.permite_llamada() is False


def test_obtener_circuit_breaker_devuelve_la_misma_instancia_por_nombre():
    b1 = obtener_circuit_breaker("bsd")
    b2 = obtener_circuit_breaker("bsd")
    assert b1 is b2


def test_resetear_todos_limpia_el_registro():
    b1 = obtener_circuit_breaker("bsd")
    b1.registrar_fallo()
    resetear_todos()
    b2 = obtener_circuit_breaker("bsd")
    assert b2 is not b1
    assert b2.estado == EstadoCircuitBreaker.CLOSED


# ─── Integración real con gateway.py (BSD/api-football) ───────────────────────


def test_apifootball_stages_abre_el_breaker_tras_fallos_consecutivos_y_luego_falla_rapido(db_session):
    """3 fallos reales (500) de api-football -> el breaker (umbral 3 acá vía instanciación
    directa del registro) se abre; la 4ta llamada NO debe ni siquiera intentar la request
    HTTP — se confirma contando cuántas veces el handler del mock fue invocado."""
    original = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "fake-key"
    llamadas_reales = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas_reales["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    # Umbral bajo (2) para no tener que simular 5 fallos reales en el test.
    obtener_circuit_breaker("api-football", umbral_fallos=2, timeout_recuperacion_segundos=60)

    try:
        async def _run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                for _ in range(2):
                    try:
                        await gateway._apifootball_stages(client, "20260601")
                    except Exception:
                        pass
                # 3ra llamada: el breaker ya debería estar OPEN
                try:
                    await gateway._apifootball_stages(client, "20260601")
                    lanzo_breaker = False
                except CircuitBreakerAbiertoError:
                    lanzo_breaker = True
                except Exception:
                    lanzo_breaker = False
                return lanzo_breaker

        lanzo_breaker = asyncio.run(_run())

        assert lanzo_breaker is True
        assert llamadas_reales["n"] == 2  # la 3ra NUNCA llegó a hacer la request HTTP real
    finally:
        settings.SPORTS_API_KEY = original


def test_bsd_stages_abre_el_breaker_tras_fallos_consecutivos(db_session):
    original = settings.BSD_API_KEY
    settings.BSD_API_KEY = "fake-key"
    llamadas_reales = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas_reales["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    obtener_circuit_breaker("bsd", umbral_fallos=2, timeout_recuperacion_segundos=60)

    try:
        async def _run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                for _ in range(2):
                    try:
                        await gateway._bsd_stages(client, "20260601")
                    except Exception:
                        pass
                try:
                    await gateway._bsd_stages(client, "20260601")
                    return False
                except CircuitBreakerAbiertoError:
                    return True
                except Exception:
                    return False

        lanzo_breaker = asyncio.run(_run())

        assert lanzo_breaker is True
        assert llamadas_reales["n"] == 2
    finally:
        settings.BSD_API_KEY = original


def test_cascada_completa_sigue_funcionando_con_breaker_abierto_en_una_fuente(db_session):
    """El objetivo del breaker es no bloquear el resto del sistema — con 'bsd' abierto, la
    cascada de `obtener_fixtures_cascada` debe seguir agotando las demás fuentes (livescore6,
    api-football) y devolver ([], 'none') sin explotar, exactamente igual que hoy sin
    breaker (ver `test_gateway.py::test_cascada_sin_api_keys_ni_cache_devuelve_none`)."""
    breaker_bsd = obtener_circuit_breaker("bsd", umbral_fallos=1, timeout_recuperacion_segundos=60)
    breaker_bsd.registrar_fallo()  # ya abierto, sin API keys configuradas en el resto (default test)
    assert breaker_bsd.permite_llamada() is False

    async def _run():
        async with httpx.AsyncClient() as client:
            return await gateway.obtener_fixtures_cascada(db_session, client, "20991231")

    stages, fuente = asyncio.run(_run())
    assert stages == []
    assert fuente == "none"
