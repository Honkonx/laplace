"""Registro de piezas del agente con comprobación de salud y circuit breaker.

Diseño: el plan de mejoras (repo de trabajo) §2 (meta MA-10).
Solo librería estándar: vive dentro del proceso del agente.

Una "pieza" es un componente que el agente usa (bot, modelo, IA, laboratorio,
conocimiento). El breaker evita pagar el plazo completo en cada mensaje cuando
una pieza está caída: cerrado -> (3 fallos en 60 s) -> abierto 30 s -> semiabierto
(una sola llamada de prueba) -> cerrado si responde, abierto de nuevo si falla.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

TIPOS_PIEZA = ("bot", "modelo", "ia", "laboratorio", "conocimiento")

EWMA_ALFA = 0.3
VENTANA_TASA_ERROR_SEGUNDOS = 300.0
UMBRAL_DEGRADADA = 0.2
MAX_LARGO_MOTIVO = 200


class EstadoPieza:
    DESCONOCIDA = "desconocida"
    SANA = "sana"
    DEGRADADA = "degradada"
    CAIDA = "caida"


class EstadoBreaker:
    CERRADO = "cerrado"
    ABIERTO = "abierto"
    SEMIABIERTO = "semiabierto"


_RUTA_WINDOWS = re.compile(r"[A-Za-z]:\\[^\s'\"]*")
_RUTA_POSIX = re.compile(r"(?<![\w:/])/(?:home|root|Users|data|var|tmp)/[^\s'\"]*")
_TOKEN_LARGO = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def limpiar_motivo(motivo: Any) -> str:
    """Acorta el motivo y quita rutas locales y cadenas que parezcan claves."""
    texto = str(motivo or "")
    texto = _RUTA_WINDOWS.sub("<ruta>", texto)
    texto = _RUTA_POSIX.sub("<ruta>", texto)
    texto = _TOKEN_LARGO.sub("<oculto>", texto)
    return texto[:MAX_LARGO_MOTIVO]


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CircuitBreaker:
    """Breaker de una pieza con reloj monotónico inyectable."""

    def __init__(
        self,
        reloj: Callable[[], float] = time.monotonic,
        fallos_para_abrir: int = 3,
        ventana_segundos: float = 60.0,
        espera_segundos: float = 30.0,
    ) -> None:
        self._reloj = reloj
        self.fallos_para_abrir = fallos_para_abrir
        self.ventana_segundos = ventana_segundos
        self.espera_segundos = espera_segundos
        self.estado = EstadoBreaker.CERRADO
        self._fallos: deque[float] = deque()
        self._abierto_hasta = 0.0
        self._prueba_en_curso = False

    def permitir(self) -> bool:
        if self.estado == EstadoBreaker.CERRADO:
            return True
        if self.estado == EstadoBreaker.ABIERTO:
            if self._reloj() < self._abierto_hasta:
                return False
            self.estado = EstadoBreaker.SEMIABIERTO
            self._prueba_en_curso = True
            return True
        # Semiabierto: solo una llamada de prueba a la vez.
        if self._prueba_en_curso:
            return False
        self._prueba_en_curso = True
        return True

    def exito(self) -> None:
        if self.estado == EstadoBreaker.SEMIABIERTO:
            self.estado = EstadoBreaker.CERRADO
            self._prueba_en_curso = False
            self._fallos.clear()
        elif self.estado == EstadoBreaker.CERRADO:
            self._fallos.clear()

    def fallo(self) -> None:
        ahora = self._reloj()
        if self.estado == EstadoBreaker.SEMIABIERTO:
            self._abrir(ahora)
            return
        if self.estado == EstadoBreaker.ABIERTO:
            return
        self._fallos.append(ahora)
        while self._fallos and ahora - self._fallos[0] > self.ventana_segundos:
            self._fallos.popleft()
        if len(self._fallos) >= self.fallos_para_abrir:
            self._abrir(ahora)

    def liberar_prueba(self) -> None:
        """Libera la llamada de prueba si se canceló sin resultado."""
        self._prueba_en_curso = False

    def _abrir(self, ahora: float) -> None:
        self.estado = EstadoBreaker.ABIERTO
        self._abierto_hasta = ahora + self.espera_segundos
        self._prueba_en_curso = False
        self._fallos.clear()


@dataclass
class Pieza:
    nombre: str
    tipo: str
    breaker: CircuitBreaker
    comprobar: Callable[[], Awaitable[Any]] | None = None
    ultima_comprobacion: str | None = None
    latencia_ewma_ms: float | None = None
    motivo: str = ""
    eventos: deque = field(default_factory=deque)  # (t, ok)
    tuvo_datos: bool = False


class RegistroPiezas:
    def __init__(
        self,
        reloj: Callable[[], float] = time.monotonic,
        alertar: Callable[[dict], None] | None = None,
        fallos_para_abrir: int = 3,
        ventana_segundos: float = 60.0,
        espera_segundos: float = 30.0,
    ) -> None:
        self._reloj = reloj
        self._alertar = alertar
        self._cfg = (fallos_para_abrir, ventana_segundos, espera_segundos)
        self._piezas: dict[str, Pieza] = {}
        self._ultimo_estado: dict[str, str] = {}

    # --- alta y consulta -------------------------------------------------
    def registrar(
        self,
        nombre: str,
        tipo: str,
        comprobar: Callable[[], Awaitable[Any]] | None = None,
    ) -> Pieza:
        if tipo not in TIPOS_PIEZA:
            raise ValueError(f"tipo de pieza desconocido: {tipo}")
        breaker = CircuitBreaker(self._reloj, *self._cfg)
        pieza = Pieza(nombre=nombre, tipo=tipo, breaker=breaker, comprobar=comprobar)
        self._piezas[nombre] = pieza
        self._ultimo_estado[nombre] = EstadoPieza.DESCONOCIDA
        return pieza

    def registrada(self, nombre: str) -> bool:
        return nombre in self._piezas

    def estado(self, nombre: str) -> str:
        pieza = self._piezas.get(nombre)
        if pieza is None:
            return EstadoPieza.DESCONOCIDA
        return self._calcular_estado(pieza)

    def _tasa_error(self, pieza: Pieza) -> float:
        ahora = self._reloj()
        while pieza.eventos and ahora - pieza.eventos[0][0] > VENTANA_TASA_ERROR_SEGUNDOS:
            pieza.eventos.popleft()
        if not pieza.eventos:
            return 0.0
        errores = sum(1 for _, ok in pieza.eventos if not ok)
        return errores / len(pieza.eventos)

    def _calcular_estado(self, pieza: Pieza) -> str:
        if pieza.breaker.estado == EstadoBreaker.ABIERTO:
            return EstadoPieza.CAIDA
        if pieza.breaker.estado == EstadoBreaker.SEMIABIERTO:
            return EstadoPieza.DEGRADADA
        if not pieza.tuvo_datos:
            return EstadoPieza.DESCONOCIDA
        if self._tasa_error(pieza) >= UMBRAL_DEGRADADA:
            return EstadoPieza.DEGRADADA
        return EstadoPieza.SANA

    # --- uso por el agente -----------------------------------------------
    def permitir(self, nombre: str) -> bool:
        pieza = self._piezas.get(nombre)
        if pieza is None:
            return True
        permitido = pieza.breaker.permitir()
        self._notificar_cambio(pieza)
        return permitido

    def exito(self, nombre: str, latencia_ms: float) -> None:
        pieza = self._piezas.get(nombre)
        if pieza is None:
            return
        pieza.tuvo_datos = True
        pieza.ultima_comprobacion = _ahora_iso()
        pieza.eventos.append((self._reloj(), True))
        if pieza.latencia_ewma_ms is None:
            pieza.latencia_ewma_ms = float(latencia_ms)
        else:
            pieza.latencia_ewma_ms = EWMA_ALFA * latencia_ms + (1 - EWMA_ALFA) * pieza.latencia_ewma_ms
        pieza.breaker.exito()
        pieza.motivo = ""
        self._notificar_cambio(pieza)

    def fallo(self, nombre: str, motivo: str = "") -> None:
        pieza = self._piezas.get(nombre)
        if pieza is None:
            return
        pieza.tuvo_datos = True
        pieza.ultima_comprobacion = _ahora_iso()
        pieza.eventos.append((self._reloj(), False))
        pieza.motivo = limpiar_motivo(motivo)
        pieza.breaker.fallo()
        self._notificar_cambio(pieza)

    def _notificar_cambio(self, pieza: Pieza) -> None:
        despues = self._calcular_estado(pieza)
        antes = self._ultimo_estado.get(pieza.nombre, EstadoPieza.DESCONOCIDA)
        if despues == antes:
            return
        self._ultimo_estado[pieza.nombre] = despues
        if self._alertar is None:
            return
        try:
            self._alertar(
                {
                    "pieza": pieza.nombre,
                    "antes": antes,
                    "despues": despues,
                    "motivo": pieza.motivo,
                    "en": _ahora_iso(),
                }
            )
        except Exception:  # noqa: BLE001 - una alerta rota no debe frenar al agente
            pass

    def resumen(self) -> list[dict]:
        salida = []
        for pieza in self._piezas.values():
            salida.append(
                {
                    "nombre": pieza.nombre,
                    "tipo": pieza.tipo,
                    "estado": self._calcular_estado(pieza),
                    "ultima_comprobacion": pieza.ultima_comprobacion,
                    "latencia_ewma_ms": (
                        None if pieza.latencia_ewma_ms is None else round(pieza.latencia_ewma_ms, 1)
                    ),
                    "tasa_error_5min": round(self._tasa_error(pieza), 3),
                    "motivo": pieza.motivo,
                    "breaker": pieza.breaker.estado,
                }
            )
        return salida

    # --- comprobación activa ---------------------------------------------
    async def comprobar_todas(self, plazo_segundos: float = 5.0) -> list[dict]:
        pendientes = [p for p in self._piezas.values() if p.comprobar is not None]
        await asyncio.gather(*(self._comprobar_una(p, plazo_segundos) for p in pendientes))
        return self.resumen()

    async def _comprobar_una(self, pieza: Pieza, plazo_segundos: float) -> None:
        inicio = self._reloj()
        try:
            resultado = await asyncio.wait_for(pieza.comprobar(), timeout=plazo_segundos)  # type: ignore[misc]
        except asyncio.TimeoutError:
            self.fallo(pieza.nombre, "comprobación sin respuesta a tiempo")
            return
        except Exception as exc:  # noqa: BLE001 - una pieza no rompe a las demás
            self.fallo(pieza.nombre, f"{type(exc).__name__}: {exc}")
            return
        sana, motivo = _interpretar_salud(resultado)
        if sana:
            self.exito(pieza.nombre, (self._reloj() - inicio) * 1000.0)
        else:
            self.fallo(pieza.nombre, motivo)


def _interpretar_salud(resultado: Any) -> tuple[bool, str]:
    if isinstance(resultado, dict):
        sana = bool(resultado.get("ok", True))
        return sana, str(resultado.get("motivo", "") or ("" if sana else "comprobación fallida"))
    sana = bool(resultado)
    return sana, "" if sana else "comprobación fallida"


async def ejecutar_con_breaker(
    registro: RegistroPiezas,
    nombre: str,
    coroutine_factory: Callable[[], Awaitable[Any]],
    plazo_segundos: float,
) -> dict:
    """Ejecuta una llamada a una pieza respetando su breaker; nunca propaga fallos de la pieza."""
    if not registro.permitir(nombre):
        return {"ok": False, "motivo": "pieza en pausa", "pieza": nombre}
    inicio = time.monotonic()
    try:
        valor = await asyncio.wait_for(coroutine_factory(), timeout=plazo_segundos)
    except asyncio.CancelledError:
        pieza = registro._piezas.get(nombre)
        if pieza is not None:
            pieza.breaker.liberar_prueba()
        raise
    except asyncio.TimeoutError:
        registro.fallo(nombre, "plazo agotado")
        return {"ok": False, "motivo": "plazo agotado", "pieza": nombre}
    except Exception as exc:  # noqa: BLE001
        motivo = limpiar_motivo(f"{type(exc).__name__}: {exc}")
        registro.fallo(nombre, motivo)
        return {"ok": False, "motivo": motivo, "pieza": nombre}
    registro.exito(nombre, (time.monotonic() - inicio) * 1000.0)
    return {"ok": True, "valor": valor}


_registro_global: RegistroPiezas | None = None


def registro_global() -> RegistroPiezas:
    global _registro_global
    if _registro_global is None:
        _registro_global = RegistroPiezas()
    return _registro_global


def resetear_registro_global() -> None:
    global _registro_global
    _registro_global = None
