# Diferencias entre los enfoques de pronóstico (2026-11-12)

Misma convención de marcas que en `LO_QUE_NOS_FALTA.md` (✔ contrastado, [S] resumen, [I] inferido, [?] sin evidencia). La columna «Lo tenemos» remite a `LO_QUE_TENEMOS.md`.

## 1. Familias de modelos
| Enfoque | Qué predice | Qué necesita | Fortaleza | Límite | Evidencia | Lo tenemos |
|---|---|---|---|---|---|---|
| **Ratings tipo Elo** (también Glicko, TrueSkill, pi-ratings) | Fuerza relativa; el 1X2 sale de una función de la diferencia | Solo resultados (y marcador) | Simple, barato, sirve con pocos datos | No separa ataque de defensa; sin incertidumbre propia (Elo) | Hvattum y Arntzen 2010: por encima de modelos econométricos y por debajo de las casas [S] | Sí (Elo con margen); sin incertidumbre ni regresión entre temporadas |
| **Modelos de goles** (Poisson, bivariante, Dixon-Coles, Skellam) | Distribución de goles → 1X2, marcadores, más/menos | Goles por equipo | Da marcadores y mercados de goles; interpretable | Supone independencia (se corrige a medias); ataque y defensa fijos en el tiempo | Desafío 2017: el Poisson jerárquico fue el mejor (RPS 0,2047) pero sobre **206 partidos** ✔ | Sí (Dixon-Coles y tasas de gol con memoria) |
| **Regresión logística / ordinal** | Probabilidad directa de H, D y A a partir de variables | Variables previas al partido (ΔElo, forma, tiros) | Calibra bien, fácil de auditar | Solo captura lo que le des como variable | Base del modelo propio; 1,0214 de log loss en 44.289 partidos ✔ (documento del modelo) | Sí (jerárquica por liga) |
| **Bayesiano jerárquico** (Baio y Blangiardo, Egidi) | Igual que los de goles, con contracción hacia la liga | Goles, equipos por temporada | Maneja pocos datos y da incertidumbre natural | Lento (MCMC); ganancias modestas | Egidi 2025: Brier de 0,616 a 0,602 en una temporada ✔ (leído por el subagente) | Parcial (jerarquía por liga con L2; sin MCMC) |
| **Estado-espacio / Kalman** | Ataque y defensa que cambian en el tiempo | Goles en secuencia | Sucesor natural de «Elo + tasas de gol» | Más complejo de ajustar | Koopman y Lit: retorno positivo frente a cuotas en la Premier [S] | No |
| **Aprendizaje automático** (XGBoost, redes, TabPFN) | Probabilidades a partir de muchas variables | Variables construidas sin fuga | Puede capturar interacciones | Con ~10 mil filas por liga los árboles ganan a las redes (Grinsztajn) [S]; no batió a las cuotas (RPS 0,2156 frente a 0,2012) [S] | Débil | No (solo propuesto en sombra) |
| **El mercado (cuotas sin margen)** | Probabilidad implícita del precio | Cuotas previas al partido | Agrega la información de miles de apostantes y casas | No existe para todas las ligas ni partidos; no se «posee» | Gana a casi todo modelo estadístico; los modelos solo suman combinándose con él [S]; en nuestros datos 0,9957 frente a 1,0131 del modelo en 20.960 partidos ✔ | Sí (Shin, apilado) |
| **Ensamble / apilado** | Combina salidas de varios modelos | Pronósticos previos de cada uno | Mejora pequeña pero estable | Con módulos dependientes la ganancia es pequeña | Apilado con cuotas 0,9946 frente a 0,9957 ✔ | Sí (consenso y apilado) |
| **LLM como pronosticador** | Una probabilidad o un pick escrito | Un prompt | Comenta y contrasta | No supera al mercado; el 92 % de los picks coincide entre modelos | arXiv 2607.17765 ✔ (4 LLM, 104 partidos); KellyBench: todos pierden [S] | Descartado por regla |
| **LLM como explicador y de herramientas** | Texto sobre cifras que le damos y llamadas a herramientas | Cifras verificadas y esquema de salida | Hace legible el análisis | Puede inventar cifras: hay que verificarlas | Ji 2023 sobre alucinación [S]; benchmark de Docker: Qwen3 14B 0,971 de F1 de selección de herramienta y modelos especializados mucho peor [S] | Sí (verificación de cifras, salida estructurada) |
| **Modelos de decisión pequeños** (Jev, Kev, Laya, Needle) | Etiqueta, nota 0-10 o llamada a herramienta | Texto | Rápidos y baratos; Needle de 26 M en el dispositivo | No dan probabilidades de partido | The Batch y búsqueda propia ✔ | No (candidato para el agente, medido) |
| **Predicción conforme** | Un **conjunto** de resultados con cobertura | Probabilidades y partidos de calibración | Honestidad sobre la incertidumbre | Garantía marginal, no por partido; el 1X2 se acota poco (2 de 3 resultados al 80 %) | Medido por nosotros ✔ | Experimento |
| **Simulación Monte Carlo** | Campeón, copa y descenso desde probabilidades de partido | Tabla y partidos pendientes | Convierte partidos en preguntas de temporada | Hereda los errores del modelo de partido | Backtest de 57 temporadas con cobertura 0,90 ✔ | Sí (Rust, Go y Python) |

## 2. Qué responde cada cosa (para no confundirlas)
| Pregunta del usuario | Se contesta con | Observación |
|---|---|---|
| «¿Quién gana?» | Probabilidades 1X2 del modelo y/o del mercado | Siempre con su incertidumbre |
| «¿Cuántos goles?», «¿ambos marcan?» | Modelos de goles | Solo se muestran los mercados que superaron a la tasa base fuera de muestra |
| «¿Quién será campeón?» | Simulación Monte Carlo | Solo planes pro/max y administradores |
| «¿Por qué?» | La IA explicando cifras verificadas | La IA no produce probabilidades |
| «¿Cuánto me puedo fiar?» | Etiqueta de confianza calibrada, nivel de evidencia y (a futuro) rango conforme | Nunca «pick seguro» |

## 3. Diferencias que cambian decisiones
1. **Rating frente a goles**: el rating es más estable con pocos datos; el modelo de goles da marcadores. Por eso el nuestro usa los dos (Elo y tasas de gol).
2. **Modelo frente a mercado**: el mercado gana donde existe; el modelo propio vale por independencia, cobertura sin cuotas y calibración. Por eso el apilado ancla al mercado.
3. **Garantía frente a precisión**: conforme garantiza cobertura promedio pero no afina el pronóstico; calibración mejora la escala de las probabilidades; ninguna de las dos sustituye a un modelo mejor.
4. **Explicar frente a predecir**: los LLM y los modelos pequeños de decisión ayudan a explicar y a enrutar; las probabilidades salen de modelos medidos.
