# Toda falla se escribe con su número exacto, y la que vuelve se cuenta

> Creada 2026-10-19. Adaptada de `documentar-fallas-y-errores.md` (PAGINA1). Complementa
> `incremental-progress-documentation.md` (cuándo escribir) con QUÉ escribir de una falla.

## Qué se escribe
Toda falla, aunque se arregle en dos minutos: **el mensaje de error textual** (entre comillas o bloque de código),
**dónde** (archivo:línea), **cuándo** y **contra qué se verificó**. Con el número, no con el adjetivo.

| Así NO | Así SÍ (casos reales de Laplace) |
|---|---|
| "api-football da pocos datos" | HTTP 200 con `errors: {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}` leído como "sin resultados" (2026-10-19) |
| "el bot responde sin datos" | 101 de 946 partidos (10,7 %) con modelo histórico válido el 2026-10-10 |
| "la fecha estaba mal" | `date_from=20261008` enviado a BSD que espera `YYYY-MM-DD` |

## La falla recurrente: se cuenta y a la tercera se automatiza
Cuando una falla vuelve, lo que se documenta es **que volvió**, con una tabla `cuándo | dónde | qué`. A la tercera
vez no se "arregla con más cuidado": se escribe un test, un script o un hook. Precedentes de este repo:
- un `errors` dentro de un HTTP 200 leído como lista vacía → `cuerpo_api_football` + `test_http_retry.py`;
- el mismo error de unidades del Poisson medido tres veces sin que nadie lo viera → `evaluar_modelo_historico.py`;
- las tasas de la liga equivocada por un nombre homónimo → filtro de país + `test_modelo_historico_cobertura.py`.

**Señal de alarma:** una nota de corrección que corrige otra nota de corrección. Ahí la tercera nota es la respuesta
equivocada; hay que arreglar la causa.

## La falla que solo se ve en un entorno
Se nombra el entorno donde aparece y donde no (SQLite / Postgres, plan gratis / plan de pago, tests con claves en
blanco / `.env` real, Windows / Termux). Si los tests pasan pero el entorno real falla, el defecto está en el entorno.
