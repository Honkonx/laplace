# Algoritmos de otros deportes y familias generales: qué se transfiere al fútbol (2026-11-12)

Resumen del anexo E (`un documento archivado del autor (no publicado)*`). Casi todo es **[S]** (resumen o fragmento de buscador): solo se leyó entero Egidi et al. 2025 (arXiv 2508.05891) **[C]**. La transferibilidad es **[I]** en todos los casos y nada se probó con datos de Laplace salvo donde se indica.

## 1. Los que más prometen para «Elo + tasas de gol + logística jerárquica»
| # | Idea | De dónde | Qué haría en el fútbol | Coste | ¿Ya lo tenemos? |
|---|---|---|---|---|---|
| 1 | Multiplicador de margen con rendimientos decrecientes y ajuste de autocorrelación | Elo de NFL, NBA y NHL (FiveThirtyEight) | Que una goleada mueva el Elo con menos de proporcionalidad y sin sobrerreaccionar al favorito | minutos | **Parcial**: ya hay `1 + 0,25·min(|dif|, 3)`; falta el ajuste por favorito |
| 2 | Regresión a la media entre temporadas y K por competición | Elo de NHL: K = 6 y 30 % hacia la media [S] | Compensa la rotación de plantillas | minutos | **No** (medido: señal débil, no demostrada; `LO_QUE_NOS_FALTA.md`, A1) |
| 3 | Elo mezclado con contexto | Tenis: mezcla de 0,71 global y 0,29 de superficie [S] | Elo de competición o de local y visitante, con pesos reajustados | bajo | **Parcial**: la variable `localia` (desvío local y visitante) |
| 4 | Incertidumbre de rating (Glicko, TrueSkill) | Ajedrez, tenis, videojuegos; en fútbol Lasek 2013 [S] | Una desviación por equipo: recién ascendidos y simulación con incertidumbre | bajo | **No** |
| 5 | Estado-espacio / Kalman de ataque y defensa | Koopman y Lit, Rue y Salvesen; DARKO en NBA | Sucesor natural de Elo + tasas de gol; Egidi 2025 [C] baja el Brier de 0,616–0,619 a 0,602 y el RPS de 0,232–0,233 a 0,224 en las últimas 3 jornadas de 2024/25 (mejora modesta y de una sola temporada) | medio | **No** |
Menciones: pitagórica (exponente ~1,83 en béisbol) como variable de suerte y regresión; vecinos similares tipo PECOTA o CARMELO para equipos sin historia.

## 2. Tabla completa
| Algoritmo o familia | Deportes donde destaca | Datos que exige | Transferible al fútbol | Coste |
|---|---|---|---|---|
| Elo con margen y autocorrelación | NFL, NBA, NHL, rugby | Resultado y marcador | Sí | trivial |
| Regresión a la media entre temporadas | NHL, NFL | Calendario | Sí | trivial |
| Glicko y Glicko-2 | Ajedrez, tenis, fútbol (Lasek) | Resultados | Sí | bajo |
| TrueSkill | Videojuegos, equipos | Resultados y alineaciones | Parcial | medio |
| Poisson, bivariante, Skellam, Dixon-Coles | Fútbol, hockey | Goles | Sí (ya está) | bajo |
| Logística ordinal o jerárquica | Fútbol, tenis | Variables previas | Sí (ya está) | bajo |
| Bayesiano jerárquico | Fútbol | Goles por temporada | Sí; ganancias modestas | medio |
| Kalman y espacio de estados | Fútbol, NBA | Goles en el tiempo | Sí | medio |
| Procesos gaussianos | Fútbol (tiros) | Tiros y goles | Parcial | alto |
| Gradient boosting | Fútbol, tenis | Variables construidas | Sí como meta-modelo; no batió a las cuotas en Baboota y Kaur 2019 (RPS 0,2156 frente a 0,2012) [S] | bajo-medio |
| LSTM y secuenciales | Críquet | Secuencias | Parcial; sin evidencia frente al mercado | medio |
| Redes de grafos | Tenis, fútbol (pases) | Grafos y eventos | Parcial; datos de pago | alto |
| Supervivencia | Fútbol en vivo, críquet | Tiempos de gol | Solo en vivo | bajo-medio |
| Markov punto a punto | Tenis | % de saque y resto | **No** (el fútbol no tiene puntos discretos) | medio |
| Pitagórica | Béisbol, NBA, NFL | Goles a favor y en contra | Sí, como variable | trivial |
| Monte Carlo de temporada | Rugby, NFL, NBA | Probabilidades de partido | Sí (ya está) | ya en Rust y Go |
| Ensambles y apilado | Fútbol, tenis | Salidas de varios modelos | Sí con walk-forward | bajo |
| Calibración y conforme | NCAA baloncesto, general | Probabilidades y resultados | Sí; probar beta antes que isotónica | bajo |

## 3. Lo que sale peor parado
XGBoost no batió a las cuotas [S]; GNN, LSTM y procesos gaussianos sin evidencia frente al mercado y algunos resultados altos citados usan datos del propio partido [S]; la supervivencia solo aporta en vivo; los modelos de Markov punto a punto no se transfieren.

## 4. Lo que no se pudo verificar
La matemática exacta de DARKO, RAPTOR, ZiPS, PECOTA y del ajuste de QB; cifras de acierto o Brier de FiveThirtyEight NBA y NFL; los resultados de la GNN de tenis; quién gana entre Elo y Glicko en fútbol (solo un resumen de Lasek y trabajo de aficionado); el exponente pitagórico para fútbol; la ganancia real de Koopman y Lit frente al mercado; la analogía entre Glicko y Kalman es del subagente, sin vínculo documentado.
