# Lo que nos falta (2026-11-12)

Lista priorizada. «Evidencia» usa las marcas de la investigación: **✔** contrastado por el asistente principal contra la fuente o el código esta ronda, **[S]** solo resumen o fragmento de un buscador, **[I]** inferido, **[?]** sin evidencia.
Regla de todo lo de esta lista: nada entra al consenso ni al producto sin medirse walk-forward contra la tasa base y el mercado sobre los mismos partidos (`.claude/rules/evidencia-historica-antes-de-promover.md`).
Lo ya hecho está en `LO_QUE_TENEMOS.md`; la comparación entre enfoques, en `DIFERENCIAS_ENTRE_ENFOQUES.md`.

## A. Modelo (de lo más barato y medible a lo más caro)
| # | Falta | Por qué (evidencia) | Esfuerzo | Cómo se mide | Estado |
|---|---|---|---|---|---|
| 1 | **Regresión a la media del Elo entre temporadas** (y un K por competición) | El Elo de NHL usa K = 6 y regresión del 30 % hacia la media entre temporadas [S]; en fútbol lo justifica la rotación de plantillas [I]. Hoy `EstadoLiga.actualizar` **no** distingue temporadas | minutos | Walk-forward (`evaluar_regresion_temporada.py`); debe vencer al actual por ≥ 0,0005 de log loss | **Medido el 2026-11-12: señal débil, no demostrada** (ver abajo) |
| 2 | **Incertidumbre de rating** (tipo Glicko: una desviación por equipo que crece sin partidos y baja con ellos) | Sirve para recién ascendidos y para propagar incertidumbre a la simulación de temporada; respaldo en fútbol: Lasek 2013 [S] | bajo (~60 líneas) | Cobertura de los intervalos y RPS en equipos con < 20 partidos | pendiente |
| 3 | **Estado-espacio / Kalman de ataque y defensa** | Koopman y Lit (rentabilidad frente a cuotas en la Premier [S]); Egidi 2025: Brier de la Premier de 0,616–0,619 a 0,602 y RPS de 0,232–0,233 a 0,224 en las últimas 3 jornadas de 2024/25 (✔ leído entero por el subagente; mejora modesta y de una sola temporada) | medio | Walk-forward 49 ligas contra el modelo actual | pendiente |
| 4 | **Calibración por liga** (temperatura vectorial o beta) con ECE por liga | La isotónica existe; la evidencia comparativa en fútbol no se encontró [?] (Guo 2017 es general) | medio | ECE y log loss por liga fuera de muestra | pendiente |
| 5 | **Predicción conforme dentro del producto** como «rango plausible» | Medido por nosotros: cobertura 79,5 % para 80 % y 89,9 % para 90 %, pero **no uniforme por liga** (peor: N1 70,3 %) ✔ | bajo | Cobertura mensual por liga en sombra | experimento hecho, producto pendiente |
| 6 | **Pooling logarítmico frente al lineal** del consenso y extremizing ajustado | Satopää y Ungar [S]; con módulos dependientes se espera mejora pequeña o nula [I] | bajo | Walk-forward del consenso | pendiente |
| 7 | **Pesos adaptativos (Hedge)** con el mercado como ancla | Cota de regret con pérdida log [S]; beneficio práctico pequeño [I] | medio | En sombra | pendiente |
| 8 | **Pi-ratings** (rating de rendimiento con decaimiento por diferencia de goles) | Ganó el desafío de 2017 junto a árboles potenciados [S]; esa prueba tiene solo **206 partidos** ✔ | medio | Walk-forward 49 ligas | pendiente |
| 9 | **Gradient boosting como meta-modelo** sobre ratings y forma | XGBoost no batió a las cuotas en Baboota y Kaur 2019 (RPS 0,2156 frente a 0,2012) [S] | bajo-medio | Solo en sombra | pendiente |
| 10 | **TabPFN** (modelo preentrenado para tablas pequeñas) | Sin evidencia deportiva; licencia v2.5 no comercial según una fuente [S] | medio | Solo en sombra, y revisar licencia | pendiente |
| 11 | **Alineaciones y lesiones** como señal | Mejora reportada pero sin la cifra [S]; exige datos previos al partido | alto | Walk-forward con corte previo | pendiente |
| 12 | **xG propio o datos de eventos** (xG, xT, VAEP) | StatsBomb Open Data sirve para estudiar, no para producción (cobertura parcial) [S] | alto | Estudio aparte | pendiente |

## B. Datos y fuentes
| # | Falta | Detalle |
|---|---|---|
| 1 | **Una segunda fuente de resultados con licencia limpia** | openfootball (CC0, 2010-11 a 2026-27, resultados y calendario sin cuotas [S]) para cruzar y validar la capa «actual» |
| 2 | **Fuente propia de la Serie B de Brasil sin ESPN** | ESPN es una API pública no documentada, sin términos ni garantía de continuidad [S] |
| 3 | **Resultados que el bot verifica para las 10.776 filas viejas sin país** | Quedan fuera de la cobertura del modelo; se completan solas al volver a traer cada día |
| 4 | **País en `analisis_comparativo` y `resultados_partidos`** | Hoy solo `partidos_dia` lo guarda |
| 5 | **Cuotas de apertura frente a cierre en las ligas nuevas de la capa «actual»** | Esa fuente solo publica cuotas de cierre: sin `ap_prom` no hay evaluación contra mercado en esas ligas |

## C. Producto y honestidad (lo que ningún bot revisado hace)
| # | Falta | Por qué |
|---|---|---|
| 1 | **Registro público con sello de tiempo, anterior al partido, de cada pronóstico** | Es el diferenciador verificable frente a bots y «tipsters» sin historial auditable; LLM-SoccerArena lo hace así [S]. Ya guardamos cada predicción con su fecha en la base; falta mostrarlo |
| 2 | **Métricas públicas con intervalo y tamaño de muestra** (RPS, log loss y Brier contra tasa base y cuotas sin margen) | Ningún bot abierto ni servicio comercial revisado lo publica [S]; hoy `/marcador` es solo de administradores |
| 3 | **Acierto por franja de confianza con n y calibración**, no un «% de acierto» | En el estudio de Tips.GG (parte interesada) 38 de 165 servicios fueron rentables y 4 de los 73 con 1.000 o más pronósticos ✔; soccerdino acertó 76 % con ROI −1,94 % [S] |
| 4 | **Texto de producto que lista las señales de alarma** | «Picks seguros», capturas como prueba, método no declarado, «IA» como argumento |

## D. Agente e IA
| # | Falta | Detalle |
|---|---|---|
| 1 | **Medir un modelo local para elegir herramientas** (Needle de 26 M o un Qwen3 8B) | Solo si el enrutador determinista falla; se compara con el conjunto dorado de 94 frases. Needle y Jev, Kev y Laya son modelos de decisión o de llamada a herramientas, no pronosticadores ✔ |
| 2 | **Verificador determinista de cifras en toda explicación** | Existe `depurar_cifras`; falta cubrir cada salida con un esquema y regenerar una vez si no coincide |

## E. Ingeniería y riesgo
| # | Falta | Detalle |
|---|---|---|
| 1 | **Alerta de deriva** | Avisar si el RPS en vivo se aleja del histórico (la regla 50/200 solo promueve) |
| 2 | **Términos y condiciones del modelo** | Por redactar: el alcance es el modelo, no el proyecto. Lo que cada fuente de datos permite sigue siendo lo que dicen sus términos (`FUENTES_DE_DATOS.md` §3) |
| 3 | **simd en el instalador portable** | Hoy lo enciende `laplace.py` si existen los binarios |

## F. Descartado por mala relación evidencia/coste o por regla del producto
Kelly y cualquier recomendación de apuesta (el producto nunca es casa de apuestas); un LLM como fuente de probabilidades (✔ arXiv 2607.17765: ninguno de 4 LLM supera el Brier del mercado en 104 partidos); KAN, JEPA, Mamba y Liquid para tablas (sin evidencia);
Weibull, Conway-Maxwell y cópulas (mejoran el ajuste de marcadores, sin ganancia medida en RPS del 1X2); GNN, LSTM y procesos gaussianos (sin evidencia frente al mercado y algunos resultados citados usan datos del propio partido [S]); modelos de Markov punto a punto de tenis (el fútbol no tiene puntos discretos);
Transfermarkt (copyright y bloqueo de bots [S]).

## Medición hecha: regresión del Elo entre temporadas (2026-11-12)
`backend/scripts/evaluar_regresion_temporada.py`, 45.680 partidos de prueba (desde 2023-07-01, 49 ligas), Elo encogido hacia 1500 en cada cambio de temporada con `r` = 0, 0,1, 0,2 y 0,3 ✔ (medido por nosotros).
| `r` | Con los pesos del modelo vigente (entrenados con r = 0) | Con pesos reentrenados para cada `r` (misma muestra de 30.000 partidos) |
|---|---|---|
| 0 | log loss 1,01779 | 1,01843 |
| 0,1 | +0,00042 (peor, z = +2,4) | **−0,00073 (z = −4,0; mejora en 33 de 49 ligas)** |
| 0,2 | +0,00151 (peor) | −0,00033 (z = −1,35, no significativo) |
| 0,3 | +0,00273 (peor) | +0,00057 (peor) |
Lectura honesta: la dirección es consistente en `r = 0,1`, pero el `r = 0` reentrenado con la muestra pequeña (1,01843) es peor que el modelo vigente (1,01779, entrenado con todos los datos); el mejor caso (1,0177) solo iguala al vigente (−0,00009). **No está demostrada una mejora sobre producción y no se promueve.**
Siguiente paso: llevar `regresion_temporada` como hiperparámetro a `afinar_modelo_laplace.py` con el entrenamiento completo (requiere que `EstadoLiga.actualizar` conozca la temporada) y decidir solo en validación, como las generaciones anteriores.

## G. Sistema ejecutable y seguridad del agente (añadido el 2026-11-12, de `LISTAS_POR_TIPO.md`)
| # | Falta | Detalle | Meta del plan |
|---|---|---|---|
| 1 | Inferencia y entrenamiento en Rust | Hoy solo la simulación; la inferencia tarda 0,6 ms en Python: solo si una medición lo exige | `MD-15` |
| 2 | Defensa contra la inyección de instrucciones y prueba adversarial del agente | No se encontró en el código; el «saneo» existente solo limpia mensajes de error | `MD-16` |
| 3 | Curva riesgo-cobertura de la abstención | Falta medir cuánto mejora el acierto al abstenerse según el umbral | `MD-17` |
| 4 | Paquete instalable, SDK y esquema JSON versionado de entrada y salida | Existe el OpenAPI en ejecución, no un documento versionado | `MD-18` |
| 5 | Hoja de datos legible del conjunto de entrenamiento | Hoy solo hash, procedencia y rango en la base | `MD-18` |
Hechos en la misma ronda: comando `predecir` por lotes y entrada HTTP con `pais` y `liga_id`.
