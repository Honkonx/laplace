# Referencia de scripts

> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).

## Lanzadores de la raíz

| Script | Para qué |
|---|---|
| `instalar.bat / instalar.sh` | Instala Laplace: Python y Node propios, dependencias, `.env`, primer administrador. |
| `configurar.bat / configurar.sh` | Menú para ver, probar, poner o cambiar las claves y el orden de la IA (`install/comun/configurar.py`). |
| `iniciar.bat / iniciar.sh` | Enciende API + bot de Telegram + planificador + web, y el agente. |
| `laplace.bat / laplace.sh` | Control general: `iniciar`, `detener`, `estado`, `doctor`, `configurar`… |

## `backend/scripts/`

Se ejecutan con el Python del entorno: `python backend/scripts/<nombre>.py --help`.

| Script | Qué hace |
|---|---|
| `acuerdo_modelo_bot.py` | si se le dan los mismos datos al modelo Laplace y al bot, ¿dan un resultado parecido? Solo lectura de los CSV históricos. |
| `afinar_modelo_laplace.py` | elige hiperparámetros y características del modelo Laplace SIN mirar el periodo de prueba. |
| `auditar_integridad.py` | cuenta, en SOLO LECTURA, los registros huérfanos de las relaciones lógicas de la base de datos (no hay claves foráneas declaradas). |
| `backfill_module_results.py` | Completa `analisis_modulos.pick_correcto` desde resultados ya verificados. |
| `backfill_resultados_laboratorio.py` | Copia a `resultados_partidos` los partidos terminados de `partidos_dia` que faltan, y califica con ellos lo que estaba pendiente (comparativos, módulos, predicciones… |
| `backtest_temporadas.py` | ¿el simulador de temporadas (`ml/laplace/liga.py`) acierta lo que dice? (MM-22/MM-23). |
| `cobertura_modulos.py` | Cuántos módulos de pronóstico votaron en los análisis guardados, por liga (solo lectura sobre `analisis_comparativo`). |
| `comparar_versiones_modelo.py` | compara dos versiones del modelo Laplace con significancia (walk-forward, mismos partidos, corte fijo). |
| `construir_go.py` | compila los programas en Go: el núcleo Monte Carlo de respaldo (`modelo/go/lsim`) y el microservicio del simulador (`modelo/go/simd`) a `modelo/go/bin/`. |
| `construir_rust.py` | compila el núcleo Monte Carlo en Rust (`modelo/rust/lsim`) a `modelo/rust/bin/lsim[.exe]`. |
| `create_admin.py` | Crea o actualiza un administrador global local. |
| `diagnostico_cobertura_vivo.py` | ¿qué responde HOY el bot a los partidos reales de una fecha? |
| `diagnostico_telegram.py` | comprueba contra el Telegram REAL que cada bot configurado puede recibir tus clics. |
| `doctor.py` | diagnóstico de una instalación de Laplace («laplace doctor»). |
| `ensayo_agente.py` | Ensayo del agente sin Telegram: corre una conversación típica (seguir un equipo, avisos, perfil, pronóstico, perfil de equipo, jerga y fechas) y muestra cada… |
| `evaluar_conformal.py` | Mide, fuera de muestra, si la predicción conforme (`ml/laplace/conformal.py`) cumple su cobertura con los datos y el modelo REALES de Laplace. |
| `evaluar_consenso_historico.py` | mide el CONSENSO REAL completo contra el mercado. |
| `evaluar_equipo_nuevo.py` | ¿qué probabilidad dar cuando un equipo no está en el modelo? |
| `evaluar_equipo_nuevo_laplace.py` | Mide si el modelo Laplace, con los valores por defecto de un equipo sin historia (Elo 1500, tasas medias de la liga), le gana a la tasa base de su liga. |
| `evaluar_modelo_historico.py` | evaluación walk-forward con datos históricos reales. |
| `evaluar_modelo_laplace.py` | mide el modelo propio de Laplace con PARTIDOS REALES, walk-forward, contra tasa base, Dixon-Coles y mercado. |
| `evaluar_proveedores_ia.py` | Evalúa a cada proveedor de IA con lo que el agente realmente le pide, antes de activarlo o al cambiar de proveedor o de modelo (MP-17) y mide si un modelo pequeño… |
| `evaluar_regresion_temporada.py` | Mide si encoger el Elo hacia la media al cambiar de temporada (la «regresión a la media» del Elo de NHL y NFL) mejora el pronóstico 1X2 de Laplace. |
| `exportar_resultados_vivos.py` | capa de resultados en vivo para reajustar los modelos. |
| `generar_conocimiento_equipos.py` | perfiles de equipo calculados del histórico real. |
| `generar_conocimiento_ligas.py` | base de conocimiento por liga, calculada. |
| `generar_referencia_docs.py` | genera las referencias técnicas de `docs/backend/referencia/` a partir del CÓDIGO (no de otros documentos). |
| `laplace_auditor.py` | Auditoría real de winrate/calibración, contra la BD real. |
| `limpiar_huerfanos.py` | retira de la base SQLite los datos de prueba y las filas corruptas conocidas, con respaldo previo y un archivo de lo retirado. |
| `medir_aporte_ia.py` | informe del aporte de la IA (python_baseline vs python_plus_ia del laboratorio). |
| `medir_calibracion_por_liga.py` | Mide si calibrar por liga (temperatura propia de cada liga) mejora al modelo, fuera de muestra (MD-6). |
| `medir_cobertura_historico.py` | mide qué fracción de los partidos reales resuelve el módulo `historico`. |
| `medir_colector.py` | cobertura de la capa en vivo, por liga con modelo (SOLO lectura). |
| `medir_discrepancia_ia.py` | ¿cuando la IA diverge del consenso, éste falla más? (MB-15). |
| `medir_equipo_nuevo_elo.py` | Mide si un rating inicial propio para un equipo que el modelo no conoce (recién llegado a la liga) mejora al modelo Laplace (MP-10), fuera de muestra y con la puerta… |
| `medir_intervalos.py` | Estudio de intervalos de credibilidad de las probabilidades (MP-16): ¿un posterior bayesiano completo (pymc/MCMC) aportaría algo sobre los intervalos que el modelo ya… |
| `medir_mercados_de_goles.py` | Mide, fuera de muestra, los mercados de goles del modelo Laplace (más de 2,5 y ambos marcan) frente a la tasa base y, donde hay cuotas, frente al mercado (MP-11). |
| `medir_modelo_segmentos_y_cierre.py` | Mide el modelo Laplace por segmentos (MP-15) y frente a la línea de cierre del mercado (MP-6), fuera de muestra y sin mirar el futuro. |
| `medir_motores.py` | Mide el tiempo de los tres núcleos del simulador (Python, Go y Rust) con una liga realista y comprueba que coinciden dentro del error Monte Carlo. |
| `medir_recencia.py` | Mide si dar más peso a los partidos recientes al entrenar mejora al modelo (MP-3), fuera de muestra y con la puerta común del plan. |
| `modelo_laplace.py` | línea de comandos del modelo propio: simular, importar, entrenar y evaluar (el modelo PRONOSTICA; no decide publicar). |
| `previa_piezas_por_liga.py` | rendimiento histórico de cada pieza (modelo Laplace, Dixon-Coles, mercado y «bot» aproximado) POR LIGA: la previa de los pesos del agente (MA-20). |
| `reajustar_modelos.py` | reajuste rápido de los Dixon-Coles con resultados en vivo. |
| `reclasificar_partidos_dia.py` | Pone el país y el identificador correcto a los partidos que se guardaron antes de que existiera `liga_pais` (ver `services/ligas_ident.py`). |
| `reparar_fechas_partidos_dia.py` | Diagnóstico y reparación SEGURA de claves `fecha` inválidas en `partidos_dia` (ej. |
| `reporte_laboratorio_vivo.py` | reporte honesto del laboratorio de pronósticos en vivo. |
| `verificar_calidad_datos_reales.py` | Verificación empírica contra el backend REAL corriendo, con partidos/ligas de HOY (datos reales, no mocks). |
| `verificar_datos_reales.py` | smoke test con datos REALES (sin mocks). |
| `verificar_fuentes.py` | Verifica proveedores deportivos configurados sin revelar credenciales. |

## `install/comun/`

| Módulo | Qué hace |
|---|---|
| `configurar.py` | detecta, prueba y configura las conexiones externas de Laplace (APIs de datos, IA y Telegram). |
| `configurar_env.py` | crea y completa el `.env` de Laplace durante la instalación (Windows y Linux). |
| `laplace.py` | control de Laplace (backend + agente), igual en Windows y Linux. |
