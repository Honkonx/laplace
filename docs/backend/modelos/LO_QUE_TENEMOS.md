# Lo que tenemos (inventario leído del código, 2026-11-12)

Cada fila apunta al archivo donde vive. Las cifras de rendimiento son las medidas fuera de muestra del documento vigente `docs/backend/MODELO_LAPLACE.md`; aquí no se repiten mediciones nuevas.

## A. Modelos de pronóstico (1X2, goles, marcadores)
| Pieza | Qué hace | Dónde | Estado |
|---|---|---|---|
| **Modelo Laplace** (Elo + tasas de gol con memoria + forma + tiros → regresión logística jerárquica por liga) | Pronóstico 1X2 y de goles propio, entrenado con el histórico real; en servicio la generación `g3` | `ml/laplace/entrenamiento.py`, `servicio.py` | Activo. Prueba desde 2023-07-01 (44.289 partidos, 49 ligas): log loss 1,0214 y RPS 0,2101 frente a 1,0712 y 0,2272 de la tasa base |
| Variante con tiros (`v1.1`) | Añade tiros y tiros a puerta como señal | `ml/laplace/entrenamiento.py` (variable extra `tiros`) | En sombra: no se promueve sin tiros en vivo |
| **Dixon-Coles** semanal | Ataque y defensa por equipo, ventaja de local y corrección de marcadores bajos | `ml/dixon_coles.py`, `services/modelo_historico*.py` | Activo como módulo `historico` y respaldo del modelo propio |
| **Apilado con el mercado** | Combina el modelo con las cuotas sin margen (método de Shin) | `ml/laplace/apilado.py`, `ml/mercado.py` | Activo con cuotas: 0,9946 frente a 0,9957 del mercado solo (20.960 partidos) |
| Prior de equipo nuevo | Pronóstico para un equipo sin historia (un ascendido) | `services/modelo_historico.py`, `ml/laplace/servicio.py` (`_desde_liga`) | Activo; medido: un equipo nuevo gana a la tasa base (RPS 0,2120 frente a 0,2253), dos no |
| Consenso de módulos | Mezcla ponderada de `odds` 0,70, `historico` 0,25, `tabla` 0,03 y `forma` 0,02 (`poisson`, `h2h` y `bsd_ml` con peso 0) | `services/consenso.py` | Activo; la evaluación walk-forward fijó los pesos |
| Módulos del consenso | Poisson, forma, H2H (con respaldo del historial propio), cuotas, tabla (con respaldo de la tabla propia), histórico, BSD | `services/pronostico.py`, `form_recent.py`, `h2h*.py`, `odds*.py`, `tabla_pos.py`, `tabla_propia.py`, `bsd_predictions.py` | Activos |
| Laboratorio de pronósticos | Variantes que corren en vivo en sombra para medirse (50 partidos exploratorio, 200 para promover) | `services/laboratorio_pronosticos.py`, `laboratorio_modelo_laplace.py` | Activo |

## B. Simulación y cálculo
| Pieza | Qué hace | Dónde | Estado |
|---|---|---|---|
| Simulador de temporada | Monte Carlo de campeón, copa y descenso con incertidumbre de la fuerza de cada equipo (σ = 0,12) | `ml/laplace/liga.py`, `services/simulador_propio.py` | Activo; validado con un backtest de 57 temporadas (cobertura 0,90) |
| Núcleo nativo | Rust (30,7× frente a Python), Go de respaldo y servicio local; Python como referencia | `modelo/rust/lsim`, `modelo/go/lsim`, `modelo/go/simd`, `ml/laplace/motor_*.py` | Activo; cadena Rust → Go → Python |
| Simulación interna frente a pública | Backtests y escenarios sintéticos en la máquina de desarrollo; la pública solo para planes pro/max y administradores | `scripts/backtest_temporadas.py`, `routers/simulador.py` | Activo |

## C. Incertidumbre, calibración y decisión
| Pieza | Qué hace | Dónde | Estado |
|---|---|---|---|
| Calibración | Isotónica sobre datos de backtest; ECE medido (0,0083 en g2) | `services/calibracion.py`, `services/backtesting.py` | Activo |
| Intervalos por covarianza y abstención | Incertidumbre de la probabilidad y «no decidir» | `ml/laplace/incertidumbre.py` | Activo |
| Etiquetas de confianza calibradas | ALTA ≥ 0,60, MEDIA 0,50–0,60, BAJA < 0,50, con frecuencias reales | `services/consenso.py`, `nivel_evidencia.py` | Activo |
| Puerta de calidad de datos | Sin fuentes independientes no se publica pronóstico | `services/calidad_datos.py` | Activo |
| Predicción conforme | Conjuntos de resultados con cobertura medida (79,5 % para 80 %) | `ml/laplace/conformal.py` | Solo experimento (no está en el producto) |

## D. Datos
| Pieza | Qué trae | Dónde | Estado |
|---|---|---|---|
| Maestro histórico | 154.421 partidos, 49 ligas, 2012–2026; 137.297 con cuotas y 67.997 con tiros | `backend/data/datos/football-data/` (no se publica) | Activo |
| Capa en vivo | Resultados que el bot verifica; ahora admite equipos recién llegados | `ml/vivo.py`, `scripts/exportar_resultados_vivos.py` | Activa |
| Capa «actual» | Temporada en curso: football-data.co.uk (34 ligas) y ESPN (Serie B de Brasil) | el actualizador de la capa «actual» (no publicado) | Diaria 06:15 |
| Memoria del modelo en la base | Estado por equipo de cada liga, reconstruido a diario | `ml/laplace/estado_vivo.py`, tabla `ml_estado_vivo` | Diaria 06:40 y 13:40 |
| Fuentes externas | LiveScore6 (partidos y país), API-Football (plan gratis), BSD (predicciones y xG), The Odds API y OddsPapi (cuotas), football-data.org (tabla) | `services/gateway*.py`, `*_fetch.py` | Activas con sus límites |
| Identidad de la competición | Nombre + país (`premier-league-england`) | `services/ligas_ident.py` | Activa |

## E. IA y LLM
| Pieza | Qué hace | Dónde | Estado |
|---|---|---|---|
| Cascada de proveedores | Gemini, Groq, Ollama Cloud, OpenRouter y Claude como último recurso | `services/ai_client.py` | Activa |
| Rol de la IA | Explica y contrasta; **nunca** produce probabilidades | `services/ai_prompts.py`, `consenso_ia.py` | Regla del producto |
| Verificación de lo que dice la IA | Cifras sin respaldo en el prompt se descartan; salida estructurada validada; crítico opcional | `consenso_ia.depurar_cifras`, `ai_salida.py`, `ai_critico.py` | Activa |
| Agente | Herramientas deportivas, memoria, aprobaciones, sesiones, simulador por plan | `services/agent_*.py`, `bot/laplace_agent_bot*.py` | Activo |

## F. Evaluación e ingeniería
Arnés walk-forward contra tasa base, mercado y modelo vigente (`scripts/evaluar_modelo_historico.py`, `evaluar_modelo_laplace.py`, `comparar_versiones_modelo.py` con Diebold-Mariano y bootstrap en bloques); registro de modelos y predicciones en la base (`ml/laplace/registro.py`);
evaluación de consenso (`ml/evaluacion_consenso.py`); mediciones puntuales (`evaluar_equipo_nuevo_laplace.py`, `evaluar_conformal.py`, `cobertura_modulos.py`, `medir_motores.py`); 15 trabajos programados; más de 3.500 pruebas, incluidos recorridos de punta a punta con migraciones reales.

## G. Interfaces
Bot deportivo de Telegram, bot del agente de Telegram, web y PWA (casi iguales) y app Android (la de menor prioridad).
