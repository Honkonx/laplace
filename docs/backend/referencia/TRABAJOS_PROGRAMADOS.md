# Referencia de trabajos programados

> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).

El planificador (APScheduler) corre dentro del backend, en la zona horaria de Chile (`America/Santiago`). Cada trabajo también se puede lanzar a mano por `POST /api/v1/scheduler/...` (ver la referencia de la API).

| Id | Cuándo | Función | Qué hace |
|---|---|---|---|
| `fuentes_deportivas_health` | hour=7, minute=30 | `_job_verificar_fuentes` | Registra la salud de fuentes antes de los ciclos que consumen datos. |
| `resultados_actuales` | hour=6, minute=15 | `_job_actualizar_resultados_actuales` | 06:15 (Chile): resultados de la temporada en curso desde football-data.co.uk → capa `actual` del conjunto de datos; el simulador y el modelo usan datos de hoy, no de… |
| `estado_vivo_modelo` | hour=6,13, minute=40 | `_job_estado_vivo` | 06:40 y 13:40 (Chile): reconstruye en la base la memoria del modelo (estado por equipo de cada liga) con maestro + capa en vivo + capa actual, después de que entren… |
| `avisos_favoritos` | hour=8, minute=30 | `_job_avisos_favoritos` | Aviso de las 08:30 (Chile) con los partidos de hoy de los favoritos, solo a quien lo activó; apagado por defecto. |
| `avisos_resultados` | hour=11,15,19,21, minute=10 | `_job_avisos_resultados` | Final de los partidos ya avisados (MS-4): varias veces al día, solo en horario activo y solo si hay un final nuevo; apagado por defecto igual que los avisos. |
| `laplace_agents_autoeval` | hour=8, minute=0 | `_job_laplace_agents` | Auto-evaluación diaria del motor: el sistema se analiza a sí mismo sin depender del tráfico de usuarios. |
| `modelo_laplace_sombra` | hour=7,16, minute=45 | `_job_modelo_laplace` | Evalúa cada día el modelo Laplace (sombra y activo) contra los resultados verificados y avisa al reunir evidencia. |
| `modelo_laplace_reentreno` | day_of_week=sun, hour=4, minute=30 | `_job_reentreno_laplace` | Reentrena cada semana el modelo Laplace en un subproceso y lo promueve solo si pasa las guardas. |
| `wfd_top_picks` | hour=9, minute=0 | `_job_top_picks` | Calcula y publica el informe diario de Top Picks en el canal. |
| `wfe_resultados_2h` | hour=*/2, minute=0 | `_job_resultados` | Verifica los resultados finales y califica los pronósticos pendientes y las observaciones del laboratorio. |
| `wfe_resultados_7am` | hour=7, minute=0 | `_job_resultados` | Verifica los resultados finales y califica los pronósticos pendientes y las observaciones del laboratorio. |
| `refresco_cuotas` | hour=7,15, minute=15 | `_job_refresco_cuotas` | Refresca las cuotas (The Odds API) y las tablas de posiciones (football-data) de los partidos de hoy y mañana, dentro de un tope diario. |
| `colector_resultados` | hour=2,12, minute=30 | `_job_colectar_resultados` | Guarda los marcadores finales recientes y los partidos programados para que la capa en vivo de los modelos crezca sola. |
| `reajuste_modelos` | day_of_week=sun, hour=3, minute=30 | `_job_reajustar_modelos` | Reajusta cada semana los modelos Dixon-Coles con los resultados verificados y reemplaza el artefacto solo si la validación pasa. |
| `mantenimiento_jobs_colgados` | minute=*/15 | `_job_reset_jobs_colgados` | Marca como error los análisis que quedaron en «procesando» porque el proceso murió a mitad. |
| `purga_datos_viejos` | hour=4, minute=0 | `_job_purga_datos_viejos` | Purga `partidos_dia` de más de 90 días y la caché de estadísticas vencida. |
