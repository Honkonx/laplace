# Modelos, algoritmos y datos de pronóstico: mapa (2026-11-12)

Carpeta de listas para decidir qué construir. Se actualiza cuando cambia el código o cuando una medición cambia una conclusión; las investigaciones con fecha viven en `un documento archivado del autor (no publicado)` y no se corrigen.

| Documento | Para qué |
|---|---|
| [`QUE_ES_EL_MODELO.md`](QUE_ES_EL_MODELO.md) | ¿Es Laplace un LLM, un modelo tipo Jev o un bot? Qué es cada pieza, entradas, salidas y generación de datos del modelo de fútbol, y cómo se ejecuta como sistema sin Telegram |
| [`LISTAS_POR_TIPO.md`](LISTAS_POR_TIPO.md) | Qué debe tener cada tipo (predicción, bot como lógica del backend, LLM, agente, decisión, sistema ejecutable) y cuáles tenemos y cuáles faltan, con casillas |
| [`LO_QUE_TENEMOS.md`](LO_QUE_TENEMOS.md) | Inventario del código: modelos, simulación, incertidumbre, datos, IA, evaluación e interfaces, con archivo y cifras |
| [`LO_QUE_NOS_FALTA.md`](LO_QUE_NOS_FALTA.md) | Lista priorizada de lo que falta (modelo, datos, producto, agente, ingeniería y riesgo) con evidencia, esfuerzo y cómo se mide |
| [`DIFERENCIAS_ENTRE_ENFOQUES.md`](DIFERENCIAS_ENTRE_ENFOQUES.md) | Comparación de las familias de modelos (ratings, goles, logística, bayesiano, Kalman, ML, mercado, ensambles, LLM, conforme, Monte Carlo) y qué pregunta contesta cada una |
| [`FUENTES_DE_DATOS.md`](FUENTES_DE_DATOS.md) | Fuentes que usamos y candidatas, con licencia o límite, y el riesgo legal de los datos de entrenamiento |
| [`BOTS_Y_PRODUCTOS_DEPORTIVOS.md`](BOTS_Y_PRODUCTOS_DEPORTIVOS.md) | Bots, servicios y modelos de IA que pronostican deportes: método, evidencia y diferencias con Laplace |
| [`ALGORITMOS_OTROS_DEPORTES.md`](ALGORITMOS_OTROS_DEPORTES.md) | Algoritmos de baloncesto, fútbol americano, béisbol, tenis, críquet y hockey, y qué se transfiere al fútbol |
| [`../MEMORIA_Y_FUENTES_DEL_MODELO.md`](../MEMORIA_Y_FUENTES_DEL_MODELO.md) | Memoria del modelo en la base, capa «actual» con ESPN y predicción conforme |

## Cómo leer las marcas
**✔** contrastado por el asistente principal contra la fuente o el código; **[C]** confirmado en la fuente por un subagente; **[S]** solo resumen o fragmento de un buscador; **[I]** inferido; **[?]** sin evidencia. Casi toda la investigación externa es [S]: los PDF de arXiv y de revistas
vinieron como binario, con paywall o con error 403. Las cifras de esta carpeta que no llevan ✔ o [C] no deben citarse como hechos.

## Método y correcciones
Seis subagentes de búsqueda web (modelos de fútbol; decisión y LLM; nombres «jev, kev, laya, cactus needle»; bots y productos; otros deportes y familias; datos y entrenamiento), cada uno con alcance disjunto y escribiendo solo su informe. El asistente principal contrastó las afirmaciones que se citan.
Corrección principal: el benchmark de 2017 se mide sobre **206 partidos de prueba**, no sobre 216.743 (esos son de entrenamiento). Los anexos conservan el texto original de cada subagente.
