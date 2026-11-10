"""ml/ — modelos estadísticos entrenados con datos históricos reales (2026-09-29).

Separación deliberada: el AJUSTE (numpy/scipy/scikit-learn, offline, `backend/scripts/
entrenar_modelo_historico.py`) vive aparte de la PREDICCIÓN (Python puro, sin dependencias
nuevas). El bot en producción solo carga artefactos JSON (`ml/artefactos/`) y evalúa fórmulas
simples — así corre igual en Windows, Docker o Termux sin instalar numpy/scipy.
"""
