# IA: proveedores, orden y roles

La IA explica y contrasta; no produce probabilidades. Todo el acceso pasa por `services/ai_client.py` (REST directo con `httpx`, sin SDK de cada proveedor).

## Proveedores
| Id | Se activa con | Modelo (variable) | Por defecto |
|---|---|---|---|
| `gemini` | `GOOGLE_API_KEY` | `GEMINI_MODEL` | `gemini-flash-lite-latest` |
| `groq` | `GROQ_API_KEY` | `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `ollama_cloud` | `OLLAMA_API_KEY` | `OLLAMA_CLOUD_MODEL` | `gpt-oss:120b` |
| `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` |
| `claude` | `ANTHROPIC_API_KEY` | `CLAUDE_MODEL` | `claude-sonnet-4-6` |

Un proveedor sin clave o sin modelo se salta solo. Las claves se leen únicamente del `.env`; ninguna pantalla ni endpoint las devuelve (`configurar` y el panel «Conexiones» solo permiten reemplazarlas o borrarlas).

## Orden por rol
Cada llamada declara un rol y se prueba en el orden de ese rol hasta que uno responde; si todos fallan, el que llama degrada a «solo estadístico».

| Rol | Uso | Orden por defecto |
|---|---|---|
| `bot` | Análisis de partido en Telegram y la app | gemini → groq → ollama_cloud → openrouter → claude |
| `canal` | Top Picks | gemini → groq → ollama_cloud → openrouter → claude |
| `laboratorio` | `ia_simple` | gemini → groq → ollama_cloud → openrouter → claude |
| `agente` | Chat del agente | ollama_cloud → groq → gemini → openrouter → claude |

Se cambia con `AI_ROUTING_BOT`, `AI_ROUTING_CANAL`, `AI_ROUTING_AGENTE` y `AI_ROUTING_LABORATORIO` (lista separada por comas, o desde `configurar` → «o»). Un nombre desconocido se ignora con un aviso; una lista vacía o sin nombres válidos vuelve al orden por defecto.

## Ollama Cloud
`POST https://ollama.com/api/chat` con `Authorization: Bearer <OLLAMA_API_KEY>`, timeout de 30 s. Los modelos «thinking» devuelven el razonamiento aparte: se usa solo `message.content`, y `num_predict` tiene un mínimo de 1024 para que el razonamiento no agote la respuesta. `OLLAMA_LOCAL_URL` y `OLLAMA_LOCAL_MODEL` se conservan únicamente para que un `.env` antiguo cargue: el enrutador no los usa.

## Seguridad al arrancar
`validar_secretos_arranque` comprueba que `KAIROS_AUTH_SECRET` y `WEB_JWT_SECRET` no estén vacíos, en su valor por defecto ni tengan menos de 32 caracteres. Con `ENV` distinto de `local` el backend no arranca; en local avisa. El mensaje nombra la variable, nunca el valor.
