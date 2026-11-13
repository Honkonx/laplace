"""
db/analisis_repo.py — Persistencia de análisis (individual, comparativo, multimodelo) y
caché de consenso.

Port de las funciones equivalentes de db_query.py — llamadas hoy desde WF-B
(`Guardar en BD`, wfb-019) con `body: { cmd: '' }` VACÍO en 7 de sus 7 pasos (confirmado por
grep, ver docs/humano/ de esta ronda): ningún análisis con IA persiste hoy, ningún job de plan
pro/max se marca `listo`. Acá cada función hace el `INSERT`/`UPDATE` real.
"""
from __future__ import annotations

# Fachada: el código vive en `analisis_repo_comun`, `_guardado`, `_cache`, `_stats`, `_top_picks` y
# `_verificacion`. Los nombres se reexportan acá porque routers, bots, agentes y pruebas los usan
# como `analisis_repo.<nombre>`.
from backend.api.db.analisis_repo_cache import (
    activar_cache_consenso,
    guardar_cache,
    verificar_cache,
    verificar_consenso_cache,
)
from backend.api.db.analisis_repo_comun import _now_str, log
from backend.api.db.analisis_repo_guardado import (
    existe_comparativo,
    guardar_analisis_individual,
    guardar_analisis_multimodelo,
    guardar_comparativo,
    guardar_prediccion,
)
from backend.api.db.analisis_repo_stats import leer_historial_app, leer_stats, leer_stats_aciertos
from backend.api.db.analisis_repo_top_picks import leer_top_picks_app
from backend.api.db.analisis_repo_verificacion import verificar_partido_completo

__all__ = [
    "_now_str", "activar_cache_consenso", "existe_comparativo", "guardar_analisis_individual",
    "guardar_analisis_multimodelo", "guardar_cache", "guardar_comparativo", "guardar_prediccion",
    "leer_historial_app", "leer_stats", "leer_stats_aciertos", "leer_top_picks_app", "log",
    "verificar_cache", "verificar_consenso_cache", "verificar_partido_completo",
]
