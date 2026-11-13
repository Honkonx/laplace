# Qué debe tener cada tipo y qué tenemos (2026-11-12)

Complementa `QUE_ES_EL_MODELO.md`. Casillas: `[x]` lo tenemos (visto en el código o medido) · `[~]` parcial (con la salvedad) · `[ ]` nos falta · `[n/a]` no aplica porque no lo construimos nosotros.
Los criterios vienen de dos investigaciones (anexos G y H en `un documento archivado del autor (no publicado)`, casi todo [S]: resúmenes de buscador y documentación de proveedores) y, para el bot, del propio código. Es una lista de verificación, no un plan: lo que haya que construir va a `docs/mejoras/modelo/10_PLAN_MEJORAS_DEL_MODELO_Y_DATOS.md`.

## A. Modelo de predicción probabilística (Laplace)
| | Propiedad | Evidencia |
|---|---|---|
| [~] | Hoja de datos del conjunto de entrenamiento | `MlConjuntoDatos` guarda hash, procedencia, rango y filas; falta una hoja de datos legible con composición, fuentes y licencias (ver `FUENTES_DE_DATOS.md`) |
| [x] | Variables sin fuga del futuro | Estado partido a partido; el apilado usa cuotas de **apertura** (`ap_prom`) |
| [x] | Salida como distribución completa que suma 1 | `p1x2`, goles, marcadores (`ml/laplace/pronostico.py`) |
| [x] | Reglas de puntuación estrictamente propias | `ml/metricas.py`: RPS, log loss y Brier |
| [x] | Calibración con curva de fiabilidad y ECE | `entrenamiento.ece`; ECE 0,0083 en g2; isotónica en `services/calibracion.py` |
| [~] | Incertidumbre comunicada y abstención | Intervalos por covarianza y «sin pronóstico» con motivo; falta el rango conforme en el producto (`MD-7`) |
| [x] | Validación temporal walk-forward | Arnés y prueba desde 2023-07-01 que el ajuste no ve |
| [x] | Comparación con tasa base y mercado en los mismos partidos | `evaluar_modelo_laplace.py`, `comparar_versiones_modelo.py` (Diebold-Mariano, bootstrap en bloques) |
| [ ] | Monitorización de deriva con alerta | Existe el modo sombra y la regla 50/200, pero nada avisa si el RPS en vivo se aleja del histórico (`MD-13`) |
| [x] | Tarjeta del modelo y reproducibilidad | `ml/laplace/tarjeta.py`, huella SHA-256, semilla, registro de versiones |

## B. Bot: la lógica del backend que arma un pronóstico
Criterio propio [I], tomado de lo que el código ya hace y de buenas prácticas de sistemas que dependen de fuentes externas.
| | Propiedad | Evidencia |
|---|---|---|
| [x] | Cascada de fuentes con respaldo | LiveScore → BSD → API-Football (`services/gateway_cascada.py`); H2H y tabla con respaldo propio |
| [x] | Reintentos con espera y cortacircuitos | `services/_http_retry.py`, `circuit_breaker.py` |
| [x] | Caché con vigencia y fechas selladas | `stats_cache`; el colector sella una fecha ya completa |
| [x] | Puerta de calidad antes de publicar | `calidad_datos.py`: mínimo 2 fuentes independientes o un ancla; sin ellas, «Sin pronóstico» |
| [x] | Decir «sin pronóstico» con su motivo en vez de inventar | `analisis_completo.py`, `mensajes_analisis.py` (hasta 3 motivos) |
| [x] | Cola de trabajos e idempotencia | `procesar_job`, trabajos colgados, doble clic probado de punta a punta |
| [x] | Una función accesoria no rompe el flujo central | Regla y pruebas con la tabla ausente (`probar-como-usuario-no-solo-unidades.md`) |
| [x] | Registro de cada análisis y auditoría de acciones de administración | `analisis_comparativo`, `ml_prediccion`, `AccionAdminAuditoria` |
| [x] | Límites por plan y usuario | `usuarios_repo.verificar_limite`, acceso al simulador leído de la base |
| [x] | Trabajos programados con interruptores | 15 trabajos en `main.py` con banderas (`*_AUTOMATICO`) |
| [x] | Pruebas de punta a punta con las migraciones reales | Más de 3.600 pruebas; recorridos de Telegram, agente y rutas HTTP |
| [x] | Degradación ordenada sin IA | `formatear_mensaje_free` |
| [~] | Observabilidad | `/health` con el estado del esquema y métricas de la IA; falta alerta ante fuentes caídas más allá del diagnóstico diario |
| [ ] | Registro público verificable con sello de tiempo anterior al partido | Se guarda cada predicción con su fecha, pero no se muestra (`MD-12`) |

## C. LLM como componente (lo que exigimos de la IA que usamos; no entrenamos ninguno)
| | Propiedad | Evidencia |
|---|---|---|
| [~] | Versión fija y documentada | Los proveedores y modelos son configurables y en cascada; el prompt sí está versionado (`PROMPT_VERSION_TEXTO` y `_JSON`) |
| [n/a] | Datos de entrenamiento descritos | Lo publica el proveedor |
| [~] | Comportamiento verificado con pruebas propias | `medir_discrepancia_ia.py`, conjunto dorado del agente; falta un conjunto fijo de frases para cada cambio de proveedor |
| [ ] | Uso del contexto medido por posición | No medido |
| [x] | Llamada a herramientas con esquema estricto y validación nuestra | `ai_salida.py`, definiciones de herramienta, validación de entradas |
| [x] | Fundamentación y capacidad de decir «no sé» | La IA solo recibe cifras del motor, `depurar_cifras` descarta las que no están en el prompt, y sin pronóstico propio la IA ni corre |
| [~] | Evaluación propia contra una línea base | `medir_aporte_ia.py`; falta repetirla en cada cambio |
| [ ] | Red teaming y barandillas de entrada y salida | No hay una prueba adversarial formal |
| [~] | Plan de retiro o cambio de proveedor | La cascada de 5 proveedores lo permite; sin un procedimiento escrito |
| [x] | Riesgos y límites publicados | El aviso de estimación en cada respuesta y la regla de que la IA no da probabilidades |

## D. Agente con herramientas
| | Propiedad | Evidencia |
|---|---|---|
| [x] | Bucle con tope de iteraciones | `ai_herramientas.MAX_VUELTAS` limita las vueltas de herramientas del agente con IA (corregido: primera búsqueda no lo encontró) |
| [x] | Mínimo privilegio | Herramientas con lista cerrada; lo sensible exige aprobación |
| [x] | Autorización en el sistema, no en el modelo | El plan se lee de la base en cada llamada; comandos de administrador con `solo_admin` |
| [x] | Un humano aprueba lo de alto impacto | `AgentApproval`, `/decidir`, expiración de aprobaciones |
| [~] | No combinar datos privados, contenido no confiable y salida al exterior | Sin revisión específica de esa combinación |
| [ ] | Defensa contra la inyección de instrucciones | **No la encontré**: el «saneo» que aparece solo limpia mensajes de error (`ai_metrics.sanitizar_error`) |
| [x] | Límites de uso | `agent_guard`: mensajes por minuto por chat, cuota de IA por plan |
| [x] | Registro auditable | Auditoría de herramientas (se conserva incluso en modo incógnito) |
| [x] | Pruebas de regresión aisladas | `qa_agent_*`, conjunto dorado de 94 frases, 260 casos del bot del agente |
| [x] | Degradación definida y modo sin IA que no inventa | Respuestas deterministas |

## E. Modelo de decisión (tipo Jev): no tenemos uno aprendido, pero sí una capa de decisión con reglas
| | Propiedad | Evidencia |
|---|---|---|
| [x] | Espacio de salidas cerrado | Pick, «Sin pronóstico» y niveles de evidencia (`nivel_evidencia.py`) |
| [x] | Confianza calibrada | Etiquetas ALTA, MEDIA y BAJA fijadas con frecuencias reales |
| [x] | Abstención como salida de primera clase | «Sin pronóstico propio» con motivo |
| [ ] | Umbral derivado de la matriz de costes de error | No hay costes: no se apuesta; los umbrales salen de la calibración |
| [x] | Conjunto etiquetado y separado por tiempo | Walk-forward con prueba intocable |
| [~] | Precisión, F1 y curva riesgo-cobertura | RPS, log loss y ECE sí; **falta la curva riesgo-cobertura** de la abstención |
| [~] | Robustez a ruido y casos fuera de distribución | Fuentes caídas probadas; sin pruebas de entradas fuera de distribución |
| [x] | Latencia y coste con tope | 0,6 ms por pronóstico; cuota de IA por plan |
| [x] | Versionado de modelo, prompt y umbrales | Familia versionada y `PROMPT_VERSION` |
| [~] | Registro de cada decisión y revisión humana de lo dudoso | Se registra todo; la revisión humana solo existe para acciones del agente |

## F. Modelo ejecutable como sistema (Python y Rust), no solo por Telegram
| | Propiedad | Evidencia |
|---|---|---|
| [x] | API HTTP con contrato versionado | `/api/v1/ml/*`, contrato `ml-1`, OpenAPI de FastAPI |
| [x] | Línea de comandos por lotes (CSV o JSON → CSV o JSON) | `modelo_laplace.py predecir` (nuevo, solo lectura) |
| [x] | Entrada con país e id de liga para ligas homónimas | `pais` y `liga_id` en `EntradaPronostico` (nuevo) |
| [x] | Núcleo de simulación en Rust con respaldo | `modelo/rust/lsim`, Go y Python |
| [ ] | Inferencia y entrenamiento en Rust | Hoy son Python; solo tendría sentido si una medición lo exige (`MD-15`) |
| [ ] | Paquete instalable y SDK | No existen |
| [ ] | Esquema JSON público de entrada y salida | Existe el OpenAPI en ejecución, no un documento versionado |
