# Configuración (`.env`)

El instalador crea `.env` a partir de `.env.example`. **Nunca se sube a git ni se muestra en pantalla.** Lo normal es **no editarlo a mano**: `configurar` (o la pantalla *Administración → Conexiones* de la web) detecta y prueba cada clave y la escribe por ti. Todas las claves son opcionales, pero sin cuotas ni modelo histórico propio los partidos quedan sin pronóstico propio (ver [motor](motor-de-pronostico.md)).

## Secretos propios (los genera el instalador)
| Clave | Para qué |
|---|---|
| `KAIROS_AUTH_SECRET` | secreto compartido entre la app Android y el backend (cabecera `x-kairos-key`); nunca va en la web |
| `WEB_JWT_SECRET` | firma las sesiones de la web (JWT) |

## Telegram
| Clave | Para qué |
|---|---|
| `TELEGRAM_BOT_TOKEN` | bot principal (@BotFather). Sin él, el bot no arranca; la web y el agente sí |
| `AGENT_TELEGRAM_BOT_TOKEN` | bot del agente (otro bot de @BotFather) |
| `SPORTS_ADMIN_IDS` | tu id numérico de Telegram como administrador (varios, separados por coma) |
| `TELEGRAM_CANAL_ID`, `TELEGRAM_GRUPO_URL` | canal y grupo de la comunidad; vacíos = no se publican ni se muestran |

## IA (cascada: se usa la primera que responda)
`OLLAMA_API_KEY` (Ollama Cloud, modelo `gpt-oss:120b`), `GROQ_API_KEY`, `GOOGLE_API_KEY` (Gemini), `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`. El orden por rol se cambia con `AI_ROUTING_BOT`, `AI_ROUTING_CANAL`, `AI_ROUTING_AGENTE` y `AI_ROUTING_LABORATORIO`. La IA solo explica y contrasta; no produce probabilidades.

## Fuentes de datos
| Clave | Fuente | Para qué |
|---|---|---|
| `SPORTS_API_KEY` | api-football | calendario, H2H (el plan gratis solo cubre algunas temporadas) |
| `THE_ODDS_API_KEY` | The Odds API | cuotas |
| `FOOTBALL_DATA_KEY` | football-data.org | tablas de posiciones |
| `LIVESCORE6_KEY` | LiveScore6 (RapidAPI) | calendario del día |
| `BSD_API_KEY` | BSD | predicciones externas |
`laplace doctor` dice cuántas fuentes tienen clave. Cada proveedor tiene su propio plan y términos ([seguridad y datos](seguridad-y-datos.md)).

## Servidor
`DATABASE_URL` (por defecto SQLite en `backend/db/`; si no contiene «sqlite» se asume Postgres), `CORS_ORIGINS` (orígenes de la web), `WEB_JWT_EXPIRA_HORAS`, `LAPLACE_PUERTO_BACKEND`, `LAPLACE_PUERTO_AGENTE`.
