# Estado actual: bot, agente y evaluación

## Procesos independientes

- **Bot/API:** `backend.api.main`, puerto 9001. Obtiene fixtures, calcula pronósticos, publica Top Picks, verifica resultados y expone el gateway de Telegram, web y Android.
- **Agente:** `backend.api.agent_main`, puerto 9100. Mantiene conversación, memoria, tareas y subagentes. Consulta al bot por herramientas HTTP y sigue con reglas locales si el bot no está disponible (ver [`../agente/INDEX.md`](../agente/INDEX.md)).
- **Clientes:** `frontend/` (9002), `pwa/` (9003) y `app-android/`. No contienen lógica de pronóstico ni secretos del servidor: la web usa JWT; la cabecera `x-kairos-key` es solo de la app Android, que la recibe al compilarla.

## Pronósticos

Votan en el consenso (`services/consenso.py`, `PESOS_BASE`): **cuotas** (0,70), **modelo histórico** Dixon-Coles entrenado (0,25), **tabla** (0,03) y **forma** (0,02). Poisson, H2H y BSD (`bsd_ml`) tienen peso 0: se calculan y se registran en el laboratorio, pero no votan. Un peso 0 equivale a módulo ausente.
La IA explica o contrasta el resultado; una hipótesis solo IA se marca como experimental. Una fuente externa no gana peso por existir: solo por evidencia medida (`.claude/rules/evidencia-historica-antes-de-promover.md`).

El planificador de Top Picks usa identificadores de competición curados (`LIGAS_OK`); la web consume el mismo catálogo y no debe elegir ligas por un nombre ambiguo como «Premier League».

## Laboratorio y resultados

Al calcular los candidatos de Top Picks se congela la salida del motor y, si existe, la referencia de API-Football; tras la consolidación se registra también la variante con contraste de IA. Los registros son prepartido, con hora de corte (ver [`LABORATORIO_EVALUACION_PRONOSTICOS.md`](LABORATORIO_EVALUACION_PRONOSTICOS.md)).
El ciclo de resultados corre cada dos horas y a las 07:00 (hora de Chile): consulta las fuentes en orden, actualiza los resultados y califica las observaciones pendientes del laboratorio con acierto, Brier, log loss y RPS. Cada corrida queda en `scheduler_runs`. Todos los trabajos: [`../backend/referencia/TRABAJOS_PROGRAMADOS.md`](../backend/referencia/TRABAJOS_PROGRAMADOS.md).

## Referencias humanas

`POST /api/v1/admin/laboratorio-pronosticos/predicciones-humanas` (solo JWT con rol `admin`) registra el alias, pick, marcador y razón de una persona para un partido ya identificado; se guarda como `human_reference` en sombra. El formulario obtiene los partidos en caché de `GET /api/v1/admin/laboratorio-pronosticos/partidos?fecha=AAAA-MM-DD`.

## Límites vigentes

- El consenso no se recalibra solo desde fuentes externas ni humanas.
- Promover una variante exige muestra suficiente, revisión administrativa y validación fuera de muestra.
- La prórroga y los penales quedan «no estimables» sin contexto fiable de la competición.
