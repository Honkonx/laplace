# Runtime del agente

El agente es un proceso aparte del bot deportivo y se comunica con él por HTTP. Si el bot está apagado, el agente sigue respondiendo con memoria y reglas locales.

| Proceso | Módulo | Puerto |
|---|---|---|
| Bot deportivo + API + planificador | `backend.api.main` | 9001 |
| Agente | `backend.api.agent_main` | 9100 |
| Web (`frontend/`) | Vite | 9002 |
| PWA (`pwa/`) | Vite | 9003 |

Ambos procesos exponen `/health` y `/capabilities` y se descubren con un timeout de 2 s; un fallo del otro nunca bloquea el arranque.

## Persistencia

`agent_sessions` (conversaciones por usuario y canal), `agent_messages` (cada turno: sesión, usuario, rol, texto, modo y herramienta), `agent_memories` y `agent_memory_history`, `agent_knowledge`, `agent_runs`, `agent_tasks`, `agent_events`, `agent_approvals`, `agent_tool_invocations`, `agent_feedback`, `agent_learning_proposals`, `agent_policy_versions` y la tabla virtual `agent_search_fts` (FTS5). Columnas y claves: [`../backend/referencia/BASE_DE_DATOS.md`](../backend/referencia/BASE_DE_DATOS.md).

## API

Todas las rutas del agente exigen JWT; el detalle (método, ruta y quién puede llamarla) está en [`../backend/referencia/API.md`](../backend/referencia/API.md), grupo `agent`.
Resumen: chat, sesiones, memoria (con exportación y búsqueda), tareas, subagentes, herramientas, aprobaciones, eventos, feedback, propuestas de aprendizaje, `capabilities`, `usage` y `metrics` (solo admin).

## IA

El turno puede pedir IA con `usar_ia`. Se usa solo si `AGENT_IA_ACTIVA` es verdadera (por defecto lo es) y hay un proveedor con clave. El filtro local rechaza temas fuera de Laplace, del agente y del dominio deportivo. Proveedores y orden: [`../backend/IA_PROVEEDORES.md`](../backend/IA_PROVEEDORES.md).

## Conocimiento

Los JSON declarativos de `backend/knowledge/agent/core.json` (alcance del agente) y `backend/knowledge/sports/football.json` (dominio deportivo) se sincronizan a `agent_knowledge` sin duplicar por `namespace/topic_key`. Los perfiles por equipo (`equipos-*.json`) no se cargan a la tabla: las herramientas `knowledge.*` los leen directamente.

## Tareas y subagentes

Registry cerrado de tipos de tarea (`TASK_KINDS`) y de subagentes (`SUBAGENT_REGISTRY`), con `parent_id`, ejecución en paralelo, cancelación cooperativa, reintentos acotados (máximo 2), timeout por tarea y `idempotency_key` por usuario. Las tareas pendientes se reencolan al arrancar. Un worker separado (`agent_worker.py`) puede consumirlas.

## Operación local

```
python backend/scripts/create_admin.py --username <usuario>
iniciar            (o: iniciar.bat / iniciar.sh)
```

Las claves de IA se leen solo de variables de entorno (`.env`); el frontend solo ve si un proveedor está configurado y qué modelo usa, nunca la clave.
