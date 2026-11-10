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
| `auditar_integridad.py` | cuenta, en SOLO LECTURA, los registros huérfanos de las relaciones lógicas de la base de datos (no hay claves foráneas declaradas). |
| `backfill_module_results.py` | Completa `analisis_modulos.pick_correcto` desde resultados ya verificados. |
| `backfill_resultados_laboratorio.py` | Copia a `resultados_partidos` los partidos terminados de `partidos_dia` que faltan, y califica con ellos lo que estaba pendiente (comparativos, módulos, predicciones… |
| `create_admin.py` | Crea o actualiza un administrador global local. |
| `diagnostico_cobertura_vivo.py` | ¿qué responde HOY el bot a los partidos reales de una fecha? |
| `doctor.py` | diagnóstico de una instalación de Laplace («laplace doctor»). |
| `evaluar_consenso_historico.py` | mide el CONSENSO REAL completo contra el mercado. |
| `evaluar_equipo_nuevo.py` | ¿qué probabilidad dar cuando un equipo no está en el modelo? |
| `evaluar_modelo_historico.py` | evaluación walk-forward con datos históricos reales. |
| `exportar_resultados_vivos.py` | capa de resultados en vivo para reajustar los modelos. |
| `generar_conocimiento_equipos.py` | perfiles de equipo calculados del histórico real. |
| `generar_conocimiento_ligas.py` | base de conocimiento por liga, calculada. |
| `generar_referencia_docs.py` | genera las referencias técnicas de `docs/backend/referencia/` a partir del CÓDIGO (no de otros documentos). |
| `laplace_auditor.py` | Auditoría real de winrate/calibración, contra la BD real. |
| `medir_cobertura_historico.py` | mide qué fracción de los partidos reales resuelve el módulo `historico`. |
| `medir_colector.py` | cobertura de la capa en vivo, por liga con modelo (SOLO lectura). |
| `reajustar_modelos.py` | reajuste rápido de los Dixon-Coles con resultados en vivo. |
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
