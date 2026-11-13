# Modelo Laplace — el modelo estadístico propio

El modelo **pronostica**: 1X2, goles esperados, marcadores probables, ambos marcan, más/menos y una confianza. **No decide si algo se publica**: esa política es del agente.
Bot, agente y modelo son tres piezas independientes que se conectan por contrato; si el modelo cae, las otras dos siguen con el consenso del bot y lo dicen.

## Piezas (código en `backend/api/ml/laplace/`)

| Módulo | Qué hace |
|---|---|
| `pronostico.py` | De (λ local, λ visitante) a toda la salida: matriz de goles Dixon-Coles, 1X2, ambos marcan, más/menos 1,5/2,5/3,5, cinco marcadores, confianza (1 − entropía normalizada: dispersión, no acierto garantizado). |
| `simulacion.py` | Mundos con verdad conocida (`simular`, modo manual), producto de semillas × rejilla (`simular_masivo`), exportar CSV/JSON e **importar** CSV/JSON con procedencia (`real`/`sintetico`); rechaza el archivo entero si una fila es inválida. |
| `entrenamiento.py` | Elo + tasas de gol con memoria exponencial → regresión logística multinomial propia (sin numpy). Características solo con lo anterior a cada partido. `evaluar_comparando`: walk-forward contra tasa base, Dixon-Coles semanal, mercado y oráculo. |
| `goles.py` | Mercados de goles **calibrados y validados**: encoge las λ hacia la media de la liga (exponente `s` por verosimilitud de Poisson), calibra ambos marcan y más de 1,5/2,5/3,5 con una logística (probabilidad cruda + tasa base de la liga) y los valida con el último 15 % de cada liga. Solo los que ganan a la tasa base quedan en `validados`. |
| `apilado.py` | 1X2 propio + cuotas sin margen (regresión logística). Se ofrece aparte como `p1x2_con_mercado`, solo si le ganó al mercado solo en la evaluación; nunca reemplaza al `p1x2` propio. |
| `ml/comparacion.py` | **Significancia** (MM-00): diferencia pareada de pérdida entre dos pronósticos sobre los mismos partidos, con error estándar, z, Diebold-Mariano-HLN e IC95 por bootstrap en bloques (semanas); `evaluar_jerarquico` la entrega en `informe["comparaciones"]` (modelo vs tasa base, Dixon-Coles, mercado y universal). Puerta de calidad: z ≥ 3 y ≥ 0,001. |
| `registro.py` | Persistencia en las siete tablas `ml_*`. Pesos como JSON en `ml/artefactos/laplace/` con SHA-256 (no se publican). `promover`: sombra → activo solo con ≥ 200 casos evaluados, sin perder contra la tasa base y con nombre de quien aprueba. |
| `servicio.py` | `pronosticar_partido`: modelo activo → si no, respaldo Dixon-Coles con `degradado: true` → si no, `ok: false` con motivo. El modelo en sombra corre en paralelo y se registra, pero no responde. Un artefacto cuya huella no coincide no se sirve. |

## Contrato HTTP (`routers/ml_modelo.py`, versión `ml-1`)
- `POST /api/v1/ml/predict` `{local, visitante, liga?, partido_id?}` → pronóstico (120/min por IP; cálculo local, sin costo externo).
- `GET /api/v1/ml/health` → si hay modelo activo. `GET /api/v1/ml/models` → modelos y métricas (administrador).
- Herramienta del agente `modelo.pronosticar` (solo lectura): llama a ese endpoint y, si no responde, devuelve `degradado` y sugiere `sports.predict`.

## Uso
```
python backend/scripts/modelo_laplace.py simular --semilla 7 --equipos 16 --temporadas 4 --csv salida.csv
python backend/scripts/modelo_laplace.py entrenar --importar partidos.csv --procedencia real --nombre laplace-real --guardar
python backend/scripts/modelo_laplace.py promover --modelo 3 --aprobado-por <nombre>
python backend/scripts/evaluar_modelo_laplace.py --max-ligas 6      # evaluación real, solo lectura
```
Sin `--guardar` no se escribe en la base. Antes de escribir en la base real, respaldo (`database-safety.md`).

## Reglas que no se rompen
- Una simulación nunca se confunde con un partido real: toda muestra lleva procedencia; la evaluación final es con partidos reales no vistos.
- Ningún modelo pasa de sombra a activo sin evidencia en vivo y un aprobador (`evidencia-historica-antes-de-promover.md`).
- Datos y modelos entrenados no viajan al repo público.

## Medición real (2026-11-10, 6 ligas, 10.058 partidos de prueba desde 2023-07-01; entrenado antes)
| | log loss | RPS |
|---|---|---|
| Tasa base | 1,0729 | 0,2260 |
| Dixon-Coles semanal | 1,0510 | 0,2181 |
| **Modelo propio** | **1,0512** | **0,2184** |
| Mercado (solo 5.255 con cuotas) | 1,0327 | 0,2148 |

Lectura: el modelo propio mejora claramente a la tasa base y **empata** con Dixon-Coles; **no** supera al mercado (coherente con la evidencia previa del proyecto). Su valor hoy es independencia, calibración (ECE 0,028) y salida completa (goles, marcadores, totales); no una ventaja de acierto. Reproducible con `evaluar_modelo_laplace.py`.

## Modelo jerárquico: universal + conocimiento de cada liga
Un solo modelo entrenado con **todas las ligas** (49 con datos, 135.737 filas) cuyo estado se lleva **por liga**: Elo, tasas de gol y media de goles de cada liga viven en `ligas[COD].estado`; los pesos
de la regresión son universales. Así un equipo se pronostica con el conocimiento de SU liga (qué tan goleadora es, cuánto vale la localía allí) sin tener que reaprender el fútbol en cada una.
Probé además **especializar los pesos por liga** (anclados a los universales, las ligas con ≥ 800 partidos): en 43.602 partidos de prueba reales dio log loss 1,02202 contra 1,02197 del universal,
es decir **no mejora**, y por liga unas ganan y otras pierden. Queda apagado (`especializar=False`) y disponible (`entrenar_jerarquico(..., especializar=True)`) para reprobarlo cuando haya más datos.

| 49 ligas, prueba desde 2023-07-01 (44.289 partidos, modelo universal) | log loss | RPS |
|---|---|---|
| Tasa base | 1,0712 | 0,2272 |
| **Modelo Laplace jerárquico** | **1,0214** | **0,2101** |
| Mercado (solo 20.960 partidos con cuotas; otro subconjunto, no comparable 1 a 1) | 0,9957 | 0,2018 |

## Funciona sin IA
Todo es Python y matemáticas (Elo, tasas de gol, regresión logística, matriz de Poisson con Dixon-Coles). Ninguna llamada a un LLM entra al cálculo. Las IAs solo **consumen** su resultado.

## Integración (tres piezas independientes, un contrato)
- **Modelo → bot:** `motor.analizar_partido` agrega `modelo_laplace` (resumen compacto) **fuera del consenso**: el pick del bot no cambia (el modelo empata con Dixon-Coles, que ya está en el consenso).
  El motor lo lee por el puntero `ml/artefactos/laplace/vigente.json` (con verificación de huella), sin abrir la base. Si falla o no cubre el partido, el campo es `null` y todo sigue igual.
- **Modelo → agente:** `sports.predict` añade `resumen.modelo_laplace`; el texto del agente y el bot de Telegram del agente muestran 1X2, goles esperados y marcador probable. `modelo.pronosticar` lo consulta solo.
  El agente decide qué hacer con eso (publicar o no); el modelo no emite política.
- **Modelo → IA por API:** `GET /api/v1/ml/tools` entrega la definición de la herramienta en formato Anthropic y OpenAI; cualquier IA con llamadas a herramientas llama a `POST /api/v1/ml/predict`.
  **No** se inyecta en el prompt del análisis con IA a propósito: ese prompt contrasta contra el modelo estadístico y debe seguir siendo independiente.
- **Degradación:** modelo activo → Dixon-Coles histórico (`degradado: true`) → `ok: false` con motivo.

## Operación
- Entrenar y guardar: `python backend/scripts/modelo_laplace.py entrenar-real --guardar` (queda en sombra). Promover: `... promover --modelo N --aprobado-por <nombre>`; exige 200 casos en sombra **o** una evaluación
  histórica real de ≥ 2.000 partidos con ≥ 0,02 de ventaja de log loss sobre la tasa base, y escribe el puntero.
- Trabajo diario `modelo_laplace_sombra` (07:45 Chile): `registro.evaluar_sombra` cruza las predicciones en sombra con los resultados verificados y actualiza `ml_evaluaciones` (origen `sombra`).
- Estado al 2026-11-10: modelo `laplace-real` versión `20261110-real` **activo** (promovido por orden del usuario con la evidencia histórica de arriba); respaldo previo de la base en `backups/laplace/`.

## Sombra en vivo y reentreno (meta M1, 2026-11-10)
- **Laboratorio:** `registrar_comparadores_del_motor` registra la variante `laplace_modelo` junto a Poisson, Dixon-Coles, IA, BSD y mercado, con la protección anti-retrospectiva del laboratorio (corte anterior al inicio
  del partido). Solo se registra cuando responde el modelo mismo (no el respaldo Dixon-Coles). Se mide con el mismo marco (50 exploratoria, 200 para promover) y no entra al consenso (`permite_consenso = 0`).
- **Reentreno semanal** (`modelo_laplace_reentreno`, domingo 04:30 Chile, después del reajuste de las 03:30): `modelo_laplace.py reentrenar --auto` por subproceso (el servidor no tiene numpy), con el histórico y la capa en vivo.
  Mide con el corte fijo 2023-07-01 y registra el modelo nuevo en sombra; lo **promueve solo si pasa todas las guardas**: ventaja ≥ 0,02 sobre la tasa base, no peor que el activo por más de 0,002, ≥ 40 ligas y ≥ 90 % de
  las filas del activo. Si falla alguna, el activo se conserva y el motivo queda en el registro del trabajo. `LAPLACE_REENTRENO_AUTOMATICO=0` lo apaga.

## Afinación (meta M3, 2026-11-10): generación 2
Protocolo: entrenamiento < 2021-07-01, **validación** 2021-07..2023-07 (24.584 partidos, 49 ligas), **prueba** ≥ 2023-07 (43.602). La rejilla (Elo `k`, memoria de goles `alfa`, y las características extra `abs_elo` = brecha de
fuerza sin signo y `forma` = puntos recientes) se compara solo en validación (`afinar_modelo_laplace.py`); el ganador debe vencer al actual por ≥ 0,0005 de log loss antes de mirar la prueba.

| | validación | prueba |
|---|---|---|
| Generación 1 (k=24, alfa=0,12, sin extras) | 1,01927 | 1,02197 |
| **Generación 2 (k=8, alfa=0,08, `abs_elo` + `forma`)** | **1,0164** | **1,0192** |

La primera ronda dejó el ganador en el borde de la rejilla (k=16, alfa=0,08), así que se amplió hacia abajo (segunda ronda, también solo en validación) y ganó k=8. Cuatro puntos: la mejora es **pequeña** (≈ 0,0028 de log loss) pero **consistente** en validación
y prueba; la meseta entre k=8 y k=16 es plana (1,0164–1,0167), no hay un óptimo agudo; la prueba se miró dos veces (una por ronda) sin que la decisión se tomara con ella; ECE bajó de 0,0121 a 0,0083.
Se aplicó con el reentreno automático: `laplace-real 20261110-real-g2` (log loss 1,01853 en la evaluación del reentreno) **se promovió solo por las guardas** y retiró al anterior (por primera vez con datos reales).
Los artefactos de la generación 1 se siguen leyendo con sus valores originales.

## Endpoint interno y clave (meta M4)
`POST /api/v1/ml/predict/interno`: igual que `/predict` pero exige `x-laplace-ml-key` (= `ML_API_KEY` del `.env`; vacía = el endpoint no existe), acepta `partido_id` y deja rastro (predicciones y sombra).
Es el camino para el laboratorio, scripts e IAs externas de confianza; el público (`/predict`) no deja rastro. La respuesta nunca incluye la clave ni la ruta local del artefacto.
La redacción del agente con IA puede citar las cifras del modelo (se aceptan las del JSON verificado y las del borrador determinista) y se rechaza si inventa una.

## Medición en vivo conectada (seguimiento de M5, 2026-11-10)
- El laboratorio (`registrar_modelo_laplace`) deja además la predicción en `ml_predicciones` con el `partido_id` real y el corte previo al partido, **dentro de la transacción del laboratorio** (sin commit propio).
- El trabajo diario `modelo_laplace_sombra` evalúa **dos** modelos contra los resultados verificados: el que está en sombra (`origen = sombra`) y el activo (`origen = vivo`). Así la ventaja de la generación 2 se podrá comprobar con partidos que
  ocurran después de hoy; todavía no hay casos acumulados.
- **Control de fidelidad de la redacción con IA:** una probabilidad entregada como fracción (0,5169) puede citarse como porcentaje (51,69 %, 51,7 %, 52 %); antes se rechazaba una redacción fiel. Verificado con una IA real (cascada: Ollama Cloud falló y respondió
  Gemini): el texto fiel se acepta y una cifra inventada se rechaza.

## Verificación de extremo a extremo (2026-11-10)
Backend real en un puerto local sobre una **copia** de la base, con una clave temporal solo en el entorno del proceso (no se tocó el `.env`):
- `POST /api/v1/ml/predict/interno`: sin clave 401, clave mala 401, clave buena 200 con el modelo `20261110-real-g2`; la respuesta no contiene la clave ni rutas locales; la fila queda con el `partido_id` y `canal = interno`.
- **IA real con llamada a herramienta nativa** (Gemini 2.5 Flash): tomó la definición de `GET /api/v1/ml/tools`, decidió llamar a `laplace_pronosticar` con los argumentos correctos y respondió con las cifras exactas del modelo (51,69 / 24,50 / 23,81 %).
- **Laboratorio con objetos reales:** `motor.analizar_partido` produce el bloque `modelo_laplace` y `registrar_comparadores_del_motor` registra `laplace_modelo` (versión g2) junto a `dixon_coles_historico`, más la predicción en `ml_predicciones` con el `partido_id`.
- Comando `modelo_laplace.py estado` (solo lectura): modelos, evaluaciones y cuánta evidencia en vivo falta (hoy 0 observaciones; 50 para la etapa exploratoria, 200 para promover).

Lo que sigue dependiendo del tiempo: la ventaja de la generación 2 en vivo (se verá en `estado` cuando se jueguen partidos analizados con el modelo activo).

## Evidencia en vivo y aviso automático
- `laboratorio_pronosticos.comparar_en_vivo(db)` compara `laplace_modelo` contra **cada** otra variante sobre los **mismos** partidos ya jugados (`ventaja_log_loss` > 0 = el modelo va mejor) y dice cuánto falta para 50 y 200. `modelo_laplace.py estado` lo muestra.
- El trabajo diario `modelo_laplace_sombra` guarda `lab=N` en su detalle y emite la alerta `modelo_laplace_evidencia` **una sola vez** al cruzar 50 (`exploratoria`) y 200 (`promocion`) partidos con resultado (si el webhook de alertas está activo); además queda en el log.
  Así no hace falta acordarse de mirar: cuando haya evidencia suficiente, avisa.

## La evidencia en vivo se acumula sola
`laboratorio_modelo_laplace.registrar_proximos(db)` registra, para los partidos **próximos** que el bot ya conoce (`partidos_dia` de hoy a pasado mañana, estado `scheduled`, empiezan en > 30 min y < 48 h), el pronóstico del modelo Laplace **y** el de Dixon-Coles
sobre los mismos partidos. Solo usa nombres de equipo y liga ya guardados: **no gasta cuota de ninguna API** y no depende de que alguien pida un análisis. Es idempotente y el laboratorio rechaza por sí mismo un corte posterior al inicio.
La corre el trabajo `modelo_laplace_sombra` dos veces al día (07:45 y 16:45 Chile, después de los refrescos de las 07:15 y 15:15). Cuando los partidos terminan, el flujo de resultados ya existente los evalúa y `comparar_en_vivo` / `estado` muestran la ventaja contra Dixon-Coles.
Primera ejecución real (2026-11-10 19:37 UTC): 41 candidatos, 40 ya habían empezado, 1 sin cobertura, 0 registrados; los partidos de mañana aún no estaban cargados. El primer registro ocurrirá en la próxima pasada.

## Dónde se ve el modelo (bot, web y agente)
- **Telegram del bot** (`/predecir` y canal): una línea `🧮 Modelo Laplace: Local x% | Empate y% | Visitante z% | goles a-b` en `mensajes_analisis._lineas_contexto_historico`; si respondió el respaldo, dice «Respaldo Dixon-Coles». No cambia el pick.
- **Web** (`PrediccionResultado`): párrafo «Modelo Laplace (lectura aparte, no cambia el pick)» con probabilidades, goles esperados y marcador probable; solo cuando el análisis trae pronóstico (con «Sin pronóstico» el bot no muestra la lectura del modelo para no contradecir
  su propia razón). 2 pruebas de vitest; 56 en total.
- **Agente:** `sports.predict` y el Telegram del agente (ver arriba).
- **Clave del endpoint interno:** `python backend/scripts/modelo_laplace.py generar-clave` crea `ML_API_KEY` en tu `.env` **sin mostrarla** (no pisa una existente; `--rotar` la reemplaza) y hay que reiniciar el backend. Es la única acción sobre tu configuración, por eso solo corre cuando tú la pides.

## Organización del código
`laboratorio_modelo_laplace.py` (variante en el laboratorio, predicción con `partido_id`, comparación en vivo) y `ml/laplace/jobs.py` (evaluación diaria y reentreno semanal; reciben la fábrica de sesiones) salieron de `laboratorio_pronosticos.py` y de `main.py`;
el laboratorio los reexporta con los mismos nombres. `top_picks.py` y otros archivos de 440-620 líneas se dejan: sus pruebas parchean nombres internos del módulo y moverlos rompería esos parches.

## Estado de la clave interna (2026-11-10)
`ML_API_KEY` está creada en el `.env` del usuario (50 caracteres, prefijo `lap-ml-`, ignorado por git; el valor no se muestra en ningún lugar). Creada con `generar-clave` **tras la autorización explícita del usuario** (antes el clasificador de permisos había denegado
la escritura en el `.env`). Verificada con un backend real sobre una copia de la base: sin clave 401, clave mala 401, clave del `.env` 200 con el modelo `20261110-real-g2`, y la respuesta no contiene la clave. El backend en marcha necesita reiniciarse para leerla.

## Generación g3: mercados de goles calibrados y apilado con cuotas (2026-11-11)
**Hallazgo (2026-11-10):** las λ crudas daban mercados de goles PEORES que la tasa base fuera de muestra (ambos marcan 0,6985 vs 0,6899; más de 2,5: 0,6971 vs 0,6874) por ser demasiado extremas. Se arregló en `goles.py`.
Medido con el modelo entrenado antes de 2023-07-01 y probado en 43.602 partidos posteriores (log loss; menos es mejor):

| Mercado | Modelo calibrado | Tasa base de la liga |
|---|---|---|
| Ambos marcan | 0,6864 | 0,6899 |
| Más de 1,5 | 0,5573 | 0,5616 |
| Más de 2,5 | 0,6814 | 0,6875 |
| Más de 3,5 | 0,5879 | 0,5944 |
| Goles totales (error absoluto) | 1,308 | 1,319 (media de la liga) |

Las mejoras son pequeñas pero reales y la calibración quedó pareja (lo que dice 55 % ocurre ≈ 55,5 %). El marcador exacto más probable acierta 12,6 % (siempre «1-1»: 12,1 %): se muestra, sin darle más peso del que tiene.
- **Lo que se muestra lo decide la validación, no el código:** el artefacto trae `goles.util` por mercado y la salida trae `validados`. `servicio.publico` (API) y `resumen_para_consumidores` (bot, web, agente) quitan o dejan en `null` lo no validado; las pantallas no lo nombran. Un artefacto anterior a g3 (sin calibración) no muestra goles.
- **Apilado con cuotas** (entrada opcional `cuotas: [local, empate, visitante]`, validada: 3 decimales entre 1,01 y 1000): en 20.960 partidos con cuotas, modelo 1,0131, mercado 0,9957, apilado 0,9946. Mejora real pero de ≈ 0,001: por eso es una lectura aparte (`p1x2_con_mercado`) y el motor del bot la pide cuando el partido trae cuotas.
- `reentrenar --forzar` registra una revisión nueva (`…-g3-r2`) el mismo día; sin él, un segundo reentreno del día no duplica. Versión activa tras esta ronda: `20261110-real-g3-r4` (promovida por las guardas; los r1–r3 quedaron retirados, nada se borra).
- Medido y descartado: ClubElo (api.clubelo.com respondió 502 el 2026-11-10; sin datos no se evalúa).

## Versión 1.1: tiros y tiros a puerta (2026-11-11, en sombra)
- **Variables nuevas (4):** log(λ de tiros / media de la liga) y lo mismo para tiros a puerta, local y visitante (`EstadoLiga._features_tiros`); valen 0 si la liga no trae tiros, un equipo no tiene historia de tiros o el partido es de la capa en vivo (que no los trae). Se activan con `extras: ["tiros"]` (`HIPER_V11`; `HIPERS = {"g3", "v1.1"}`).
- **Enrutador por liga:** los pesos universales se ajustan solo con las ligas que traen tiros (18); las otras 31 usan los pesos de la versión sin tiros rellenos con ceros (`pesos_de_respaldo`, medido: con pesos únicos algunas ligas sin tiros empeoraban hasta 0,005, z = −3,6).
- **Medido con el código oficial** (`scripts/comparar_versiones_modelo.py --a g3 --b v1.1`, corte 2023-07-01, 43.602 partidos de prueba, diferencias pareadas, bootstrap en bloques de semana): global **−0,00273** de log loss (z = 8,6; IC95 [0,00207; 0,00340]); ligas con tiros **−0,00568** (z = 8,6); ligas sin tiros 0,00000 (idénticas a g3). Cumple la puerta (≥ 0,001, z ≥ 3, IC95 sin cero).
- **Estado:** registrada como `20261111-real-v11` en **sombra** (`reentrenar --variante v1.1`; nunca se promueve sola). Antes de promoverla falta la captura de tiros en vivo (MM-13): sin ella el estado de tiros envejece. Se evalúa en vivo con la sombra y la regla 50/200.
- **Linaje y model card (MM-01, MM-03):** cada artefacto trae `linaje` (`semilla` 0, `hash_datos`, `version_variables`, `hash_codigo`); dos entrenamientos con los mismos datos dan el mismo artefacto byte a byte (probado). `tarjeta.py` genera la model card junto al artefacto y `GET /api/v1/ml/modelo` expone la ficha (versión, variables, ligas, mercados validados, linaje; sin rutas ni secretos). `variables.py` es el catálogo de variables con su cobertura por liga.
- **Simulación de ligas** (`ml/laplace/liga.py`, MM-22/23): Monte Carlo de temporadas en Python puro con semilla, huellas, desempates y cupos; escenarios (forzar/filtrar con aleatorios comunes) y caminos exactos (≤ 8 partidos). 10.000 temporadas de 380 partidos en 3,4 s. `validado: false` hasta el backtest; todavía sin endpoint.
- **Matriz de goles** 4,8 veces más rápida con la misma salida exacta (MM-04). Arnés de significancia: `ml/comparacion.py` y `ml/laplace/versiones.py`.

## Contrato `ml-2` (2026-11-11): capacidades para IAs y servicios internos
`routers/ml_capacidades.py`, prefijo `/api/v2/ml`, **todas con `x-laplace-ml-key`** (sin `ML_API_KEY` no existen: 404; clave mala: 401). Solo lectura y sin estado; esquema cerrado, cuerpo ≤ 1 MB y límites; el error siempre es `{"ok": false, "error": entrada_invalida|limite_excedido|datos_insuficientes|no_validado|modelo_no_disponible, "campo", "maximo", "corregible"}` con HTTP 422;
toda salida lleva `contrato`, `capacidad`, `version_modelo`, `semilla`, `huella_entrada`, `huella_salida` y `validado`.
| Ruta | Qué hace |
|---|---|
| `GET /capacidades`, `GET /tools` | Qué hay y las herramientas en formato Anthropic y OpenAI (`laplace_pronosticar`, `laplace_simular_temporada`, `laplace_verificar_afirmacion`) |
| `POST /sim/temporada` | Monte Carlo del resto de la temporada (≤ 20.000 simulaciones, ≤ 24 equipos, ≤ 500 pendientes): probabilidad de cada posición, puntos y cupos; las lambdas se pasan o se piden al modelo (`lambdas_de_modelo`); reproducible con la semilla |
| `POST /sim/escenario` | «¿Y si…?»: resultados forzados o condicionados con aleatorios comunes y diferencia contra la base |
| `POST /sim/caminos` | Enumeración exacta de los 3^k resultados 1X2 de ≤ 8 partidos con su probabilidad |
| `POST /eval/comparar` | Dos listas de pronósticos sobre los mismos partidos: diferencia de log loss, z, Diebold-Mariano-HLN, IC95 por bootstrap y si cumple la puerta |
| `POST /verificar` | **«La IA propone, el modelo calcula, la IA critica»:** recalcula la cifra que afirmó una IA (`p1x2.*`, `btts.*`, `mas_1_5/2_5/3_5`, `goles_esperados.total`; solo campos validados) y responde `coincide`/`difiere` con la diferencia y la tolerancia; **no corrige** la cifra |
Las simulaciones salen con `validado: false` hasta pasar el backtest de temporadas pasadas.

## Qué falta
Validación en vivo de g3 (0 de 50 y 0 de 200 partidos con resultado), evaluar los mercados de goles también en vivo, calibración por temperatura medida (ECE ya es 0,012), árboles de gradiente solo si mejoran, conectores opcionales (System One, MCP) y Go solo si se mide un cuello de botella.

## El «por qué» de un pronóstico (2026-11-11)
`ml/laplace/explicacion.py` descompone el logit de «local frente a visitante» en la contribución de cada variable: `(peso_local − peso_visitante) · valor`. Es exacto (la suma más el sesgo es `ln(p_local / p_visitante)`) y descriptivo: no cambia ninguna cifra.

## Incertidumbre del 1x2 (2026-11-11)
El artefacto guarda la covarianza de los pesos universales (`incertidumbre.covarianza`); `ml/laplace/incertidumbre.py` calcula, por el método delta, un intervalo al 80 % para cada probabilidad y marca `poco_fiable` si alguno mide más de 0,20. Describe la incertidumbre de los PESOS, no el azar del resultado, y no vale para pesos especializados por liga.

## Validación del simulador de temporadas (2026-11-11)
`backend/scripts/backtest_temporadas.py` congela el modelo al 60 % de cada temporada de 10 ligas europeas (57 temporadas), simula el resto y compara con la tabla final real. Sin incertidumbre de fuerza el intervalo p05–p95 cubría 83,9 % de los equipos; con `sigma_fuerza` = 0,12 cubre 90,1 %. El error de los puntos finales esperados (4,43) supera a extrapolar los puntos actuales (4,76) y el Brier del campeón (0,222) a repartir por puntos actuales (0,609). El simulador solo se declara `validado` si existe ese backtest en la máquina y se hizo con el mismo sigma.

## Núcleo en Go (2026-11-11)
`modelo/go/lsim` ejecuta el bucle Monte Carlo del simulador (`ml/laplace/motor_go.py`); ×19,7 con 10.000 temporadas. Python orquesta y es el respaldo. Salida con `motor`: `go` o `python`. Compilar con `python backend/scripts/construir_go.py --probar`. Detalle y cifras: `docs/mejoras/modelo/09_MEDICION_NUCLEO_GO.md`.

## ¿El modelo da lo mismo que el bot? (2026-11-12, `backend/scripts/acuerdo_modelo_bot.py`)
Sobre 20.960 partidos de prueba (posteriores a 2023-07, con cuotas de apertura, sin fuga del futuro), con las mismas fechas y equipos:

| Comparación | Diferencia media de probabilidad (L / E / V) | Mismo pick | Correlación de P(local) |
|---|---|---|---|
| Modelo vs bot sin cuotas (55 % Laplace + 45 % Dixon-Coles) | 1,7 / 1,0 / 1,4 puntos | 96,6 % | 0,991 |
| Modelo vs bot con cuotas (aprox.: 0,70 mercado + 0,25 Dixon-Coles) | 4,2 / 1,7 / 3,7 puntos | 89,5 % | 0,936 |
| Modelo vs mercado sin margen | 5,1 / 1,8 / 4,6 puntos | 87,2 % | 0,907 |
| Bot con cuotas vs mercado | 1,4 / 0,6 / 1,2 puntos | 96,8 % | 0,994 |

Log loss: modelo 1,0131; bot sin cuotas 1,0118; bot con cuotas 0,9982; mercado 0,9957. Lectura: sin cuotas el bot ES casi el modelo (la mezcla lo contiene); con cuotas el bot es casi el mercado, y el modelo difiere ≈ 4 puntos porque no ve las cuotas. «Mismos datos» solo se cumple sin cuotas. El consenso con cuotas es una APROXIMACIÓN (sin forma, tabla ni el apilador interno del módulo histórico).

## Versión y lenguajes (2026-11-12)
En servicio: generación g3 (`20261110-real-g3-r4`, activa), que el plan llama `1x2@1.0`. La v1.1 con tiros (`20261111-real-v11`) está en sombra y no se promueve sin tiros en vivo. Python entrena, valida y sirve; el núcleo Monte Carlo del simulador corre en Go; Rust no (no está instalado).
