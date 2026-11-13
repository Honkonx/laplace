"""Modelo propio de Laplace: pronostica (1X2, goles esperados, marcadores, ambos marcan, más/menos).

No decide si algo se publica: esa política es del agente (ver `ANALISIS_PLAN_GPT_Y_AJUSTES_AL_MODELO_PROPIO_2026-11-10.md` en docs/archive).
Módulos: `pronostico` (matriz de goles), `simulacion` (mundos con verdad conocida e importador), `entrenamiento`
(regresión logística propia, walk-forward), `registro` (tablas `ml_*`), `servicio` (predicción con degradación).
"""
VERSION_GENERADOR = "sim-1"
