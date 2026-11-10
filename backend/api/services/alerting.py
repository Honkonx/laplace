"""Alertas operativas opcionales.

El webhook está desactivado por defecto. Cuando se configura, solo recibe eventos estructurados
de fallo; nunca se envían tokens, contraseñas ni payloads completos de usuario.
"""
from __future__ import annotations

import logging

import httpx

from backend.api.core.config import settings

log = logging.getLogger("laplace.alerting")


def emitir_alerta(evento: str, detalle: dict[str, object]) -> bool:
    if not settings.ALERTS_ACTIVAS or not settings.ALERT_WEBHOOK_URL:
        return False
    payload = {"source": "laplace", "event": evento, "detail": detalle}
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.post(settings.ALERT_WEBHOOK_URL, json=payload)
            response.raise_for_status()
        return True
    except Exception as exc:
        log.warning("No se pudo entregar alerta operativa: %s", type(exc).__name__)
        return False
