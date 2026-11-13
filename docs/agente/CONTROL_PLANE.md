# Control plane del agente

El agente registra sesiones, mensajes, tareas, subagentes, invocaciones de herramientas, eventos, aprobaciones humanas y versiones de políticas.

## Herramientas y aprobación

Las 12 herramientas ([`HERRAMIENTAS.md`](HERRAMIENTAS.md)) se listan en `GET /api/v1/agent/tools` (un usuario normal solo ve las de lectura) y se ejecutan por `POST /api/v1/agent/tools/{tool_name}`. Cada ejecución queda en `agent_tool_invocations`.
Las acciones que exigen confirmación crean una aprobación pendiente en `agent_approvals`; solo un administrador puede aprobarla o rechazarla (`GET /api/v1/agent/approvals`, `POST .../approvals/{id}/approve` y `.../reject`).
La publicación mantiene dos barreras: rol de administrador y el argumento explícito `publish=true`; aprobar una solicitud no añade ese argumento.

## Política de publicación (`services/agent_politica_publicacion.py`)
El modelo y el bot solo pronostican; **publicar es decisión del agente**. La política es una función pura con tres salidas y sus motivos:
- `no_publicar`: no hay picks válidos, algún pick tiene menos de 50 % de probabilidad o el lote es de baja confianza.
- `publicar_con_aprobacion` (por defecto): un administrador confirma (`/publicar confirmo`).
- `publicar_solo`: solo con `AGENTE_PUBLICA_SOLO=1` **y** al menos 200 pronósticos del motor ya jugados en el laboratorio. Hoy es imposible: no hay esa evidencia.
`sports.top_picks` (vista previa, sin publicar) devuelve la recomendación en `politica_publicacion`. El trabajo diario de Top Picks del bot (09:00) no pasa por esta política; la política gobierna al agente.

## Eventos y tareas

`agent_events` registra tareas encoladas, iniciadas, reintentadas, terminadas y canceladas, y subagentes creados. `GET /api/v1/agent/events` devuelve los eventos propios; el administrador ve el conjunto.
`GET /api/v1/agent/metrics` (solo admin) expone contadores en formato Prometheus: tareas, aprobaciones, memoria, invocaciones y eventos.

## Memoria y políticas

- `recuerda que ...` guarda una memoria privada con fuente `chat:auto`, confianza 0,8 y vencimiento de 365 días. La memoria global solo la crea un administrador.
- `GET /api/v1/agent/memory/export?formato=jsonl` exporta las memorias **normales, activas y no vencidas** visibles para el usuario; las sensibles no salen.
- Cada alta, cambio o archivado deja una fila append-only en `agent_memory_history` (`/agent/memory/{id}/history`). Cada fila lleva `agent_id`.
- Una propuesta de aprendizaje aprobada por el administrador crea una `AgentPolicyVersion` activa y deja la anterior como `superseded`. Las políticas activas se incorporan al prompt del agente; no editan skills ni código.
