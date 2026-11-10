# Referencia de la API

> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).

88 rutas en 13 grupos. «Acceso» sale de las dependencias reales de cada ruta; la API interactiva está en `/docs` con el backend encendido.

## (sin grupo)

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/health` | público | — |
| GET | `/capabilities` | público | — |
| GET | `/dependencies/agent` | público | Detecta el agente sin convertirlo en requisito del bot deportivo. |
| GET | `/health` | público | Healthcheck mínimo del backend deportivo, independiente de Telegram y del agente. |
| POST | `/webhook/kairos-app` | app Android (`x-kairos-key`) | — |

## admin

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/admin/calibracion` | admin (JWT con rol admin) | Winrate real por módulo (poisson/forma/h2h/odds/tabla/externo) + winrate del pick final + Brier score de calibración del módulo Poisson, leídos de… |
| GET | `/api/v1/admin/codigos` | admin (JWT con rol admin) | `filtro`: `disponibles` \| `usados` \| `todos` (default) — envuelve `codigos_repo.listar_codigos`, sin paginar (mismo comportamiento que esa función). |
| GET | `/api/v1/admin/conexiones` | admin (JWT con rol admin) | Las 13 conexiones externas (datos, IA y Telegram) con su estado de configuración. |
| PUT | `/api/v1/admin/conexiones-orden-ia` | admin (JWT con rol admin) | — |
| DELETE | `/api/v1/admin/conexiones/{conexion_id}` | admin (JWT con rol admin) | — |
| POST | `/api/v1/admin/conexiones/{conexion_id}` | admin (JWT con rol admin) | Guarda (o cambia) la clave de una conexión. |
| POST | `/api/v1/admin/conexiones/{conexion_id}/probar` | admin (JWT con rol admin) | Prueba la clave guardada contra el host oficial. |
| GET | `/api/v1/admin/historial-plan` | admin (JWT con rol admin) | Primer lector real de `HistorialPlan` — hasta ahora se escribía (`activar_codigo`, `gestionar_usuario`) pero nada la leía. |
| GET | `/api/v1/admin/ia/proveedores` | admin (JWT con rol admin) | Estado seguro de proveedores: nunca devuelve claves ni secretos. |
| POST | `/api/v1/admin/ia/proveedores` | admin (JWT con rol admin) | Escribe una clave en `.env` sin conservarla ni exponerla en logs o respuestas. |
| GET | `/api/v1/admin/intentos-login` | admin (JWT con rol admin) | Primer lector real de `IntentoLoginFallido` — útil para detectar patrones de fuerza bruta contra un username. |
| GET | `/api/v1/admin/jobs` | admin (JWT con rol admin) | `status` filtra opcionalmente por `pendiente`/`procesando`/`listo`/`error`; vacío = todos. |
| GET | `/api/v1/admin/laboratorio-pronosticos` | admin (JWT con rol admin) | Comparación interna por variante, fuente y liga. |
| POST | `/api/v1/admin/laboratorio-pronosticos` | admin (JWT con rol admin) | Ingresa una referencia autorizada al laboratorio, nunca al consenso del bot. |
| GET | `/api/v1/admin/laboratorio-pronosticos/partidos` | admin (JWT con rol admin) | Lista fixtures del bot ya disponibles para el formulario de referencias humanas. |
| POST | `/api/v1/admin/laboratorio-pronosticos/predicciones-humanas` | admin (JWT con rol admin) | Entrada exclusiva del administrador para pronósticos de amigos o analistas externos. |
| GET | `/api/v1/admin/sports/fuentes` | admin (JWT con rol admin) | Inventario seguro de fuentes deportivas. |
| POST | `/api/v1/admin/sports/fuentes/verificar` | admin (JWT con rol admin) | Prueba manual explícita; incluye la consulta que consume cuota de The Odds API. |
| GET | `/api/v1/admin/stats` | admin (JWT con rol admin) | Winrate real (no marketing, ver `.claude/rules/product-philosophy.md`) desde `AnalisisComparativo`/`Prediccion` — reusa `analisis_repo.leer_stats_aciertos`, la misma… |
| GET | `/api/v1/admin/usuarios` | admin (JWT con rol admin) | `q` busca por coincidencia parcial en `username` o `device_id`. |
| PATCH | `/api/v1/admin/usuarios/{device_id}/plan` | admin (JWT con rol admin) | Cambia `Usuario.plan` (free\|pro\|max — nunca `admin`, ese pseudo-valor ya no existe desde que `rol` se separó de `plan`, ver `admin_repo.PLANES_VALIDOS`). |
| PATCH | `/api/v1/admin/usuarios/{device_id}/rol` | admin (JWT con rol admin) | Cambia `Usuario.rol` (usuario\|admin\|agente) — v1.1, primer punto de escritura real del dashboard (ver docstring del módulo). |

## agent

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/agent/approvals` | sesión (JWT) | — |
| POST | `/api/v1/agent/approvals/{approval_id}/approve` | sesión (JWT) | — |
| POST | `/api/v1/agent/approvals/{approval_id}/reject` | sesión (JWT) | — |
| GET | `/api/v1/agent/capabilities` | sesión (JWT) | Qué ofrece el agente a ESTE usuario: modos, herramientas visibles para su rol, límites y versión del conocimiento. |
| POST | `/api/v1/agent/chat` | sesión (JWT) | — |
| GET | `/api/v1/agent/events` | sesión (JWT) | — |
| POST | `/api/v1/agent/feedback` | sesión (JWT) | — |
| GET | `/api/v1/agent/knowledge` | sesión (JWT) | — |
| GET | `/api/v1/agent/learning/feedback-stats` | sesión (JWT) | Agregado de feedback por herramienta y modo (solo administrador). |
| GET | `/api/v1/agent/learning/policies` | sesión (JWT) | — |
| POST | `/api/v1/agent/learning/policies/{policy_id}/rollback` | sesión (JWT) | — |
| GET | `/api/v1/agent/learning/proposals` | sesión (JWT) | — |
| POST | `/api/v1/agent/learning/proposals` | sesión (JWT) | — |
| POST | `/api/v1/agent/learning/proposals/{proposal_id}/review` | sesión (JWT) | — |
| GET | `/api/v1/agent/memory` | sesión (JWT) | — |
| POST | `/api/v1/agent/memory` | sesión (JWT) | — |
| GET | `/api/v1/agent/memory/export` | sesión (JWT) | — |
| DELETE | `/api/v1/agent/memory/{memory_id}` | sesión (JWT) | — |
| GET | `/api/v1/agent/memory/{memory_id}/history` | sesión (JWT) | — |
| GET | `/api/v1/agent/metrics` | sesión (JWT) | — |
| GET | `/api/v1/agent/providers` | sesión (JWT) | Catálogo seguro: muestra capacidad/configuración, nunca el valor de una credencial. |
| GET | `/api/v1/agent/runs` | sesión (JWT) | — |
| GET | `/api/v1/agent/search` | sesión (JWT) | Búsqueda FTS5 en SQLite con fallback textual portable. |
| GET | `/api/v1/agent/sessions` | sesión (JWT) | — |
| GET | `/api/v1/agent/sessions/{session_id}/messages` | sesión (JWT) | — |
| GET | `/api/v1/agent/subagents` | sesión (JWT) | — |
| GET | `/api/v1/agent/tasks` | sesión (JWT) | — |
| POST | `/api/v1/agent/tasks` | sesión (JWT) | — |
| GET | `/api/v1/agent/tasks/{task_id}` | sesión (JWT) | — |
| POST | `/api/v1/agent/tasks/{task_id}/cancel` | sesión (JWT) | — |
| GET | `/api/v1/agent/tools` | sesión (JWT) | Catálogo común que pueden consumir web, PWA, Android y Telegram. |
| GET | `/api/v1/agent/tools/invocations` | sesión (JWT) | — |
| POST | `/api/v1/agent/tools/{tool_name:path}` | sesión (JWT) | — |
| GET | `/api/v1/agent/usage` | sesión (JWT) | Cupo de IA restante del usuario (por minuto y por día) y tareas activas; solo lectura, no consume cupo. |

## app

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/deportivo` | app Android (`x-kairos-key`) | — |

## auth

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/auth/activar-codigo` | sesión (JWT) | Canjea un código `KS-PRO-XXXXXXX` / `KS-MAX-XXXXXXX` para el usuario autenticado por JWT (Web/PWA o App) y emite un nuevo JWT firmado con el `plan` actualizado. |
| POST | `/api/v1/auth/login` | público | — |
| POST | `/api/v1/auth/logout` | sesión (JWT) | Revoca el JWT actual (`jti` del token del header `Authorization`) — ver `db/tokens_repo.py`. |
| GET | `/api/v1/auth/me` | sesión (JWT) | Devuelve el estado real vigente del usuario autenticado por JWT (sincronizado con BD). |
| GET | `/api/v1/auth/me` | sesión (JWT) | Verifica el JWT del header `Authorization: Bearer <token>` y devuelve el usuario que representa — 401 si el token falta/expiró/es inválido/fue revocado (ver… |
| POST | `/api/v1/auth/registro` | público | — |

## deportivo

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/analisis` | público | Corre el motor completo (poisson + forma + h2h/odds/tabla si aplican + consenso) sobre un partido ya enriquecido con datos. |
| GET | `/api/v1/analisis/{partido_id}` | público | Último análisis guardado para un partido — reemplaza el core de `check_job` de WF-A2 para el caso 'ya hay resultado' (la cola de jobs asíncrona en sí, con Telegram/… |

## partidos

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/partidos` | público | `fecha` en formato yyyyMMdd (mismo formato que ya usa gateway_unificado.py/la app). |
| GET | `/api/v1/partidos/pronosticables` | público | Partidos programados del día que el bot SABE pronosticar (modelo histórico con la liga y los equipos), para que la web y la app ofrezcan primero lo que tendrá respuesta. |

## prediccion-web

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/prediccion-web` | sesión (JWT) | Análisis estadístico completo (sin IA) para un partido, listo para mostrar en la web. |

## resultados

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/resultados/verificar` | admin (JWT con rol admin) | — |

## scheduler

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| POST | `/api/v1/scheduler/colectar-resultados` | admin (JWT con rol admin) | Dispara a mano el colector diario de resultados (mismo código y mismo tope diario de peticiones que el cron: gasta cuota real de LiveScore6, hasta el tope). |
| POST | `/api/v1/scheduler/laplace-agents` | admin (JWT con rol admin) | Dispara a mano la auto-evaluación diaria (`services/laplace_agents.py`) — el sistema se analiza a sí mismo (ligas conocidas del día, sin IA) para no depender de que… |
| POST | `/api/v1/scheduler/reajustar-modelos` | admin (JWT con rol admin) | Dispara a mano el reajuste de los Dixon-Coles con resultados en vivo (mismo código que el cron semanal: exporta, reentrena, valida y reemplaza el artefacto solo si la… |
| POST | `/api/v1/scheduler/refresco-cuotas` | admin (JWT con rol admin) | Dispara a mano el refresco de odds/standings de hoy y mañana (mismo código y mismo tope diario que el cron de `main.py`: gasta cuota real de The Odds API, hasta el tope). |
| POST | `/api/v1/scheduler/resultados` | admin (JWT con rol admin) | Reemplaza el cron cada 2h + 07:00 de WF-E. |
| GET | `/api/v1/scheduler/status` | admin (JWT con rol admin) | Healthcheck real: ¿sigue vivo `AsyncIOScheduler` en este proceso?, y ¿cuándo fue la última corrida exitosa (automática o manual) de cada job? Un `/health` en 200 no… |
| POST | `/api/v1/scheduler/top-picks` | admin (JWT con rol admin) | Reemplaza el cron 9AM Chile de WF-D. |

## simulador

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/simulador/{liga_slug}` | público | Simula el resto de la temporada actual de `liga_slug` (uno de los slugs de `services/top_picks.py::LIGA_SLUG_POR_ID`, ej. |

## track-record

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/track-record` | público | Métricas reales del motor (winrate del pick final, Brier score y RPS del módulo Poisson, volumen real de datos verificados) — mismo cálculo honesto que `GET… |

## web-catalog

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/v1/web/agent-predictions` | sesión (JWT) | Variantes privadas del agente; nunca alimentan el consenso público por lectura. |
| GET | `/api/v1/web/fixtures` | público | — |
| GET | `/api/v1/web/history` | sesión (JWT) | — |
| GET | `/api/v1/web/history/accuracy` | sesión (JWT) | "Mis picks": acierto real de los pronósticos que consultó el usuario (solo partidos terminados con marcador). |
| GET | `/api/v1/web/top-picks` | público | Devuelve solamente picks ya guardados; jamás genera ni publica desde una lectura. |
