"""laplace_agents — el agente de Laplace, separado del backend a propósito.

Ver `README.md` (raíz de este paquete) para la visión completa. Hoy expone el ciclo de
auto-evaluación diaria (`core.py`); el resto del roadmap (puntuación de ligas, filtrado de
partidos prometedores, detector de uniformidad, auditoría de riqueza de datos, encuestas a
usuarios) se construye incrementalmente sobre esta base."""
from __future__ import annotations

from .core import (
    CAP_PARTIDOS_POR_CORRIDA,
    USUARIO_SISTEMA,
    ejecutar_ciclo_autoevaluacion,
)

__all__ = ["ejecutar_ciclo_autoevaluacion", "CAP_PARTIDOS_POR_CORRIDA", "USUARIO_SISTEMA"]
