"""core/errores_validacion.py — respuesta 422 que nunca se rompe por el contenido inválido que la provocó.

El manejador por defecto de FastAPI devuelve en el error el valor recibido (`input`). Si ese valor es `NaN` o `Infinity` (JSON no estándar que Python sí acepta al leer) la respuesta no se puede serializar y el
servidor contesta 500 en vez de 422 (hallado por las pruebas de robustez del modelo el 2026-11-13: `POST /api/v1/ml/predict` con el cuerpo `NaN`). Aquí los valores no finitos salen como `null` y se quita `ctx`,
que puede traer excepciones. El formato del error (`detail: [{loc, msg, type, input}]`) no cambia.
"""
from __future__ import annotations

import math

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _finito(valor: float) -> float | None:
    return valor if math.isfinite(valor) else None


async def manejador_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    errores = [{clave: valor for clave, valor in error.items() if clave != "ctx"} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errores, custom_encoder={float: _finito})})
