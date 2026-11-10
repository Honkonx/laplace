# Referencia de trabajos programados

> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).

El planificador (APScheduler) corre dentro del backend, en la zona horaria de Chile (`America/Santiago`). Cada trabajo también se puede lanzar a mano por `POST /api/v1/scheduler/...` (ver la referencia de la API).

| Id | Cuándo | Función | Qué hace |
|---|---|---|---|
| `fuentes_deportivas_health` | hour=7, minute=30 | `_job_verificar_fuentes` | Registra la salud de fuentes antes de los ciclos que consumen datos. |
| `laplace_agents_autoeval` | hour=8, minute=0 | `_job_laplace_agents` | Auto-evaluación diaria del motor: el sistema se analiza a sí mismo sin depender del tráfico de usuarios. |
| `wfd_top_picks` | hour=9, minute=0 | `_job_top_picks` | Calcula y publica el informe diario de Top Picks en el canal. |
| `wfe_resultados_2h` | hour=*/2, minute=0 | `_job_resultados` | Verifica los resultados finales y califica los pronósticos pendientes y las observaciones del laboratorio. |
| `wfe_resultados_7am` | hour=7, minute=0 | `_job_resultados` | Verifica los resultados finales y califica los pronósticos pendientes y las observaciones del laboratorio. |
| `refresco_cuotas` | hour=7,15, minute=15 | `_job_refresco_cuotas` | Refresca las cuotas (The Odds API) y las tablas de posiciones (football-data) de los partidos de hoy y mañana, dentro de un tope diario. |
| `colector_resultados` | hour=2,12, minute=30 | `_job_colectar_resultados` | Guarda los marcadores finales recientes y los partidos programados para que la capa en vivo de los modelos crezca sola. |
| `reajuste_modelos` | day_of_week=sun, hour=3, minute=30 | `_job_reajustar_modelos` | Reajusta cada semana los modelos Dixon-Coles con los resultados verificados y reemplaza el artefacto solo si la validación pasa. |
| `mantenimiento_jobs_colgados` | minute=*/15 | `_job_reset_jobs_colgados` | Marca como error los análisis que quedaron en «procesando» porque el proceso murió a mitad. |
| `purga_datos_viejos` | hour=4, minute=0 | `_job_purga_datos_viejos` | Purga `partidos_dia` de más de 90 días y la caché de estadísticas vencida. |
