# Laboratorio de pronósticos: operación

Activo en modo sombra: no modifica el consenso publicado. Diseño y métricas: [`../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md`](../arquitectura/LABORATORIO_EVALUACION_PRONOSTICOS.md).

## Flujo automático
1. Top Picks recupera los partidos de las ligas priorizadas y conserva la respuesta íntegra de API-Football cuando hay cobertura de predicciones.
2. El motor registra `python_baseline` solo si Poisson tiene pick y probabilidades 1X2 completas; los promedios genéricos de liga no generan fila.
3. Cuando existe el análisis combinado, registra `python_plus_ia` con el mismo corte temporal, sin convertirlo en señal de consenso.
4. Para una muestra diaria acotada (`LAB_IA_SIMPLE_MAX_PARTIDOS`), `ia_simple` consulta un proveedor con solo equipos y competición. La respuesta debe ser JSON válido con probabilidades normalizadas; se guardan proveedor, modelo, versión de prompt y texto crudo.
5. Al llegar un marcador FT/AET/PEN, el servicio de resultados evalúa cada variante; el planificador además reconcilia filas que hayan quedado pendientes por un reinicio.

## Calidad y publicación
- Top Picks publica solo si hay **al menos dos canales de datos independientes** (mercado, histórico, xG…) **o un ancla** (cuotas reales, o histórico válido con ambos equipos) — `services/calidad_datos.py`. Los valores por defecto no cuentan.
- IA simple, API-Football, BSD y referencias humanas permanecen en sombra.
- Promoción: al menos 50 resultados evaluados para explorar y 200 más validación fuera de muestra; se comparan acierto, Brier, log loss y RPS por variante, fuente y liga.

## Operación
- Informe: `GET /api/v1/admin/laboratorio-pronosticos`.
- Referencias humanas: `POST /api/v1/admin/laboratorio-pronosticos/predicciones-humanas`.
- Detener el comparador de IA simple: `LAB_IA_SIMPLE_ACTIVA=false` en `.env`.
- Ninguna variante se usa como consenso sin revisión explícita y evidencia suficiente.
