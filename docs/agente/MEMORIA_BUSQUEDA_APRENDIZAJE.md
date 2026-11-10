# Memoria, búsqueda y aprendizaje controlado

## Capas persistentes
- `agent_messages`: todos los turnos del chat (sesión, usuario, rol, texto, modo y herramienta); el canal vive en `agent_sessions`.
- `agent_memories`: recuerdos clasificados por `scope`, propietario, confianza, fuente, sensibilidad y vencimiento.
- `agent_knowledge`: los JSON declarativos de `backend/knowledge/`, sin duplicar entradas.
- `agent_feedback`: valoración, etiqueta y comentario sobre ejecuciones.
- `agent_learning_proposals`: propuestas pendientes de revisión administrativa.

## Contratos
- `GET /api/v1/agent/search?q=...`: busca en mensajes propios, memorias visibles y conocimiento.
- `POST /api/v1/agent/memory`: crea memoria de usuario; `scope=global` exige administrador.
- `POST /api/v1/agent/feedback`: guarda feedback, opcionalmente ligado a un `run_id` propio.
- `POST` y `GET /api/v1/agent/learning/proposals`: crea o lista propuestas (propias, o todas para el administrador).
- `POST /api/v1/agent/learning/proposals/{id}/review`: aprueba o rechaza y deja trazabilidad.

La búsqueda usa FTS5 con triggers en SQLite y un fallback textual (`sql-like`) en otros motores. El aislamiento por usuario no depende del motor de búsqueda.

## Regla de aprendizaje
El agente registra evidencia y propone cambios. Una propuesta aprobada crea una política versionada (`agent_policy_versions`) que se incorpora al prompt; no modifica skills, reglas ni código por su cuenta.
