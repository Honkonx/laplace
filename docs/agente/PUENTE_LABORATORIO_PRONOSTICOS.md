# Puente agente ↔ laboratorio de pronósticos

El bot y el agente son procesos independientes. El bot registra en el laboratorio las variantes `python_baseline`, `python_plus_ia`, `bsd_catboost` (cuando hay dato) e `ia_simple` (que escribe Top Picks, no el agente). Ver [`../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md`](../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md).

## Qué hace el agente
- Guarda su historial privado en `predicciones_variantes_agente` (proveedor, modelo, `prompt_version`, texto crudo). Hoy solo se registra la vía «solo IA» (`ai_scout`), con `partido_id` y `liga` vacíos: una consulta conversacional puede no tener un partido resuelto, y sin partido, fecha y hora de inicio no se puede evaluar honestamente una hipótesis.
- Antes de una predicción pregunta si el usuario quiere la **predicción del bot** o **solo IA** (`agent.prediction_choice`).
- Marca la respuesta de solo IA como hipótesis experimental, fuera del consenso público.
- Muestra a cada usuario únicamente su propio historial; el informe comparativo completo es del administrador.

## Qué no puede hacer
Promover variantes, cambiar pesos ni escribir en las tablas del laboratorio: el bot valida el corte temporal y la normalización 1X2.

## Pendiente
Resolver el partido (equipos, competición, fecha y hora) con el bot antes de la ruta de solo IA, para poder registrar esas hipótesis como observaciones evaluables.
