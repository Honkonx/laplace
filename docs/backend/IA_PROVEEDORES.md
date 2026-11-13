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

## Llamadas a herramientas nativas (`services/ai_herramientas.py`)
Gemini y los proveedores de formato OpenAI (Groq, OpenRouter) pueden **pedir** una herramienta (p. ej. `laplace_pronosticar`, la misma de `GET /api/v1/ml/tools`); el servidor la ejecuta y devuelve el resultado para que la IA redacte.
Límites: solo corren las herramientas que el llamador registró (cualquier otro nombre vuelve a la IA como error), argumentos de hasta 2.000 caracteres, resultado truncado a 6.000, plazo de 15 s por herramienta y 3 vueltas como máximo.
Usa el mismo enrutamiento por rol y las mismas métricas que el camino de texto; si ningún proveedor lo logra lanza `AnalisisIAError` y el llamador cae a `generar_texto_ia`. La IA sigue sin producir probabilidades: las cita de la herramienta o no las da.
Estado: capacidad lista y probada con transporte simulado (7 pruebas); todavía **no está conectada** al flujo de chat del agente (esa decisión de producto queda pendiente) ni se probó con una IA real en esta ronda.

## Análisis con IA: salida estructurada, fidelidad de cifras y anti-inyección (2026-11-11)
- **Salida estructurada** (`services/ai_salida.py`, `AI_ANALISIS_JSON=True` por defecto): el prompt `analisis.v2-json` pide un JSON `analisis.v1` (`dato_local`, `dato_visitante`, `lectura`, `pick`). Se valida (campos exactos, versión, largos, y el `pick` debe ser el local, el visitante o «Empate») y se renderiza al texto de siempre con la línea `⚖️ Balance y PICK:`, de modo que el consenso, el control de cifras y los mensajes no cambian. H2H y cuotas las pone el sistema, no la IA.
  Si la IA responde con el formato de texto antiguo se acepta; si parece JSON pero no cumple el esquema se rechaza y el análisis cae a solo estadístico (nunca se publica un pick inventado). Todo texto se sanea y se escapa para HTML.
- **La IA ya no escribe BTTS, Over/Under ni marcador** y el prompt describe el consenso real (cuotas + modelo histórico; ya no dice «Poisson independiente»). Los goles del mensaje salen del modelo Laplace **solo si están validados**; el Poisson crudo (peso 0) ya no se muestra. Tampoco se muestra «Bankroll» (lenguaje de apuestas).
- **Fidelidad de cifras** (`consenso_ia.depurar_cifras`): se descarta la línea que traiga CUALQUIER cifra ausente del prompt (porcentajes con tolerancia 0,6; decimales con 0,06; enteros ≥ 11 exactos; los enteros de 0 a 10 y los años no se exigen). La línea del PICK nunca se descarta.
- **Prompt del canal** (`canal.v2`): no pide confianza ni obliga a dar pick (`Sin datos` es válido) y recibe el pick y la probabilidad del **consenso** en lugar de «Poisson pick/Forma pick».
- **Anti-inyección:** `sanear_texto` quita `<<<`, `>>>` y cercados de código de los datos externos; el prompt JSON envuelve los datos en `<<<DATOS … DATOS>>>` y dice que son información, no instrucciones. Versión de prompt guardada en `combinado["prompt_version"]` y `["formato_ia"]`.
- Conjunto dorado: `backend/tests/test_ia_dorado.py` (147 casos) y `test_ai_salida.py`.

## Proveedores caídos y configuración que se pudre
- Un proveedor que responde **401, 402, 403 o 404** (clave inválida, sin créditos, sin permiso o modelo que ya no existe) no se arregla reintentando: la cascada (`services/ai_client.py`) lo salta 10 minutos y sigue con el siguiente. Un 429 o un 5xx sí se reintentan una vez. Una respuesta sin texto (`content: null` de un modelo de razonamiento) no rompe: se pasa al siguiente.
- Ollama Cloud con una clave sin créditos responde 402 con todos los modelos. En OpenRouter el modelo `:free` debe estar vigente; algunos devuelven solo `reasoning`.
- `backend/scripts/evaluar_proveedores_ia.py` mide a cada proveedor con lo que el agente le pide antes de activarlo o al cambiar de modelo.
