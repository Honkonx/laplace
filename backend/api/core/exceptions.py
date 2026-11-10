"""
core/exceptions.py — Jerarquía de excepciones tipadas para fuentes externas.

Patrón adaptado de la skill `error-handling-patterns` (.claude/skills/error-handling-patterns/
SKILL.md) — reemplaza el `except Exception` genérico que usan todos los scripts de
backend/python/ hoy. Cada fuente externa real de Laplace tiene su propia jerarquía
Transient/Permanent para poder decidir CUÁNDO reintentar (ver services/gateway.py, Parte 2).
"""
from __future__ import annotations


class LaplaceError(Exception):
    """Base de todas las excepciones propias del backend de Laplace."""


class ExternalSourceError(LaplaceError):
    """Base para errores de cualquier fuente externa (API o scraping)."""


class ExternalSourceTransientError(ExternalSourceError):
    """Error temporal — reintentar puede funcionar (timeout, 5xx, rate limit)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ExternalSourcePermanentError(ExternalSourceError):
    """Error permanente — no reintentar (401/403 por API key inválida, 404, payload rechazado)."""


class OddsAPIError(ExternalSourceError):
    """Errores de The Odds API."""


class OddsAPITransientError(OddsAPIError, ExternalSourceTransientError):
    pass


class OddsAPIPermanentError(OddsAPIError, ExternalSourcePermanentError):
    pass


class BSDAPIError(ExternalSourceError):
    """Errores de BSD API (bzzoiro.com)."""


class ApiFootballError(ExternalSourceError):
    """Errores de api-football / api-sports."""


class AnalysisInputError(LaplaceError):
    """El JSON de entrada a un servicio de análisis es inválido o insuficiente.

    Equivalente tipado de lo que hoy backend/python/{h2h,odds,tabla_pos}.py devuelven como
    {'ok': False, 'error': razon} desde sus funciones `validar_*`.
    """


class JobNotFoundError(LaplaceError):
    """No existe un job con el id pedido."""


class LimiteAnalisisDiarioError(LaplaceError):
    """El device_id/usuario ya agotó su límite de análisis del día (plan free/pro).

    Equivalente al fallo de `verificar_limite`/`verificar_limite_app` en db_query.py.
    """
