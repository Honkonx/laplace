# Herramientas del agente

El agente invoca al bot deportivo mediante herramientas con timeout, permisos, confirmación, reintentos y auditoría. Catálogo: `GET /api/v1/agent/tools`; ejecución: `POST /api/v1/agent/tools/{tool_name}`; historial: `GET /api/v1/agent/tools/invocations`.

| Herramienta | Tipo | Qué hace |
|---|---|---|
| `sports.list_leagues` | lectura | Ligas configuradas y su cobertura |
| `sports.list_fixtures` | lectura | Partidos, con filtros de fecha, liga y equipo |
| `sports.list_top_picks` | lectura | Top Picks ya publicados para una fecha |
| `sports.get_match` | lectura | Un partido por id o por equipos |
| `sports.predict` | lectura | Análisis estadístico completo de un partido |
| `sports.get_odds` | lectura | Cuotas disponibles en los datos del partido |
| `knowledge.team_profile` | lectura | Perfil de un equipo calculado del histórico |
| `knowledge.league_profile` | lectura | Tasas base, cobertura y frescura de una liga |
| `knowledge.glossary` | lectura | Definición de un término o pregunta frecuente |
| `sports.results` | admin + confirmación | Verifica resultados pendientes |
| `sports.top_picks` | admin + confirmación | Genera Top Picks y puede preparar su publicación |
| `sports.publish` | admin + confirmación | Publica Top Picks en el canal; exige además `publish=true` |

## Límites y reintentos
- Lecturas: caché de 15 s, timeout de 10 s y hasta 3 intentos ante error de red o 5xx.
- Análisis y acciones (POST): sin caché, timeout de 45 s y hasta 2 intentos; un timeout no se reintenta. Un 4xx nunca se reintenta.
- Tope de 60 solicitudes por minuto por proceso (todas las herramientas). Las predicciones además tienen un tope diario por usuario (`AGENT_PREDICCIONES_MAX_POR_DIA`, 15 por defecto).
- Resultados, errores, permisos y confirmaciones quedan en `agent_tool_invocations`.

## sports.capabilities
Consulta `SPORTS_BACKEND_URL/capabilities` con 2 s de timeout y suma lo que responda al turno. Si el bot no responde, registra `sports.route_unavailable` y continúa con memoria y reglas locales. Ninguna herramienta ejecuta shell ni código enviado por el usuario.

El chat sin IA reconoce consultas de ligas, partidos, predicciones y cuotas y las enruta a la herramienta correspondiente.
