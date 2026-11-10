"""core/rate_limit.py — Rate limiting con slowapi, para endpoints sensibles a fuerza bruta.

Límite elegido para `/api/v1/auth/login` y `/api/v1/auth/registro`: **5 intentos por minuto,
por IP**. Motivo (no es un número arbitrario):
- Un usuario real que se equivoca de contraseña rara vez necesita más de 2-3 reintentos en
  un minuto — 5 deja margen real para errores de tipeo genuinos sin trabar el uso normal.
- A ese ritmo, probar un diccionario de contraseñas comunes contra una cuenta (fuerza bruta
  clásica) se vuelve impracticable: cientos de intentos tomarían horas en vez de segundos.
- `/registro` comparte el mismo límite porque también es un vector de abuso (spam de cuentas,
  enumeración de usernames vía el 409 "ya en uso") — no hay motivo para que sea más laxo.
- Todavía no existe bloqueo de cuenta tras N fallos (`.claude/skills/backend-api-seguridad`
  sugiere 30/min + bloqueo de cuenta a 5 fallos/15min como combinación) — mientras eso no
  exista, se prefiere el límite más estricto por IP (5/min) en vez de uno más laxo (30/min)
  que dependería de una segunda capa de defensa que todavía no está implementada.

Clave del limitador: IP remota (`get_remote_address`) — no hay usuario autenticado todavía en
estos dos endpoints (son los que EMITEN la sesión), así que no aplica la distinción
"usuario autenticado vs IP" que sí tendría sentido en endpoints ya protegidos por JWT.
"""
from __future__ import annotations

import typing
from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def limitar(regla: str) -> Callable:
    """Envoltorio sobre `limiter.limit()` — usar SIEMPRE en vez del decorador crudo de
    slowapi en cualquier router que tenga `from __future__ import annotations` (PEP 563,
    todos los routers de este proyecto lo tienen).

    Bug real encontrado 2026-09-08 al agregar rate limiting a `/api/v1/auth/login` y
    `/registro` (confirmado corriendo la suite real, no solo revisando el código — ver
    `.claude/rules/empirical-verification-before-fix.md`): con PEP 563, las anotaciones de
    un endpoint quedan guardadas como STRING (`"LoginInput"`, no la clase). FastAPI las
    resuelve en `fastapi.dependencies.utils.get_typed_signature()` usando
    `wrapper.__globals__` — pero `wrapper.__globals__` de la función que devuelve
    `limiter.limit()` apunta al namespace del MÓDULO DE SLOWAPI (`__globals__` no lo puede
    reescribir `functools.wraps`, es de solo lectura), no al del router (`auth.py`). El
    resultado: FastAPI no encuentra `LoginInput` en ese namespace y termina tratando
    `body: LoginInput` como un parámetro de query sin tipo — todo el body real del POST se
    ignora y responde 422 "Field required" en vez de 401/409/200 según corresponda.

    Fix: resolver las anotaciones del endpoint a objetos reales (`typing.get_type_hints`,
    que sí usa el `__globals__` correcto porque se llama ANTES de que slowapi envuelva la
    función) y mutar `func.__annotations__` in-place con esos objetos ya resueltos. Cuando
    slowapi copia `__annotations__` al wrapper (vía `functools.wraps`), copia valores que ya
    no son strings — `get_typed_annotation()` de FastAPI los deja pasar tal cual, sin
    necesitar evaluarlos contra ningún `__globals__`.
    """

    def decorador(func: Callable) -> Callable:
        func.__annotations__ = typing.get_type_hints(func)
        return limiter.limit(regla)(func)

    return decorador
