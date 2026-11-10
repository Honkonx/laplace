---
name: ai-llm
description: "Uso de la IA en Laplace: proveedores, orden por rol, prompts y límites. Activar al tocar services/ai_client.py, ai_prompts.py, ai_prompt_canal.py, consenso_ia.py, ia_simple_laboratorio.py o la IA del agente. Regla de fondo: la IA explica y contrasta; nunca produce las probabilidades."
allowed-tools: [Read, Write, Bash]
---

# IA en Laplace

## Regla de fondo
Las probabilidades salen de modelos estadísticos medidos (consenso de cuotas + Dixon-Coles entrenado + forma y tabla). La IA **explica y contrasta** el resultado; una hipótesis solo-IA se marca como experimental y vive en el laboratorio en sombra, fuera del consenso público (`.claude/rules/evidencia-historica-antes-de-promover.md`).

## Cómo se llama
- Todo pasa por `backend/api/services/ai_client.py`: REST directo con `httpx`, sin SDK de cada proveedor. Proveedores: `gemini`, `groq`, `ollama_cloud`, `openrouter` y `claude`.
- Cada llamada declara un **rol** (`bot`, `canal`, `laboratorio`, `agente`); el rol fija el orden de prueba. Se cambia con `AI_ROUTING_<ROL>` o desde `configurar`. Detalle y modelos por defecto: `docs/backend/IA_PROVEEDORES.md`.
- Si ningún proveedor responde (o no hay claves), quien llamó degrada a «solo estadístico»: nunca se inventa un resultado.
- Las claves se leen solo de `.env`; no se imprimen ni se devuelven. Las pruebas vacían las claves reales (`conftest`).

## Al escribir o cambiar un prompt
- Entrada acotada: equipos, competición y los números ya calculados; pedir una salida estructurada (JSON validable) y validarla antes de usarla (probabilidades normalizadas, claves esperadas).
- Guardar con cada respuesta el proveedor, el modelo, la versión del prompt y el texto crudo (así se puede auditar y comparar).
- Modelos «thinking» (Ollama): la respuesta útil está en `message.content`; dar margen de tokens para que el razonamiento no la agote.
- Un prompt nuevo se mide como cualquier variante: en sombra, contra la tasa base y las cuotas, con 50 partidos para explorar y 200 para proponer promoción.

## Límites y costo
Topes por minuto y por día por usuario (`AGENT_IA_MAX_*`), muestra diaria acotada del laboratorio (`LAB_IA_SIMPLE_MAX_PARTIDOS`) y cuotas de los planes gratuitos: no encadenar llamadas sin tope.
