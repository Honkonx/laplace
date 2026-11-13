"""Alertas operativas opcionales.

El webhook está desactivado por defecto. Cuando se configura, solo recibe eventos estructurados
de fallo; nunca se envían tokens, contraseñas ni payloads completos de usuario.

Enfriamiento (2026-11-10): un fallo que se repite (p. ej. una tarea del agente que cae cada minuto) no debe inundar el canal. El mismo evento (con su `error_type` o `kind`)
no se reenvía antes de `ALERT_COOLDOWN_SEGUNDOS`; lo suprimido se cuenta y el siguiente envío lo informa en `detail.suprimidas`.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from backend.api.core.config import settings

log = logging.getLogger("laplace.alerting")

_LOCK = threading.Lock()
_ULTIMO_ENVIO: dict[str, float] = {}
_SUPRIMIDAS: dict[str, int] = {}
_MAX_CLAVES = 500  # tope de memoria: un atacante no puede crecer el diccionario inventando eventos


def resetear_enfriamiento() -> None:
    with _LOCK:
        _ULTIMO_ENVIO.clear()
        _SUPRIMIDAS.clear()


def _clave(evento: str, detalle: dict[str, object]) -> str:
    return f"{evento}|{detalle.get('error_type') or detalle.get('kind') or ''}"


def _en_enfriamiento(clave: str) -> bool:
    """True si hay que suprimir; en ese caso cuenta la supresión. Si no, reserva el turno de envío."""
    ventana = max(int(settings.ALERT_COOLDOWN_SEGUNDOS), 0)
    ahora = time.monotonic()
    with _LOCK:
        previo = _ULTIMO_ENVIO.get(clave)
        if ventana and previo is not None and ahora - previo < ventana:
            _SUPRIMIDAS[clave] = _SUPRIMIDAS.get(clave, 0) + 1
            return True
        if len(_ULTIMO_ENVIO) >= _MAX_CLAVES and clave not in _ULTIMO_ENVIO:
            _ULTIMO_ENVIO.pop(next(iter(_ULTIMO_ENVIO)))
        _ULTIMO_ENVIO[clave] = ahora
        return False


def emitir_alerta(evento: str, detalle: dict[str, object]) -> bool:
    if not settings.ALERTS_ACTIVAS or not settings.ALERT_WEBHOOK_URL:
        return False
    clave = _clave(evento, detalle)
    if _en_enfriamiento(clave):
        return False
    with _LOCK:
        suprimidas = _SUPRIMIDAS.pop(clave, 0)
    payload = {"source": "laplace", "event": evento, "detail": {**detalle, "suprimidas": suprimidas} if suprimidas else detalle}
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.post(settings.ALERT_WEBHOOK_URL, json=payload)
            response.raise_for_status()
        return True
    except Exception as exc:
        log.warning("No se pudo entregar alerta operativa: %s", type(exc).__name__)
        with _LOCK:
            _SUPRIMIDAS[clave] = _SUPRIMIDAS.get(clave, 0) + suprimidas  # lo no entregado no se pierde de la cuenta
            _ULTIMO_ENVIO.pop(clave, None)  # un envío fallido no cuenta como enviado: el siguiente intento no se enfría
        return False
