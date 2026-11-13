# Bots, productos y modelos de IA que pronostican deportes (2026-11-12)

Resumen de la investigación del anexo D (`un documento archivado del autor (no publicado)*`). Marcas: **✔** contrastado por el asistente principal, **[C]** confirmado en la fuente por el subagente, **[S]** resumen o fragmento, **[I]** inferido, **[?]** sin evidencia.
La mayoría de la columna de evidencia es [S]: no se abrieron los repositorios ni se leyeron los PDF completos.

## 1. Panorama
| Proyecto o servicio | Qué hace | Método | Evidencia de acierto | Fiabilidad |
|---|---|---|---|---|
| Bots de Telegram abiertos (por ejemplo, de regresión de Poisson o de tips con API de terceros) | Pronóstico o tips | Simple o no detallado | Ninguna vista | Baja [?] |
| Forebet | 1X2, goles y marcador | No divulgado | Sin métricas propias | Muy baja [S] |
| FiveThirtyEight SPI (cerrado) | Ratings y pronósticos de clubes | Ofensiva y defensiva, Poisson, Monte Carlo | CSV de predicciones desde 2016; no se vio evaluación | Media [S] |
| Opta Supercomputer | Probabilidades de liga | Cuotas + ranking propio + simulación | Sin métrica vista | Baja [S] |
| Club Elo | Rating Elo | Elo | No verificado | [?] |
| Pinnacle (precio de cierre) | Mercado | Gestión de riesgo y flujo de dinero | Referente de eficiencia | Media-baja [S] |
| Desafío de Predicción 2017 | 206 partidos de prueba | Árboles potenciados + pi-ratings (ganador); Poisson jerárquico con RPS 0,2047 en el artículo de Tsokos et al. | Muestra pequeña ✔ | Media |
| WC2026-Agents (arXiv 2607.17765) | 4 LLM contra el mercado en 104 partidos | Prompts | **Ninguno supera al mercado en Brier** ✔ | Media (n = 104) |
| LLM-SoccerArena (arXiv 2607.24573) | Benchmark prospectivo de LLM con pronósticos validados y con sello de tiempo | Factorial | Acceso web mejora el Brier en 0,023 [C] | Media |
| KellyBench (arXiv 2604.27865) | LLM apostando una temporada de Premier | Agentes con ML propio | Todos pierden dinero [C] (−8 % en el resumen, −10,97 % en prensa: sin resolver) | Media |
| Tips.GG (estudio de enero a agosto de 2026) | Ranking de 165 servicios con apuesta plana | Margen de la casa no descontado (8,19 % de media) | **38 de 165 con ganancia; 4 de 73 entre los de 1.000 o más pronósticos** ✔ | Media-baja: es parte interesada |
| Brown y Reade | Sabiduría de tipsters amateurs | Mayoría de tips | +1,317 % sobre 68.339 eventos [C] (resumen) | Alta [C] |
| Redes de «partidos fijos» en Telegram | Venta de picks «seguros» | Ninguno | Capturas de pantalla | Nula [S] |

## 2. Señales de poca fiabilidad (para no parecernos y para el texto de producto)
Acierto sin tamaño de muestra ni cuota; «picks seguros»; capturas de pantalla como prueba, picks borrados o cuotas cambiadas; método no declarado o «IA» como argumento (en Tips.GG la etiqueta «IA» no mejora el resultado [C]); muestras de pocas semanas.

## 3. Diferencias con Laplace
| Aspecto | Lo habitual en bots y servicios | Laplace |
|---|---|---|
| Método | No declarado | Declarado: Elo y tasas de gol → logística jerárquica, apilado con el mercado sin margen |
| Evidencia | Acierto sin n | RPS y log loss contra tasa base y mercado sobre los mismos partidos; walk-forward; prueba que el ajuste no ve |
| Mercado | Se ignora o se vende como pick | Insumo y referencia; el apilado lo ancla |
| IA | Argumento de venta | Explica y contrasta; nunca produce probabilidades |
| Honestidad | «Picks seguros» | Etiquetas de confianza calibradas, abstención y «sin pronóstico propio» con su motivo; nunca casa de apuestas |
| Registro | Capturas | Cada predicción se guarda con su fecha; **falta mostrarla públicamente** (ver `LO_QUE_NOS_FALTA.md`, C1) |

## 4. Lo más útil que se aprende
1. Publicar RPS o Brier con intervalo y tamaño de muestra, contra tasa base y cuotas sin margen, es un diferenciador (ninguno de los revisados lo hace [S]); no prometer superar al mercado.
2. El acierto sin cuota engaña: mostrar acierto por franja de confianza con n y calibración.
3. Registro con sello de tiempo anterior al partido.
4. El LLM no da las probabilidades (✔ arXiv 2607.17765).
5. Un ensamble simple y calibrado basta: ganó el desafío de 2017 un modelo de árboles con pi-ratings [S] y en Kaggle March Mania 2023 un XGBoost simple [S].

## 5. Lo que no se pudo verificar
Método y acierto medido de Club Elo y de Understat; los RPS exactos del podio de 2017 (la cifra 0,1925 que circula no se confirmó); el Brier de LLM-SoccerArena frente al cierre; el código real de los repositorios de GitHub y Discord; si algún modelo profundo supera a las cuotas en fútbol con una muestra grande (la búsqueda fue acotada: no es prueba de que no exista).
