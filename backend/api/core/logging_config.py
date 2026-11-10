"""core/logging_config.py — logging estructurado en JSON para toda la app FastAPI.

Se eligió un `logging.Formatter` custom en vez de agregar `python-json-logger` como
dependencia nueva: el formato que necesita este proyecto es simple (timestamp, level,
logger, message, más los campos extra que ya se pasan hoy con `extra={...}` en llamadas
de logging existentes) y no justifica una dependencia extra solo para serializar un dict
a JSON — YAGNI, ver `.claude/rules/clean-code-principles.md`.

Reemplaza el estado actual (ningún módulo llama `logging.basicConfig`, así que Python usa
el handler `lastResort` sin formato estructurado — solo texto plano a stderr). Se invoca
desde `lifespan()` en `main.py`, antes de arrancar el bot/scheduler, para que TODO el
logging de la app quede en JSON desde el primer mensaje — incluye los loggers de módulos
que ya existen (`laplace.main`, `laplace.auth`, etc.) porque configura el ROOT logger, no uno
nuevo, y esos módulos usan `logging.getLogger(...)` sin propagate=False.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Campos propios de un LogRecord "vacío" — todo lo que no esté acá y sí esté en
# record.__dict__ es un campo extra pasado por el caller (ej. `extra={"device_id": ...}`).
_CAMPOS_RESERVADOS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    """Formatea cada LogRecord como una línea JSON — timestamp (UTC ISO 8601), level,
    logger, message, más cualquier campo extra pasado vía `extra={...}`. Nunca hay que
    pasar secretos/passwords en `extra` (ver `.claude/rules/secrets-never-revealed.md`) —
    este formatter no filtra nada, solo serializa lo que el caller ya decidió loguear."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _CAMPOS_RESERVADOS}
        if extras:
            payload.update(extras)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


# Loggers que, a nivel INFO, imprimen la URL completa de cada request — y varias APIs externas
# de Laplace van con la API key en la URL como query param (The Odds API `apiKey=`, Gemini
# `key=`) o en el propio path (Telegram: `https://api.telegram.org/bot<TOKEN>/getMe`). Encontrado
# 2026-09-08 en vivo: el token real de Telegram apareciendo en texto plano en el log JSON de cada
# request del bot — ver el registro de decisiones del proyecto. Subirlos a WARNING no pierde nada útil (el propio
# código de Laplace ya loguea sus propios eventos con logueres `laplace.*` a INFO) y cierra la fuga.
_LOGGERS_CON_URLS_SENSIBLES = ("httpx", "httpcore")


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Configura el root logger con el formatter JSON. Idempotente — limpia handlers
    previos antes de agregar el nuevo, para no duplicar líneas si se llama más de una vez
    (ej. tests que reconstruyen la app, o un reload de uvicorn)."""
    root = logging.getLogger()
    root.setLevel(nivel)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    for nombre in _LOGGERS_CON_URLS_SENSIBLES:
        logging.getLogger(nombre).setLevel(logging.WARNING)
