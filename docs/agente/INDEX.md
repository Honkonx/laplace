# docs/agente/ — El agente de Laplace

El agente corre como proceso aparte (`backend.api.agent_main`, puerto 9100) y consulta al bot por HTTP.

| Archivo | Qué contiene |
|---|---|
| [`RUNTIME.md`](RUNTIME.md) | Cómo corre: proceso, modos, tareas y reglas locales |
| [`CONTROL_PLANE.md`](CONTROL_PLANE.md) | Estado, permisos y control del agente |
| [`HERRAMIENTAS.md`](HERRAMIENTAS.md) | Herramientas que puede invocar |
| [`TELEGRAM.md`](TELEGRAM.md) | El bot de Telegram del agente |
| [`MEMORIA_BUSQUEDA_APRENDIZAJE.md`](MEMORIA_BUSQUEDA_APRENDIZAJE.md) | Memoria, búsqueda y aprendizaje controlado |
| [`FLUJO_DEPORTIVO_INVOCABLE.md`](FLUJO_DEPORTIVO_INVOCABLE.md) | Cómo el agente pide un pronóstico al bot deportivo |
| [`PUENTE_LABORATORIO_PRONOSTICOS.md`](PUENTE_LABORATORIO_PRONOSTICOS.md) | Relación entre el agente y el laboratorio de pronósticos |
