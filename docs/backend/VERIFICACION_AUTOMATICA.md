# Verificación automática de pronósticos

Describe el código de hoy. Cada pronóstico emitido se verifica solo: el sistema anota la hora del partido, vuelve a buscar el resultado cuando termina, lo guarda con los goles de cada equipo, califica todo lo enlazado y entrega un informe semanal.

## Flujo
1. **Se emite un pronóstico** (bot, agente, laboratorio, modelo o autopiloto). `services/verificacion.encolar_seguro` lo pone en la cola `verificaciones` (una fila por partido) con el **inicio en UTC**. Una falla de la cola nunca rompe el pronóstico.
2. **Primer intento a inicio + 140 min** (`core/horario.DURACION_PARTIDO_MIN`). Sin hora conocida: la mañana siguiente al día del partido.
3. **El trabajo `verificar_partidos`** (`main.py`, cada 10 min y 45 s después de arrancar) llama a `verificacion.procesar_vencidas`:
   - fuentes en orden (`FuenteReal`): base local (`resultados_partidos`, `partidos_dia`) → LiveScore por fecha (una petición cubre todos los partidos de un día; prueba la fecha y la siguiente porque LiveScore fecha en UTC+7; tope de 3 fechas por corrida y el presupuesto diario del colector) → BSD (sin cuota) → api-football (solo ids numéricos, tope de 5 por corrida; el plan gratuito exige `id` y no `ids`, y no da la temporada actual);
   - `final` → `resultados._guardar_resultado` escribe `resultados_partidos` y califica comparativos, predicciones, variantes del agente, `partidos_dia` y las observaciones del laboratorio (con goles reales de cada equipo);
   - `en_juego` / sin dato → reintento a los 20, 20, 30, 60, 120 y 240 min;
   - `aplazado` → cada día; `sin_resultado` → cancelado o 3 días sin dato (se informa, no se inventa).
4. **Planificador robusto:** `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`; lo vencido mientras el backend estaba apagado se recupera en la primera corrida.
5. **Rescate:** `sembrar_pendientes` pone en la cola lo anterior que quedó sin resultado.
6. **Estado y aviso:** `GET /health` → `verificacion` (conteo por estado y `atrasadas`: vencidas hace más de 90 min). Con 5 o más atrasadas, el administrador recibe un aviso por Telegram una vez al día.

Corrida real (2026-11-14, copia de la base, fuentes reales): 21 de 29 pronósticos cerrados (8 por LiveScore, 9 por BSD, 3 por api-football, 1 de la base) y 4 `sin_resultado` en ligas menores que ninguna fuente cubre.

## Horas (`core/horario.py`)
- LiveScore entrega `Esd` en **UTC+7** (medido: los horarios de la Serie A 00:30, 02:45 y 21:00 son 17:30, 19:45 y 14:00 UTC). El colector y el gateway lo convierten a UTC y a la hora de Chile.
- Chile usa su horario de verano (`zoneinfo`): en noviembre es UTC−3. Antes había un −4 fijo.

## Cuotas
`odds_fetch.obtener_odds_partido` agrega `odds_consultadas_en` y `odds_min_al_inicio`: cuándo se pidió la cuota y cuánto faltaba para el inicio. La cuota es intermedia (caché de 2 h; 30 min si faltan menos de 2 h); no hay marca de apertura ni de cierre de la casa.

## Informe semanal (`services/informe_semanal.py`)
- Domingo 21:30 (Chile): guarda `informe_semanal:<fecha>` en la caché y lo envía al administrador; `GET /api/v1/ml/informe-semanal?dias=7` (administradores).
- Contiene: embudo de verificación, 1X2 por variante (acierto, log loss, RPS, Brier) frente a la tasa base con IC95, goles de cada equipo (error absoluto y Poisson frente a la media de la ventana, marcador probable acertado) y detalle por liga.
- Una semana confirma que el circuito funciona; no alcanza para decidir si se le gana al mercado.

## Autopiloto
`laboratorio_modelo_laplace.registrar_proximos` (trabajo `modelo_laplace_sombra`, 07:45 y 16:45) registra, sin intervención, el pronóstico del modelo y de Dixon-Coles para los partidos de `partidos_dia` de las próximas 48 h de las ligas con cobertura. Tope de 3.000 por corrida; los ya registrados no gastan cálculo.

## Goles de cada equipo
El contrato del modelo (`ml/laplace/servicio.resumen_para_consumidores`) incluye `goles_por_equipo`: esperados, probabilidad de 0, 1, 2 y 3 o más goles y de marcar de cada equipo, y la tasa de acierto histórica del marcador más probable (12,4 %). Sale solo si los goles por equipo superaron a la media de la liga en la reserva (`goles.calibrar` → `util["equipo"]`) o, en artefactos anteriores, si el total estaba validado. Medición: `backend/scripts/medir_goles_por_equipo.py`.

## Pruebas
`backend/tests/test_verificacion.py`, `test_informe_semanal.py` y `test_goles_por_equipo.py`: base con las migraciones reales, reloj simulado y solo la fuente externa falsa.
