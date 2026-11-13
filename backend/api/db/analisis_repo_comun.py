"""
db/analisis_repo_comun.py — Utilidades compartidas de los repos de análisis. Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

import logging

from backend.api.core.tiempo import utc_ahora

log = logging.getLogger("laplace.analisis_repo")


def _now_str() -> str:
    """`creado_en`/`completado_en` de este módulo — normalizado a UTC 2026-09-09 (ver
    docstring de `jobs_repo._now_str`). Filas anteriores a este commit pueden estar en hora
    local de Chile. `fecha` (día calendario del partido/análisis, distinto de `creado_en`)
    NO se toca acá — sigue siendo negocio en hora local, ver `jobs_repo.rango_utc_dia_chile`."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")
