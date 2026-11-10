# Bot de Telegram del agente

Usa `AGENT_TELEGRAM_BOT_TOKEN`, distinto del token del bot deportivo. Sin token, el resto del backend funciona igual. Los mensajes y sesiones se guardan con `user_id=telegram:<id>`.

## Acceso
El agente responde a **todos** los usuarios de Telegram; los privilegios son solo del administrador (`SPORTS_ADMIN_IDS`).
- `AGENT_TELEGRAM_BLOCKED_IDS`: ids vetados (tiene prioridad).
- `AGENT_TELEGRAM_ALLOWED_IDS`: si tiene valores, solo esos ids y los administradores.
- `AGENT_TELEGRAM_RATE_PER_MIN`: mensajes por minuto y por chat (10 por defecto; el administrador tiene un tope mayor).
- Topes de IA: `AGENT_IA_MAX_POR_MINUTO` y `AGENT_IA_MAX_POR_DIA`.

## Comandos
| Comando | Quién | Qué hace |
|---|---|---|
| `/start`, `/ayuda` | todos | Alcance y ayuda |
| `/ia <consulta>` | todos | Pide IA para una consulta dentro del alcance |
| `/estado` | todos | Últimas tareas y cantidad de memoria privada |
| `/partidos`, `/ligas`, `/top` | todos | Partidos, cobertura de ligas y Top Picks publicados |
| `/predecir A vs B` | todos | Pronóstico de un partido |
| `/panel`, `/fuentes` | admin | Panel del sistema y salud de las fuentes |
| `/resultados`, `/toppicks`, `/publicar confirmo` | admin | Acciones con efectos (la publicación pide confirmación explícita) |
| `/aprobaciones` | admin | Aprobaciones pendientes |
| `/decidir <id> aprobar` | admin | Aprueba; **cualquier otro valor, o ninguno, rechaza** |
