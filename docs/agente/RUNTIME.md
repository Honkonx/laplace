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

## Comprensión del mensaje (2026-11-11)
- `agent_runtime_reglas.py`: quita `¿ ¡`; extrae el partido con «vs / versus / contra / ante», «Madrid-Barça» (guion solo tras una pista de partido, para no romper «Colo-Colo»), «A o B, ¿quién gana?» y «compara A y B»; entiende «Over 2.5 / ambos marcan en A vs B» y «who wins».
- El filtro de alcance ya no bloquea temas de fútbol (tabla, jugador, goles, pronóstico, «cómo viene», retomar…). Respuestas deterministas nuevas: `agent.resume` (retomar), `agent.no_apuestas` (Laplace no es casa de apuestas), `agent.sin_datos_jugadores` y `agent.tabla_no_disponible` (se dice con honestidad lo que aún no existe) y «pronóstico de hoy» → Top Picks ya publicados.
- **Historial:** el prompt de la IA incluye los últimos 8 turnos de la sesión como datos (sin delimitadores) y el mensaje del usuario se escapa. Cada herramienta pedida desde el chat o Telegram queda en `agent_tool_invocations`. Pendiente: rol `system` separado en `ai_client`.
- Conjunto dorado de frases: `backend/tests/test_agent_fase_a.py`.

## Piezas, respaldo y modelo propio (2026-11-11)
- **Registro de piezas** (`agent_piezas.py`): bot, modelo e IA con estado (`sana`/`degradada`/`caida`/`desconocida`), latencia, tasa de error y **circuit breaker** (3 fallos en 60 s → en pausa 30 s → una llamada de prueba). Toda llamada al bot pasa por él (`agent_tools._get`/`_post`): con el bot caído la siguiente consulta no espera el plazo completo. `/estado` de Telegram muestra el estado de cada pieza.
- **Modelo en el proceso del agente** (`AGENT_MODELO_EN_PROCESO=True`): `modelo.pronosticar` calcula con el puntero `vigente.json` (Python puro, sin red ni base) y solo cae al HTTP del bot si no puede; el modelo ya no depende de que el bot esté vivo.
- **Cadena de respaldo para «analiza A vs B»:** bot ‖ modelo → si el bot no responde o el partido no está en su calendario, **solo el modelo** con los nombres → si tampoco, **hipótesis de IA rotulada «NO calculada por Laplace»**, sin porcentajes ni marcador, solo si la IA está permitida en el turno (`AGENT_IA_PURA_AUTOMATICA`) → si no, un aviso honesto. Nunca se inventa una cifra.

## Marcador de piezas por liga y pesos (2026-11-11)
- `scripts/previa_piezas_por_liga.py` mide, walk-forward desde 2023-07-01, el log loss POR LIGA de `modelo` (Laplace g3), `dixon_coles`, `mercado` (solo con cuotas) y `bot` (aproximación del consenso: 0,70 mercado + 0,25 Dixon-Coles con cuotas; Dixon-Coles sin ellas) sobre los mismos partidos → `backend/data/datos/resultados/previa_piezas_por_liga.json` (49 ligas; datos locales, no se publican).
- `agent_marcador.py`: pesos de presentación entre `modelo` y `bot` = previa histórica contraída con lo medido en vivo en el laboratorio (`λ = n/(n+150)`, ignorado con menos de 30 partidos), acotados a [0,2; 0,8]; solo se nombra un líder con diferencia ≥ 0,002 de log loss; si no, «no hay evidencia para preferir uno». **No cambia las cifras** de ninguna pieza: decide qué se dice primero y la frase.
- La predicción con bot y modelo agrega una frase corta («En Premier League el bot rinde mejor en el histórico: log loss …, n partidos; diferencia pequeña, no una garantía») y `/marcador [liga]` (administrador) muestra la tabla.

## Privacidad del agente (2026-11-11)
- Antes de guardar y de enviar al proveedor de IA, `agent_privacidad.redactar` enmascara claves, tokens, JWT, correos y números de tarjeta.
- `/incognito [on|off]` (Telegram) o `incognito=true` (chat web): se responde pero no se guarda nada; el modo vive en el proceso.
- `/olvidar confirmo`: borra lo del usuario en `agent_messages`, `agent_runs`, `agent_sessions`, `agent_tasks`, `agent_feedback`, `agent_memories`, `agent_memory_history` y el índice `agent_search_fts`; anonimiza `agent_approvals`, `agent_events` y `agent_tool_invocations`. Una prueba falla si se agrega una tabla `agent_*` sin clasificar.
- El cupo diario de IA y de predicciones se guarda en `agent_uso_diario` (solo conteos) y sobrevive a los reinicios; `/olvidar` no lo borra, para no devolver el cupo.

## Diálogo, herramientas nuevas, historial y presupuesto (2026-11-11)
- `agent_dialogo.py`: los seguimientos cortos («¿y mañana?», «¿y las cuotas?») heredan el último partido de la sesión.
- Herramientas de lectura nuevas: `sports.recent_results` (últimos resultados de un equipo) y `knowledge.compare_teams` (perfiles lado a lado); «¿qué me dijiste de X?» busca en el historial propio (`agent.search_history`).
- `AGENT_PERMISIVIDAD` (`estricto` | `normal` | `abierto`): en `estricto` la IA no conversa libremente; en `normal` lo que dice sin respaldo del modelo lleva la etiqueta «no verificada».
- Presupuesto diario de tokens por usuario (`AGENT_IA_TOKENS_POR_DIA`): agotado, se responde sin IA y se avisa.
- Sesiones largas: `historial_reciente` antepone un resumen estructurado (partidos y mercados consultados) a los últimos 8 turnos.
- Modo CON IA con herramientas (`AGENT_FUNCTION_CALLING`, apagado): la IA llama `laplace_pronosticar`, `resultados_recientes` y `comparar_perfiles`; si alguna cifra del texto no sale de las herramientas o del mensaje, se descarta y se responde por el camino normal.
