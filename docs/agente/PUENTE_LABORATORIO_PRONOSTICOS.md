# Puente agente ↔ laboratorio de pronósticos

El bot y el agente son procesos independientes. El bot registra en el laboratorio las variantes `python_baseline`, `python_plus_ia`, `bsd_catboost` (cuando hay dato) e `ia_simple` (que escribe Top Picks, no el agente). Ver [`../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md`](../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md).

## Qué hace el agente
- Guarda su historial privado en `predicciones_variantes_agente` (proveedor, modelo, `prompt_version`, texto crudo). Hoy solo se registra la vía «solo IA» (`ai_scout`). Antes de guardar intenta resolver el partido con el bot (`partido_id` y `liga`); si el bot no está o no lo encuentra, la hipótesis se guarda igual pero sin partido y por eso **no se puede evaluar**.
- Al llegar el resultado oficial (`services/resultados.py`), las hipótesis con `partido_id` se califican (`resultado_real` y `pick_correcto`) con el mismo criterio que el resto del track record; las ya calificadas no se recalifican.
- Antes de una predicción pregunta si el usuario quiere la **predicción del bot** o **solo IA** (`agent.prediction_choice`).
- Marca la respuesta de solo IA como hipótesis experimental, fuera del consenso público.
- Muestra a cada usuario únicamente su propio historial; el informe comparativo completo es del administrador.

## Qué no puede hacer
Promover variantes, cambiar pesos ni escribir en las tablas del laboratorio: el bot valida el corte temporal y la normalización 1X2.

## Pendiente
Registrar también las hipótesis «solo IA» como observaciones `ia_simple` del laboratorio (hoy solo las crea Top Picks), para medirlas con Brier, log loss y RPS además del acierto del pick.
