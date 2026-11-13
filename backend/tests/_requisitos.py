"""Marcadores para pruebas que necesitan datos que NO se publican (licencias de terceros).

El producto debe funcionar sin esos datos y decirlo; las pruebas que verifican lo que solo existe CON ellos se omiten con un motivo claro, no se esconden ni se dejan fallando.
"""
import pytest

from backend.api.core.config import settings

HAY_CONOCIMIENTO_EQUIPOS = bool(list((settings.repo_root / "backend" / "knowledge" / "sports").glob("equipos-*.json")))

requiere_conocimiento_equipos = pytest.mark.skipif(
    not HAY_CONOCIMIENTO_EQUIPOS,
    reason="falta el conocimiento por equipo (no se publica: se genera con backend/scripts/generar_conocimiento_equipos.py y datos históricos propios)",
)
