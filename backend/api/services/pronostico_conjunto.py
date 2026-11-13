"""services/pronostico_conjunto.py — orquestador de las piezas que producen un pronóstico: en PARALELO las independientes, en SERIE lo que consume sus salidas.

Piezas típicas: el análisis del bot (motor, fuentes, cuotas) y el modelo Laplace corren en paralelo, cada una con su plazo; después, en serie, la IA que explica (opcional) con lo que haya.
Reglas del diseño (ver `docs/arquitectura/CONEXIONES_MOTOR_BOT_MODELO_IA.md`):
- Ninguna pieza depende de otra: cada una es una función sin argumentos que devuelve un valor. Si cae, se agota su plazo o se cancela, las demás siguen y el resultado lo dice.
- Nunca se inventa lo que falta: una pieza caída queda con `ok = False`, el motivo y el tiempo; quien consume decide qué hacer (responder con la otra, degradar o fallar).
- El orquestador no conoce los datos de las piezas ni importa el bot, el modelo ni la IA: solo las ejecuta y las mide.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

PLAZO_POR_DEFECTO = 30.0


@dataclass
class Pieza:
    nombre: str
    ok: bool = False
    valor: Any = None
    error: BaseException | None = None
    segundos: float = 0.0
    agotada: bool = False

    def resumen(self) -> dict:
        return {"ok": self.ok, "segundos": round(self.segundos, 3), "agotada": self.agotada, "error": type(self.error).__name__ if self.error else None}


@dataclass
class Conjunto:
    """Resultado de una ronda: `paralelas` (las independientes) y `serie` (las que consumen)."""

    paralelas: dict[str, Pieza] = field(default_factory=dict)
    serie: dict[str, Pieza] = field(default_factory=dict)

    def valor(self, nombre: str) -> Any:
        pieza = self.paralelas.get(nombre) or self.serie.get(nombre)
        return pieza.valor if pieza and pieza.ok else None

    @property
    def disponibles(self) -> list[str]:
        return [n for n, p in {**self.paralelas, **self.serie}.items() if p.ok and p.valor is not None]

    def resumen(self) -> dict:
        return {nombre: pieza.resumen() for nombre, pieza in {**self.paralelas, **self.serie}.items()}


async def _correr(nombre: str, fabrica: Callable[[], Awaitable[Any]], plazo: float) -> Pieza:
    pieza, inicio = Pieza(nombre), time.perf_counter()
    try:
        pieza.valor = await asyncio.wait_for(fabrica(), timeout=plazo)
        pieza.ok = True
    except (TimeoutError, asyncio.TimeoutError) as exc:
        pieza.error, pieza.agotada = exc, True
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — la caída de una pieza es un resultado, no una excepción hacia las demás
        pieza.error = exc
    pieza.segundos = time.perf_counter() - inicio
    return pieza


async def ejecutar(
    paralelas: dict[str, Callable[[], Awaitable[Any]]],
    plazos: dict[str, float] | None = None,
    serie: dict[str, Callable[[Conjunto], Awaitable[Any]]] | None = None,
) -> Conjunto:
    """Corre `paralelas` a la vez y luego `serie` una tras otra; cada pieza de la serie recibe el `Conjunto` parcial para usar lo que haya (o saltarse lo que falte)."""
    plazos = plazos or {}
    resultado = Conjunto()
    if paralelas:
        piezas = await asyncio.gather(*(_correr(n, f, plazos.get(n, PLAZO_POR_DEFECTO)) for n, f in paralelas.items()))
        resultado.paralelas = {p.nombre: p for p in piezas}
    for nombre, fabrica in (serie or {}).items():
        resultado.serie[nombre] = await _correr(nombre, lambda fabrica=fabrica: fabrica(resultado), plazos.get(nombre, PLAZO_POR_DEFECTO))
    return resultado
