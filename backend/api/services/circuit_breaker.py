"""services/circuit_breaker.py — circuit breaker simple in-memory para fuentes externas.

Contexto real (pedido de esta ronda, 2026-09-10): `gateway.py`, `bsd_predictions.py` y
`odds_fetch.py` ya tienen retry/backoff **individual por request** (ver `_http_retry.py` —
un reintento con `Retry-After` ante 429). Lo que faltaba: si una fuente entera empieza a
fallar en cascada (ej. api-football caído, no solo rate-limited), cada request nueva reintenta
igual, sin memoria de que esa fuente viene fallando — cada partido del día repite el mismo
timeout completo contra una fuente que ya sabemos que no responde, en vez de fallar rápido y
dejar que el resto de la cascada (`gateway.obtener_fixtures_cascada`) siga con lo que ya tiene.

Estados (patrón circuit breaker clásico, Fowler/Nygard):
  - CLOSED: comportamiento normal, todas las llamadas pasan.
  - OPEN: tras `umbral_fallos` fallos CONSECUTIVOS, se abre — ninguna llamada nueva se
    intenta (`permite_llamada()` devuelve False) hasta que pase `timeout_recuperacion_segundos`.
  - HALF_OPEN: pasado el timeout, se permite UNA llamada de prueba — si tiene éxito, vuelve a
    CLOSED (contador de fallos reseteado); si falla, vuelve a OPEN (nuevo timeout completo).

Estado 100% in-memory, por proceso — mismo criterio que `gateway._fixtures_locks` (el backend
corre en un solo proceso/event loop, confirmado por auditoría previa de esta sesión; no hace
falta un breaker distribuido tipo Redis para esto hoy). Un registro global por nombre de fuente
(`obtener_circuit_breaker("bsd")`/`obtener_circuit_breaker("api-football")`) para que todas las
funciones de `gateway.py` que llaman a la misma fuente compartan el mismo estado — el breaker
representa la salud de LA FUENTE, no de una función puntual.
"""
from __future__ import annotations

import logging
import time
from enum import Enum

log = logging.getLogger("laplace.circuit_breaker")

# Defaults razonables, no configurables por .env todavía (YAGNI — ver
# `.claude/rules/clean-code-principles.md`: no agregar una superficie de configuración nueva
# sin un caso real que la necesite hoy). `obtener_circuit_breaker(..., umbral_fallos=...,
# timeout_recuperacion_segundos=...)` permite overridear por caller/test sin tocar esto.
UMBRAL_FALLOS_DEFAULT = 5
TIMEOUT_RECUPERACION_SEGUNDOS_DEFAULT = 60.0


class EstadoCircuitBreaker(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerAbiertoError(Exception):
    """La fuente `fuente` tiene el circuit breaker abierto — no se intentó ninguna request HTTP.
    Los callers de `gateway.py` la tratan igual que cualquier otra excepción de fuente (la
    cascada de fallback ya captura `Exception` genérico y sigue con la siguiente fuente)."""

    def __init__(self, fuente: str):
        self.fuente = fuente
        super().__init__(f"circuit breaker abierto para fuente={fuente}")


class CircuitBreaker:
    """Un breaker por fuente externa. No es thread-safe con hilos reales (no hace falta: el
    backend es async de un solo hilo) pero sí seguro entre corutinas concurrentes del mismo
    event loop — las transiciones son operaciones simples sobre atributos, sin await de por
    medio, así que no hay punto de interrupción a mitad de una transición."""

    def __init__(
        self,
        nombre: str,
        *,
        umbral_fallos: int = UMBRAL_FALLOS_DEFAULT,
        timeout_recuperacion_segundos: float = TIMEOUT_RECUPERACION_SEGUNDOS_DEFAULT,
    ):
        self.nombre = nombre
        self.umbral_fallos = umbral_fallos
        self.timeout_recuperacion_segundos = timeout_recuperacion_segundos
        self._estado = EstadoCircuitBreaker.CLOSED
        self._fallos_consecutivos = 0
        self._abierto_desde: float | None = None

    @property
    def estado(self) -> EstadoCircuitBreaker:
        return self._estado

    def permite_llamada(self) -> bool:
        """Chequear ANTES de intentar la request HTTP real. En OPEN, hace la transición a
        HALF_OPEN por su cuenta si ya pasó el timeout de recuperación (sin esto, el breaker se
        quedaría abierto para siempre — nada más lo volvería a cerrar)."""
        if self._estado == EstadoCircuitBreaker.CLOSED:
            return True
        if self._estado == EstadoCircuitBreaker.OPEN:
            si_paso_timeout = (
                self._abierto_desde is not None
                and (time.monotonic() - self._abierto_desde) >= self.timeout_recuperacion_segundos
            )
            if si_paso_timeout:
                self._estado = EstadoCircuitBreaker.HALF_OPEN
                log.info(
                    "circuit breaker fuente=%s pasa a HALF_OPEN (timeout de recuperación de %.0fs cumplido) "
                    "— próxima llamada es de prueba",
                    self.nombre, self.timeout_recuperacion_segundos,
                )
                return True
            return False
        return True  # HALF_OPEN: se permite la única llamada de prueba

    def registrar_exito(self) -> None:
        if self._estado != EstadoCircuitBreaker.CLOSED:
            log.info("circuit breaker fuente=%s se cierra (llamada de prueba exitosa)", self.nombre)
        self._estado = EstadoCircuitBreaker.CLOSED
        self._fallos_consecutivos = 0
        self._abierto_desde = None

    def registrar_fallo(self) -> None:
        if self._estado == EstadoCircuitBreaker.HALF_OPEN:
            # La llamada de prueba falló — vuelve a OPEN con un timeout completo nuevo, sin
            # necesidad de volver a acumular `umbral_fallos` fallos desde cero.
            log.warning(
                "circuit breaker fuente=%s vuelve a OPEN (la llamada de prueba en HALF_OPEN falló)",
                self.nombre,
            )
            self._estado = EstadoCircuitBreaker.OPEN
            self._abierto_desde = time.monotonic()
            return

        self._fallos_consecutivos += 1
        if self._fallos_consecutivos >= self.umbral_fallos:
            self._estado = EstadoCircuitBreaker.OPEN
            self._abierto_desde = time.monotonic()
            log.warning(
                "circuit breaker fuente=%s se ABRE tras %d fallos consecutivos — próximos %.0fs se "
                "saltan sin intentar la request HTTP",
                self.nombre, self._fallos_consecutivos, self.timeout_recuperacion_segundos,
            )


_registro: dict[str, CircuitBreaker] = {}


def obtener_circuit_breaker(
    nombre: str,
    *,
    umbral_fallos: int = UMBRAL_FALLOS_DEFAULT,
    timeout_recuperacion_segundos: float = TIMEOUT_RECUPERACION_SEGUNDOS_DEFAULT,
) -> CircuitBreaker:
    """Devuelve el breaker de `nombre`, creándolo la primera vez. Llamadas siguientes con el
    mismo `nombre` devuelven la MISMA instancia (los kwargs solo aplican en la creación) —
    intencional: todas las funciones de `gateway.py` que hablan con "bsd" comparten un único
    breaker, así un fallo detectado en `enriquecer_bsd` también salta la próxima llamada de
    `_bsd_stages`, y viceversa."""
    breaker = _registro.get(nombre)
    if breaker is None:
        breaker = CircuitBreaker(
            nombre, umbral_fallos=umbral_fallos, timeout_recuperacion_segundos=timeout_recuperacion_segundos
        )
        _registro[nombre] = breaker
    return breaker


def resetear_todos() -> None:
    """Solo para tests — limpia el registro global para que un test no herede el estado
    (OPEN/HALF_OPEN) que dejó otro test anterior. Ver fixture autouse en `conftest.py`."""
    _registro.clear()
