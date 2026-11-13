# ¿Qué es el modelo Laplace? ¿Se parece a un LLM, a un modelo tipo Jev o a un bot? (2026-11-12)

Análisis, no plan. Fuentes: el código leído esta ronda (rutas en cada fila), `docs/mejoras/modelo/05_AUDITORIA_MODELO_ACTUAL.md` y `01_INVESTIGACION_COMO_SE_CREAN_LLM.md` (que ya cubren el modelo g3 y cómo se crea un LLM) y dos investigaciones nuevas (anexos G y H en `un documento archivado del autor (no publicado)`, casi todo [S]: resúmenes de buscador).
Aclaración del autor que fija el vocabulario: **«bot» es la lógica interna del backend** (cómo se arma un pronóstico: fuentes, módulos, consenso, puertas de calidad, persistencia, publicación), no la interfaz de Telegram ni de WhatsApp. El informe H definió «bot» como interfaz de mensajería: esa parte se descartó. Regla permanente: `.claude/rules/bot-es-la-logica-del-backend.md`.

## 1. Respuesta corta
El modelo Laplace es un **modelo de predicción probabilística de fútbol** (ratings Elo + tasas de gol + regresión logística jerárquica). **No es un LLM** (no genera ni entiende texto) y **no es un modelo de decisión tipo Jev** (no clasifica texto ni elige entre opciones). Tampoco es el bot: el **bot** es el sistema que lo usa y lo combina con más fuentes.
Si hay que decir a cuál se parece más de los tres: a ninguno como modelo; **el conjunto (modelo + bot) es un sistema de pronóstico**, y su núcleo es un predictor estadístico. Lo que sí es parecido a un «modelo de decisión» es la **capa de reglas del bot** (consenso, puerta de calidad, abstención), que decide cuándo hablar y cuándo decir «sin pronóstico», pero con reglas escritas y medidas, no con un modelo aprendido.

## 2. Las piezas, con su código
| Pieza | Qué es | Entrada → salida | Cómo se crea y se evalúa | Dónde |
|---|---|---|---|---|
| **Modelo de predicción** (Laplace) | Estima la distribución de probabilidad de lo que aún no pasó | Equipos, liga, país, cuotas opcionales → probabilidades 1X2, goles esperados, marcadores, ambos marcan, más/menos, confianza, intervalos | Se **entrena** con 154.421 partidos reales; se evalúa walk-forward con RPS, log loss, Brier y ECE contra tasa base y mercado | `ml/laplace/`, `ml/dixon_coles.py`, `ml/metricas.py` |
| **Bot** (lógica del backend) | Orquesta: pide partidos y datos a varias fuentes, corre módulos (incluido el modelo), combina, decide si hay base para publicar, guarda y entrega | Un partido → un análisis con pick, confianza y motivos, o «sin pronóstico» con su motivo | **No se entrena: se programa**; se evalúa con pruebas de punta a punta y con la medición del consenso | `services/motor.py`, `analisis_completo*.py`, `consenso.py`, `calidad_datos.py`, `nivel_evidencia.py`, `top_picks.py`, `gateway*.py`, `colector_resultados.py`, trabajos programados |
| **Agente** | Conversa, elige herramientas, pide aprobación para lo sensible | Texto → respuesta o llamada a una herramienta | Reglas + IA opcional; se evalúa con un conjunto dorado de frases y recorridos | `services/agent_*.py` |
| **LLM** (de terceros) | Genera y entiende texto | Prompt → texto | Lo entrena el proveedor; nosotros solo lo **usamos** y verificamos lo que dice | `services/ai_client.py` (Gemini, Groq, Ollama Cloud, OpenRouter, Claude) |
| **Modelo de decisión tipo Jev** | Clasifica un texto con salidas cerradas y confianza | Texto + pregunta → sí/no, opción o nota 0-10 | Lo entrena su autor; evaluación con conjunto etiquetado | **No tenemos ninguno** (Jev, Kev, Laya y Needle se revisaron: sirven, si acaso, para el agente) |
| **Interfaces** | Telegram, web, PWA, app: solo muestran | — | — | `bot/`, `frontend/`, `pwa/`, `app-android/` |

## 3. En qué se parece y en qué no cada comparación
| | Laplace (modelo) | LLM | Modelo tipo Jev | Bot (lógica) |
|---|---|---|---|---|
| Aprende de datos | **Sí** (partidos reales) | Sí, de texto | Sí, de texto etiquetado | **No** (reglas escritas) |
| Entrada | Tabular: equipos, liga, cuotas | Texto libre | Texto + pregunta | Un partido y lo que devuelven las fuentes |
| Salida | **Probabilidades** que suman 1 | Texto | Una opción cerrada con confianza | Un análisis completo o «sin pronóstico» |
| Se evalúa con | Reglas propias (RPS, log loss, Brier) y calibración | Benchmarks y evaluaciones propias | Precisión, F1, riesgo-cobertura | Pruebas de punta a punta y mediciones del consenso |
| Puede inventar | No inventa cifras: calcula | **Sí** (alucina): hay que verificarlo | Se equivoca de opción, no inventa texto | No, pero puede combinar mal si falla una fuente |
| Qué parecido tiene con Laplace | — | Solo el LLM que *explica* las cifras; **nunca** da las probabilidades (✔ arXiv 2607.17765: ninguno de 4 LLM supera al mercado) | La capa de decisión del bot hace algo parecido con reglas | Es el sistema que lo rodea |

## 4. Entradas, salidas y generación de datos del modelo de fútbol
**Generación de datos** (de dónde sale lo que el modelo aprende): resultados, goles, tiros y cuotas de football-data.co.uk (maestro: 154.421 partidos, 49 ligas, 2012–2026; 137.297 con cuotas y 67.997 con tiros) → capa en vivo (resultados que el bot verifica) → capa «actual»
(temporada en curso, con ESPN para la Serie B) → partidos canónicos (nombres de equipo resueltos) → estado por equipo (Elo, tasas de gol, forma, tiros), reconstruido a diario en la base → entrenamiento walk-forward → artefacto versionado con huella SHA-256. Hay además un generador sintético
(`ml/laplace/simulacion.py`) para pruebas, que nunca se mezcla con partidos reales (`procedencia`).
**Entrada del modelo** (contrato `ml-1`): `local` y `visitante` (obligatorios), `liga`, `pais` y `liga_id` (opcionales: desambiguan ligas homónimas), `cuotas` (3 decimales previas al partido: activan `p1x2_con_mercado`). **Salida:** `p1x2`, goles esperados, marcadores, ambos marcan, más/menos
(solo los mercados que superaron a la tasa base fuera de muestra), `confianza`, `fuente` (`modelo_laplace`, `dixon_coles_historico` o `referencia_de_liga`), `degradado` y el motivo cuando no hay pronóstico.
**Cómo se ejecuta como sistema, sin Telegram:**
| Vía | Qué es | Estado |
|---|---|---|
| HTTP | `POST /api/v1/ml/predict` (público, 120 por minuto), `/predict/interno` con clave, `/sim/*`, `/verificar`, `/modelo`, `/health` | Existe |
| Línea de comandos | `modelo_laplace.py predecir --entrada partidos.csv --salida pronosticos.csv` (lote, solo lectura) y los de entrenar, evaluar y promover | `predecir` es **nuevo** (11 pruebas) |
| Biblioteca Python | `servicio.pronosticar_partido(db, entrada)` | Existe |
| Rust | Núcleo de la simulación (30,7× frente a Python), por stdin y stdout en JSON o por el servicio `simd` de Go | **Solo la simulación**: la inferencia (0,6 ms por pronóstico) y el entrenamiento siguen en Python |

## 5. Veredicto
1. Laplace es un modelo de predicción, no un LLM ni un modelo de decisión; su valor es dar probabilidades **calibradas y medidas**, algo que un LLM no hace.
2. El «bot» (la lógica del backend) es lo que convierte un modelo en un producto: fuentes con respaldo, puertas de calidad, abstención, persistencia. Ahí está la mayor parte del código.
3. Lo que más separa a Laplace de un sistema «completo» no es un tipo de modelo nuevo sino: monitorizar deriva, publicar el registro verificable, defensas contra la inyección de instrucciones en el agente y, si se quiere, inferencia en Rust. Las listas de lo que tenemos y falta por tipo están en `LISTAS_POR_TIPO.md`.
