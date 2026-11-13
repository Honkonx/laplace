# Referencia de la base de datos

> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).

59 tablas, tomadas de los modelos de SQLAlchemy (`backend/api/models/`). SQLite por defecto; PostgreSQL con `DATABASE_URL`. Las fechas se escriben siempre desde Python.

## `accion_admin_auditoria`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `actor_admin_id` | VARCHAR | no | — |
| `accion` | VARCHAR | no | — |
| `detalle` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_accion_admin_auditoria_actor_admin_id` (actor_admin_id)

## `agent_approvals`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `invocation_id` | VARCHAR(64) | sí | — |
| `user_id` | VARCHAR(255) | no | — |
| `tool_name` | VARCHAR(100) | no | — |
| `payload_json` | TEXT | no | — |
| `status` | VARCHAR(32) | no | — |
| `requested_en` | VARCHAR(32) | no | — |
| `decided_en` | VARCHAR(32) | sí | — |
| `decided_by` | VARCHAR(255) | sí | — |
| `note` | TEXT | sí | — |

Índices: `ix_agent_approvals_invocation_id` (invocation_id); `ix_agent_approvals_status` (status); `ix_agent_approvals_user_id` (user_id)

## `agent_events`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR(255) | no | — |
| `task_id` | VARCHAR(64) | sí | — |
| `run_id` | VARCHAR(64) | sí | — |
| `event_type` | VARCHAR(64) | no | — |
| `payload_json` | TEXT | no | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_events_event_type` (event_type); `ix_agent_events_run_id` (run_id); `ix_agent_events_task_id` (task_id); `ix_agent_events_user_id` (user_id)

## `agent_feedback`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR(255) | no | — |
| `run_id` | VARCHAR(64) | sí | — |
| `rating` | INTEGER | no | — |
| `label` | VARCHAR(64) | sí | — |
| `comment` | TEXT | sí | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_feedback_run_id` (run_id); `ix_agent_feedback_user_id` (user_id)

## `agent_knowledge`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `namespace` | VARCHAR(64) | no | — |
| `topic_key` | VARCHAR(255) | no | — |
| `content` | TEXT | no | — |
| `source` | VARCHAR(255) | no | — |
| `metadata_json` | TEXT | no | — |
| `creado_en` | VARCHAR(32) | no | — |
| `actualizado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_knowledge_namespace` (namespace); `ix_agent_knowledge_topic_key` (topic_key)

## `agent_learning_proposals`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `created_by` | VARCHAR(255) | no | — |
| `scope` | VARCHAR(32) | no | — |
| `topic_key` | VARCHAR(255) | no | — |
| `proposal_json` | TEXT | no | — |
| `status` | VARCHAR(32) | no | — |
| `review_note` | TEXT | sí | — |
| `creado_en` | VARCHAR(32) | no | — |
| `revisado_en` | VARCHAR(32) | sí | — |

## `agent_memories`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `agent_id` | VARCHAR(100) | no | — |
| `scope` | VARCHAR(32) | no | — |
| `owner_id` | VARCHAR(255) | sí | — |
| `kind` | VARCHAR(32) | no | — |
| `topic_key` | VARCHAR(255) | no | — |
| `content` | TEXT | no | — |
| `confidence` | FLOAT | no | — |
| `source` | VARCHAR(255) | no | — |
| `metadata_json` | TEXT | no | — |
| `activo` | INTEGER | no | — |
| `sensibilidad` | VARCHAR(32) | no | — |
| `expira_en` | VARCHAR(32) | sí | — |
| `creado_en` | VARCHAR(32) | no | — |
| `actualizado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_memories_agent_id` (agent_id); `ix_agent_memories_owner_id` (owner_id); `ix_agent_memories_scope` (scope); `ix_agent_memories_topic_key` (topic_key)

## `agent_memory_history`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `memory_id` | INTEGER | no | — |
| `owner_id` | VARCHAR(255) | sí | — |
| `action` | VARCHAR(32) | no | — |
| `before_json` | TEXT | no | — |
| `after_json` | TEXT | no | — |
| `changed_by` | VARCHAR(255) | no | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_memory_history_memory_id` (memory_id); `ix_agent_memory_history_owner_id` (owner_id)

## `agent_messages`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `session_id` | VARCHAR(64) | no | — |
| `user_id` | VARCHAR(255) | no | — |
| `role` | VARCHAR(32) | no | — |
| `content` | TEXT | no | — |
| `modo` | VARCHAR(32) | no | — |
| `herramienta` | VARCHAR(100) | sí | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_messages_session_id` (session_id); `ix_agent_messages_user_id` (user_id)

## `agent_policy_versions`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `scope` | VARCHAR(32) | no | — |
| `topic_key` | VARCHAR(255) | no | — |
| `version` | INTEGER | no | — |
| `status` | VARCHAR(32) | no | — |
| `content_json` | TEXT | no | — |
| `created_by` | VARCHAR(255) | no | — |
| `created_en` | VARCHAR(32) | no | — |
| `activated_en` | VARCHAR(32) | sí | — |
| `deactivated_en` | VARCHAR(32) | sí | — |

Índices: `ix_agent_policy_versions_scope` (scope); `ix_agent_policy_versions_status` (status); `ix_agent_policy_versions_topic_key` (topic_key)

## `agent_runs`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `session_id` | VARCHAR(64) | sí | — |
| `user_id` | VARCHAR(255) | no | — |
| `agent_name` | VARCHAR(100) | no | — |
| `status` | VARCHAR(32) | no | — |
| `input_json` | TEXT | no | — |
| `output_json` | TEXT | no | — |
| `creado_en` | VARCHAR(32) | no | — |
| `terminado_en` | VARCHAR(32) | sí | — |

Índices: `ix_agent_runs_session_id` (session_id); `ix_agent_runs_user_id` (user_id)

## `agent_sessions`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `user_id` | VARCHAR(255) | no | — |
| `channel` | VARCHAR(32) | no | — |
| `title` | VARCHAR(255) | sí | — |
| `status` | VARCHAR(32) | no | — |
| `creado_en` | VARCHAR(32) | no | — |
| `actualizado_en` | VARCHAR(32) | no | — |

Índices: `ix_agent_sessions_user_id` (user_id)

## `agent_tasks`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `parent_id` | VARCHAR(64) | sí | — |
| `user_id` | VARCHAR(255) | no | — |
| `kind` | VARCHAR(100) | no | — |
| `status` | VARCHAR(32) | no | — |
| `input_json` | TEXT | no | — |
| `output_json` | TEXT | no | — |
| `error` | TEXT | sí | — |
| `creado_en` | VARCHAR(32) | no | — |
| `iniciado_en` | VARCHAR(32) | sí | — |
| `terminado_en` | VARCHAR(32) | sí | — |
| `cancel_requested` | INTEGER | no | — |
| `attempt_count` | INTEGER | no | — |
| `max_attempts` | INTEGER | no | — |
| `timeout_seconds` | INTEGER | no | — |
| `idempotency_key` | VARCHAR(255) | sí | — |

Índices: `ix_agent_tasks_idempotency_key` (idempotency_key); `ix_agent_tasks_parent_id` (parent_id); `ix_agent_tasks_user_id` (user_id)

## `agent_tool_invocations`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | VARCHAR(64) | no | PK |
| `user_id` | VARCHAR(255) | no | — |
| `tool_name` | VARCHAR(100) | no | — |
| `status` | VARCHAR(32) | no | — |
| `input_json` | TEXT | no | — |
| `output_json` | TEXT | no | — |
| `error` | TEXT | sí | — |
| `creado_en` | VARCHAR(32) | no | — |
| `terminado_en` | VARCHAR(32) | sí | — |

Índices: `ix_agent_tool_invocations_tool_name` (tool_name); `ix_agent_tool_invocations_user_id` (user_id)

## `agent_uso_diario`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `clave` | VARCHAR(255) | no | PK |
| `dia` | VARCHAR(10) | no | PK |
| `usos` | INTEGER | no | — |

## `analisis_comparativo`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `partido_id` | VARCHAR | no | — |
| `fecha` | VARCHAR | no | — |
| `local` | TEXT | sí | — |
| `visitante` | TEXT | sí | — |
| `liga` | TEXT | sí | — |
| `pick_python` | TEXT | sí | — |
| `prob_local_py` | FLOAT | sí | — |
| `prob_empate_py` | FLOAT | sí | — |
| `prob_visit_py` | FLOAT | sí | — |
| `score_py` | INTEGER | sí | — |
| `pick_claude` | TEXT | sí | — |
| `pick_externo` | TEXT | sí | — |
| `pick_final` | TEXT | sí | — |
| `fuentes_disp` | INTEGER | sí | — |
| `consenso` | TEXT | sí | — |
| `score_final` | INTEGER | sí | — |
| `confianza` | TEXT | sí | — |
| `peso_python` | FLOAT | sí | — |
| `peso_ia` | FLOAT | sí | — |
| `resultado_real` | TEXT | sí | — |
| `pick_correcto` | INTEGER | sí | — |
| `creado_en` | TEXT | no | — |
| `hora_kickoff` | TEXT | sí | — |
| `goles_local` | INTEGER | sí | — |
| `goles_visitante` | INTEGER | sí | — |
| `status_partido` | TEXT | sí | — |
| `pick_form` | TEXT | sí | — |
| `score_form` | INTEGER | sí | — |
| `pick_python_correcto` | INTEGER | sí | — |
| `pick_claude_correcto` | INTEGER | sí | — |
| `pick_form_correcto` | INTEGER | sí | — |
| `pick_h2h` | TEXT | sí | — |
| `pick_odds` | TEXT | sí | — |
| `pick_tabla` | TEXT | sí | — |
| `score_poisson` | INTEGER | sí | — |
| `score_forma` | INTEGER | sí | — |
| `score_h2h` | INTEGER | sí | — |
| `score_odds` | INTEGER | sí | — |
| `score_tabla` | INTEGER | sí | — |
| `consenso_nivel` | TEXT | sí | — |
| `coinciden_modulos` | INTEGER | sí | — |
| `total_modulos` | INTEGER | sí | — |
| `bloque_claude_json` | TEXT | sí | — |
| `pick_externo_score` | FLOAT | sí | — |
| `fuente_externo` | TEXT | sí | — |
| `pick_externo_detalle` | TEXT | sí | — |
| `pick_h2h_correcto` | INTEGER | sí | — |
| `pick_odds_correcto` | INTEGER | sí | — |
| `pick_tabla_correcto` | INTEGER | sí | — |
| `pick_externo_correcto` | INTEGER | sí | — |
| `over25_pred` | FLOAT | sí | — |
| `over25_real` | INTEGER | sí | — |
| `over25_correcto` | INTEGER | sí | — |
| `btts_pred` | FLOAT | sí | — |
| `btts_real` | INTEGER | sí | — |
| `btts_correcto` | INTEGER | sí | — |

Índices: `ix_analisis_comparativo_fecha` (fecha); `ix_analisis_comparativo_partido_id` (partido_id)

## `analisis_individuales`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `partido_id` | VARCHAR | no | — |
| `pick_final` | TEXT | no | — |
| `confianza` | TEXT | sí | — |
| `score_final` | INTEGER | sí | — |
| `texto_completo` | TEXT | no | — |
| `creado_en` | TEXT | no | — |
| `fuente` | VARCHAR | no | — |

## `analisis_modulos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `partido_id` | VARCHAR | no | — |
| `job_id` | TEXT | sí | — |
| `modulo` | VARCHAR | no | — |
| `pick` | TEXT | sí | — |
| `prob_local` | FLOAT | sí | — |
| `prob_empate` | FLOAT | sí | — |
| `prob_visitante` | FLOAT | sí | — |
| `score` | INTEGER | sí | — |
| `confianza` | TEXT | sí | — |
| `datos_json` | TEXT | sí | — |
| `pick_correcto` | INTEGER | sí | — |
| `creado_en` | TEXT | no | — |

## `bot_avisos_enviados`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR(64) | no | — |
| `partido_id` | VARCHAR(64) | no | — |
| `tipo` | VARCHAR(10) | no | — |
| `pronostico_json` | TEXT | sí | — |
| `enviado_en` | VARCHAR(32) | no | — |

Índices: `ix_bot_avisos_enviados_user_id` (user_id)

## `bot_consentimientos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `user_id` | VARCHAR(64) | no | PK |
| `version` | VARCHAR(16) | no | — |
| `aceptado_en` | VARCHAR(32) | no | — |
| `revocado_en` | VARCHAR(32) | sí | — |

## `bot_historial_consultas`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR(64) | no | — |
| `partido_id` | VARCHAR(64) | no | — |
| `fecha_partido` | VARCHAR(16) | sí | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_bot_historial_consultas_user_id` (user_id)

## `bot_perfil_usuario`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `user_id` | VARCHAR(64) | no | PK |
| `zona_horaria` | VARCHAR(40) | sí | — |
| `estilo` | VARCHAR(12) | sí | — |
| `mercados` | VARCHAR(80) | sí | — |
| `actualizado_en` | VARCHAR(32) | no | — |

## `bot_preferencias`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `user_id` | VARCHAR(64) | no | PK |
| `equipos_favoritos` | TEXT | sí | — |
| `idioma` | VARCHAR(8) | no | — |
| `personalizar` | INTEGER | no | — |
| `avisos` | INTEGER | no | defecto `0` |
| `actualizado_en` | VARCHAR(32) | no | — |

## `cache_consenso`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `partido_id` | VARCHAR | no | único |
| `pick_consenso` | TEXT | no | — |
| `texto_consenso` | TEXT | no | — |
| `total_analisis` | INTEGER | no | — |
| `usos` | INTEGER | no | — |
| `max_usos` | INTEGER | no | — |
| `expira_en` | TEXT | no | — |
| `creado_en` | TEXT | no | — |
| `tipo_consenso` | VARCHAR | no | — |

## `cache_predicciones`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `input_hash` | VARCHAR | no | único |
| `respuesta_json` | TEXT | no | — |
| `partido_id` | VARCHAR | no | — |
| `expira_en` | TEXT | no | — |
| `hits` | INTEGER | no | — |
| `creado_en` | TEXT | no | — |

## `codigos_acceso`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `codigo` | VARCHAR | no | único |
| `plan` | VARCHAR | no | — |
| `dias` | INTEGER | no | — |
| `usado` | INTEGER | no | — |
| `device_id_asignado` | TEXT | sí | — |
| `device_id_usado` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |
| `usado_en` | TEXT | sí | — |

## `consenso_ia_validacion`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `partido_id` | VARCHAR | no | PK |
| `pick_ia` | TEXT | no | — |
| `confianza_ia` | TEXT | sí | — |
| `score_ia` | INTEGER | sí | — |
| `texto_ia` | TEXT | no | — |
| `primer_usuario_id` | TEXT | no | — |
| `segundo_usuario_id` | TEXT | sí | — |
| `usuarios_confirmaron` | INTEGER | no | — |
| `validado` | INTEGER | no | — |
| `creado_en` | TEXT | no | — |
| `actualizado_en` | TEXT | no | — |
| `expira_en` | TEXT | no | — |

## `estado_fuentes_deportivas`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `fuente` | VARCHAR(64) | no | PK |
| `configurada` | INTEGER | no | — |
| `saludable` | INTEGER | no | — |
| `status_http` | INTEGER | sí | — |
| `latencia_ms` | FLOAT | sí | — |
| `cuota_restante` | VARCHAR(64) | sí | — |
| `detalle` | TEXT | sí | — |
| `verificado_en` | VARCHAR | no | — |

Índices: `ix_estado_fuentes_deportivas_verificado_en` (verificado_en)

## `experimentos_pronostico`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `codigo` | VARCHAR(96) | no | — |
| `nombre` | TEXT | no | — |
| `tipo` | VARCHAR(32) | no | — |
| `estado` | VARCHAR(32) | no | — |
| `version` | VARCHAR(96) | no | — |
| `permite_consenso` | INTEGER | no | — |
| `descripcion` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |
| `actualizado_en` | TEXT | no | — |

Índices: `ix_experimentos_pronostico_codigo` (codigo)

## `fixture_id_cache`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `match_id` | VARCHAR | no | PK |
| `fecha` | VARCHAR | no | — |
| `apifootball_fixture_id` | TEXT | sí | — |
| `league_id` | INTEGER | sí | — |
| `season` | INTEGER | sí | — |
| `team_home_id` | INTEGER | sí | — |
| `team_away_id` | INTEGER | sí | — |
| `creado_en` | TEXT | no | — |

## `historial_plan`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `device_id` | VARCHAR | no | — |
| `plan_anterior` | VARCHAR | sí | — |
| `plan_nuevo` | VARCHAR | no | — |
| `medio` | VARCHAR | no | — |
| `detalle` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_historial_plan_device_id` (device_id)

## `historial_predicciones_web`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR | no | — |
| `partido_id` | VARCHAR | no | — |
| `fecha` | VARCHAR | no | — |
| `liga` | TEXT | sí | — |
| `local` | TEXT | sí | — |
| `visitante` | TEXT | sí | — |
| `pick` | TEXT | sí | — |
| `confianza` | TEXT | sí | — |
| `resultado_json` | TEXT | no | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_historial_predicciones_web_partido_id` (partido_id); `ix_historial_predicciones_web_user_id` (user_id)

## `intento_login_fallido`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `username_intentado` | VARCHAR | no | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_intento_login_fallido_username_intentado` (username_intentado)

## `jobs`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `job_id` | VARCHAR | no | único |
| `match_id` | VARCHAR | no | — |
| `fecha_partido` | VARCHAR | no | — |
| `chat_id` | VARCHAR | no | — |
| `origen` | VARCHAR | no | — |
| `status` | VARCHAR | no | — |
| `intentos` | INTEGER | no | — |
| `creado_en` | TEXT | no | — |
| `completado_en` | TEXT | sí | — |
| `user_id` | TEXT | sí | — |
| `plan` | VARCHAR | no | — |
| `device_id_app` | TEXT | sí | — |
| `resultado_app` | TEXT | sí | — |
| `local_app` | TEXT | sí | — |
| `visitante_app` | TEXT | sí | — |
| `liga_app` | TEXT | sí | — |

Índices: `ix_jobs_device_id_app_status` (device_id_app, status); `ix_jobs_match_id` (match_id)

## `laplace_agent_memoria`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `fecha` | VARCHAR | no | — |
| `tipo_evento` | VARCHAR | no | — |
| `resumen` | TEXT | no | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_laplace_agent_memoria_fecha` (fecha); `ix_laplace_agent_memoria_tipo_evento` (tipo_evento)

## `metricas_ia_proveedor`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `proveedor` | VARCHAR | no | — |
| `modelo` | TEXT | sí | — |
| `exitoso` | INTEGER | no | — |
| `latencia_ms` | FLOAT | no | — |
| `error` | TEXT | sí | — |
| `creado_en` | VARCHAR | no | — |

Índices: `ix_metricas_ia_proveedor_creado_en` (creado_en); `ix_metricas_ia_proveedor_proveedor` (proveedor)

## `ml_conjuntos_datos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `nombre` | VARCHAR(120) | no | — |
| `version` | VARCHAR(40) | no | — |
| `hash_datos` | VARCHAR(64) | sí | — |
| `procedencia` | VARCHAR(12) | no | — |
| `desde` | VARCHAR(10) | sí | — |
| `hasta` | VARCHAR(10) | sí | — |
| `filas` | INTEGER | no | — |
| `ruta` | TEXT | sí | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_conjuntos_datos_nombre` (nombre)

## `ml_entrenamientos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `conjunto_id` | INTEGER | no | — |
| `familia` | VARCHAR(40) | no | — |
| `semilla` | INTEGER | no | — |
| `parametros_json` | TEXT | no | — |
| `commit_codigo` | VARCHAR(40) | sí | — |
| `estado` | VARCHAR(12) | no | — |
| `error` | TEXT | sí | — |
| `inicio` | VARCHAR(32) | sí | — |
| `fin` | VARCHAR(32) | sí | — |

Índices: `ix_ml_entrenamientos_conjunto_id` (conjunto_id); `ix_ml_entrenamientos_estado` (estado)

## `ml_errores`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `modelo_id` | INTEGER | no | — |
| `partido_id` | VARCHAR(64) | no | — |
| `liga` | VARCHAR(120) | no | — |
| `fecha` | VARCHAR(10) | no | — |
| `p_local` | FLOAT | no | — |
| `p_empate` | FLOAT | no | — |
| `p_visitante` | FLOAT | no | — |
| `resultado` | VARCHAR(1) | no | — |
| `rps` | FLOAT | no | — |
| `log_loss` | FLOAT | no | — |
| `tramo` | VARCHAR(8) | no | — |
| `acierto` | INTEGER | no | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_errores_modelo_id` (modelo_id)

## `ml_estado_vivo`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `modelo_id` | INTEGER | no | — |
| `liga` | VARCHAR(40) | no | — |
| `estado_json` | TEXT | no | — |
| `hasta_dia` | INTEGER | no | — |
| `partidos` | INTEGER | no | — |
| `actualizado_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_estado_vivo_modelo_id` (modelo_id)

## `ml_evaluaciones`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `modelo_id` | INTEGER | no | — |
| `ventana_desde` | VARCHAR(10) | sí | — |
| `ventana_hasta` | VARCHAR(10) | sí | — |
| `n` | INTEGER | no | — |
| `log_loss` | FLOAT | sí | — |
| `brier` | FLOAT | sí | — |
| `rps` | FLOAT | sí | — |
| `ece` | FLOAT | sí | — |
| `cobertura` | FLOAT | sí | — |
| `referencias_json` | TEXT | sí | — |
| `origen` | VARCHAR(12) | no | — |
| `creada_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_evaluaciones_modelo_id` (modelo_id)

## `ml_modelos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `nombre` | VARCHAR(80) | no | — |
| `version` | VARCHAR(60) | no | — |
| `familia` | VARCHAR(40) | no | — |
| `tarea` | VARCHAR(40) | no | — |
| `artefacto_ruta` | TEXT | sí | — |
| `artefacto_sha256` | VARCHAR(64) | sí | — |
| `estado` | VARCHAR(12) | no | — |
| `metricas_json` | TEXT | sí | — |
| `entrenamiento_id` | INTEGER | sí | — |
| `promovido_por` | VARCHAR(80) | sí | — |
| `creado_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_modelos_estado` (estado); `ux_ml_modelos_nombre_version` (nombre, version, único)

## `ml_muestras`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `conjunto_id` | INTEGER | no | — |
| `simulacion_id` | INTEGER | sí | — |
| `partido_id` | VARCHAR(64) | sí | — |
| `procedencia` | VARCHAR(12) | no | — |
| `peso` | FLOAT | no | — |
| `fecha_evento` | VARCHAR(10) | sí | — |
| `caracteristicas_json` | TEXT | no | — |
| `etiqueta_json` | TEXT | sí | — |
| `hash_muestra` | VARCHAR(64) | no | — |
| `creada_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_muestras_conjunto_fecha` (conjunto_id, fecha_evento); `ix_ml_muestras_simulacion_id` (simulacion_id)

## `ml_predicciones`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `modelo_id` | INTEGER | no | — |
| `partido_id` | VARCHAR(64) | sí | — |
| `entrada_json` | TEXT | no | — |
| `probabilidades_json` | TEXT | no | — |
| `goles_json` | TEXT | sí | — |
| `confianza` | FLOAT | sí | — |
| `latencia_ms` | FLOAT | sí | — |
| `canal` | VARCHAR(12) | no | — |
| `creada_en` | VARCHAR(32) | no | — |
| `hash_previo` | VARCHAR(64) | sí | — |
| `hash_fila` | VARCHAR(64) | sí | — |

Índices: `ix_ml_predicciones_modelo_fecha` (modelo_id, creada_en); `ix_ml_predicciones_partido_id` (partido_id)

## `ml_simulaciones`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `conjunto_id` | INTEGER | sí | — |
| `grupo` | VARCHAR(120) | sí | — |
| `semilla` | INTEGER | no | — |
| `parametros_json` | TEXT | no | — |
| `tipo` | VARCHAR(12) | no | — |
| `version_generador` | VARCHAR(40) | no | — |
| `generada_en` | VARCHAR(32) | no | — |

Índices: `ix_ml_simulaciones_conjunto_id` (conjunto_id); `ix_ml_simulaciones_grupo` (grupo)

## `partidos_dia`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `fecha` | VARCHAR | no | PK |
| `match_id` | VARCHAR | no | PK |
| `liga_slug` | TEXT | sí | — |
| `liga_nombre` | TEXT | sí | — |
| `liga_codigo` | TEXT | sí | — |
| `liga_pais` | TEXT | sí | — |
| `liga_logo` | TEXT | sí | — |
| `local` | TEXT | sí | — |
| `visitante` | TEXT | sí | — |
| `hora_chile` | TEXT | sí | — |
| `logo_local` | TEXT | sí | — |
| `logo_visitante` | TEXT | sí | — |
| `status` | VARCHAR | no | — |
| `goles_local` | INTEGER | sí | — |
| `goles_visitante` | INTEGER | sí | — |
| `creado_en` | TEXT | sí | — |
| `kick_off_utc` | TEXT | sí | — |
| `cache_invalidado` | INTEGER | no | — |
| `apifootball_fixture_id` | TEXT | sí | — |

## `predicciones`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `partido_id` | VARCHAR | no | — |
| `fuente` | VARCHAR | no | — |
| `pick` | TEXT | sí | — |
| `confianza` | TEXT | sí | — |
| `confianza_score` | INTEGER | sí | — |
| `razonamiento` | TEXT | sí | — |
| `texto_completo` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |
| `pick_correcto` | INTEGER | sí | — |

## `predicciones_usuario`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `match_id` | VARCHAR | no | — |
| `telegram_user_id` | VARCHAR | no | — |
| `pick` | VARCHAR | no | — |
| `razon` | TEXT | sí | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_predicciones_usuario_match_id` (match_id)

## `predicciones_variantes_agente`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `user_id` | VARCHAR | no | — |
| `session_id` | VARCHAR(64) | sí | — |
| `partido_id` | VARCHAR | sí | — |
| `fecha` | VARCHAR | no | — |
| `liga` | TEXT | sí | — |
| `local` | TEXT | no | — |
| `visitante` | TEXT | no | — |
| `via` | VARCHAR(32) | no | — |
| `pick` | TEXT | sí | — |
| `marcador_probable` | TEXT | sí | — |
| `confianza` | TEXT | sí | — |
| `proveedor` | VARCHAR(64) | sí | — |
| `modelo` | VARCHAR(255) | sí | — |
| `prompt_version` | VARCHAR(64) | sí | — |
| `respuesta_cruda` | TEXT | no | — |
| `resultado_json` | TEXT | no | — |
| `resultado_real` | TEXT | sí | — |
| `pick_correcto` | INTEGER | sí | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_predicciones_variantes_agente_partido_id` (partido_id); `ix_predicciones_variantes_agente_session_id` (session_id); `ix_predicciones_variantes_agente_user_id` (user_id)

## `pronosticos_experimentales`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `experimento_codigo` | VARCHAR(96) | no | — |
| `partido_id` | VARCHAR | no | — |
| `fecha_partido` | VARCHAR | no | — |
| `hora_kickoff` | TEXT | sí | — |
| `liga` | TEXT | sí | — |
| `local` | TEXT | no | — |
| `visitante` | TEXT | no | — |
| `fuente` | VARCHAR(96) | no | — |
| `variante` | VARCHAR(96) | no | — |
| `modelo_version` | VARCHAR(255) | sí | — |
| `prompt_version` | VARCHAR(96) | sí | — |
| `corte_datos_en` | TEXT | no | — |
| `input_hash` | VARCHAR(128) | sí | — |
| `datos_json` | TEXT | no | — |
| `respuesta_cruda` | TEXT | sí | — |
| `pick` | TEXT | sí | — |
| `prob_local` | FLOAT | sí | — |
| `prob_empate` | FLOAT | sí | — |
| `prob_visitante` | FLOAT | sí | — |
| `marcador_probable` | TEXT | sí | — |
| `goles_local_esperados` | FLOAT | sí | — |
| `goles_visitante_esperados` | FLOAT | sí | — |
| `rango_goles_total` | TEXT | sí | — |
| `prob_empate_90` | FLOAT | sí | — |
| `resultado_real` | TEXT | sí | — |
| `goles_local_real` | INTEGER | sí | — |
| `goles_visitante_real` | INTEGER | sí | — |
| `pick_correcto` | INTEGER | sí | — |
| `brier_score` | FLOAT | sí | — |
| `log_loss` | FLOAT | sí | — |
| `rps` | FLOAT | sí | — |
| `creado_en` | TEXT | no | — |

Índices: `ix_pronosticos_experimentales_corte_datos_en` (corte_datos_en); `ix_pronosticos_experimentales_experimento_codigo` (experimento_codigo); `ix_pronosticos_experimentales_fecha_partido` (fecha_partido); `ix_pronosticos_experimentales_fuente` (fuente); `ix_pronosticos_experimentales_liga` (liga); `ix_pronosticos_experimentales_partido_id` (partido_id); `ix_pronosticos_experimentales_variante` (variante)

## `push_tokens`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `device_id` | VARCHAR | no | PK |
| `expo_push_token` | TEXT | no | — |
| `platform` | VARCHAR | no | — |
| `creado_en` | TEXT | no | — |
| `actualizado_en` | TEXT | no | — |

## `recomendaciones_dia`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `fixture_id` | VARCHAR | no | — |
| `local` | TEXT | no | — |
| `visitante` | TEXT | no | — |
| `liga` | TEXT | no | — |
| `hora_chile` | TEXT | sí | — |
| `fecha` | VARCHAR | no | — |
| `creado_en` | TEXT | no | — |

## `resultados_partidos`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `fixture_id` | VARCHAR | no | único |
| `local` | TEXT | sí | — |
| `visitante` | TEXT | sí | — |
| `liga` | TEXT | sí | — |
| `goles_local` | INTEGER | sí | — |
| `goles_visitante` | INTEGER | sí | — |
| `ganador` | TEXT | sí | — |
| `status_api` | TEXT | sí | — |
| `fecha_partido` | TEXT | sí | — |
| `hora_kickoff` | TEXT | sí | — |
| `actualizado_en` | TEXT | no | — |

## `scheduler_runs`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `job_name` | VARCHAR | no | — |
| `ejecutado_en` | TEXT | no | — |
| `ok` | BOOLEAN | no | — |
| `detalle` | TEXT | sí | — |

Índices: `ix_scheduler_runs_job_name` (job_name)

## `stats_cache`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `cache_key` | VARCHAR | no | PK |
| `tipo` | VARCHAR | no | — |
| `datos_json` | TEXT | no | — |
| `creado_en` | TEXT | no | — |
| `expira_en` | TEXT | no | — |
| `veces_confirmado` | INTEGER | no | — |
| `ultima_confirmacion_en` | TEXT | sí | — |

## `token_revocado`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `jti` | VARCHAR | no | único |
| `device_id` | VARCHAR | no | — |
| `revocado_en` | TEXT | no | — |

Índices: `ix_token_revocado_jti` (jti, único)

## `uso_diario_app`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `device_id` | VARCHAR | no | PK |
| `fecha` | VARCHAR | no | PK |
| `predicciones_usadas` | INTEGER | no | — |

## `uso_diario_ia_app`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `device_id` | VARCHAR | no | PK |
| `fecha` | VARCHAR | no | PK |
| `usados` | INTEGER | no | — |

## `usuarios`

| Columna | Tipo | Nulo | Clave / valor por defecto |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `device_id` | VARCHAR | no | único |
| `activo` | INTEGER | no | — |
| `plan` | VARCHAR | no | — |
| `creado_en` | TEXT | no | — |
| `nickname` | TEXT | sí | — |
| `activo_hasta` | TEXT | sí | — |
| `origen` | VARCHAR | no | — |
| `username` | VARCHAR | sí | único |
| `password_hash` | TEXT | sí | — |
| `favoritos_ligas` | TEXT | sí | — |
| `rol` | VARCHAR | no | — |
| `terms_version` | VARCHAR | sí | — |
| `terms_accepted_at` | TEXT | sí | — |
