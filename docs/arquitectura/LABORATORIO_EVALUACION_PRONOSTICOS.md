# Laboratorio de evaluación de pronósticos

## Propósito
Compara pronósticos prepartido de Laplace, de IA y de fuentes autorizadas contra el resultado oficial. Es interno y no modifica el consenso público: produce evidencia reproducible para decidir qué variantes siguen en sombra, se corrigen o se proponen como candidatas.

## Separación de responsabilidades

```text
Fuentes de datos -> normalización -> motor estadístico -> consenso público
                                 \-> laboratorio de sombra -> métricas -> informe admin
IA / fuentes externas ----------------------^
```

`consenso.py` no consulta `pronosticos_experimentales`. Una fuente registrada en el laboratorio no cambia pesos, picks ni Top Picks. El módulo BSD tiene peso 0 en el consenso (no vota) y se mide aquí como `bsd_catboost`.

## Entidades
| Tabla | Responsabilidad |
|---|---|
| `experimentos_pronostico` | Catálogo y versión de cada variante; todas inician en `sombra`. |
| `pronosticos_experimentales` | Pronóstico inmutable por partido, variante y corte de datos. |
| `analisis_comparativo` / `analisis_modulos` | Historial operativo del motor y del consenso. |
| `resultados_partidos` | Resultado oficial que dispara la evaluación. |

Cada observación guarda partido, liga, equipos, fuente, variante, versión de modelo y de prompt, corte de datos, hash de entrada, probabilidades 1X2, marcador y resultado. Se rechaza un corte posterior al inicio del partido cuando este se conoce.

## Variantes (`EXPERIMENTOS_BASE`)
| Código | Origen |
|---|---|
| `python_baseline` | Motor estadístico Poisson + Dixon-Coles, sin IA (referencia principal) |
| `python_plus_ia` | Motor con contraste de IA |
| `ia_simple` | IA simple del laboratorio (rol `laboratorio`): solo equipos y competición; la genera Top Picks |
| `api_football_prediction` | Predicción externa de API-Football |
| `bsd_catboost` | Referencia BSD CatBoost |
| `human_reference` | Referencia humana supervisada |
| `dixon_coles_historico` | Dixon-Coles entrenado con el histórico, puro (sin cuotas) |
| `dc_mas_mercado_historico` | Dixon-Coles apilado con las cuotas del mercado |

Una fuente web solo entra mediante un adaptador aprobado que documente fuente, términos, hora de captura y carga original. El experimento debe existir antes en el catálogo: el endpoint no acepta códigos arbitrarios.

## Métricas
Cobertura y cantidad evaluada; acierto del pick 1X2; Brier, log loss y RPS (menor es mejor); segmentación por fuente, variante y liga. Mínimos: 50 partidos para exploración y 200 para proponer una promoción; ninguno autoriza un cambio automático.

## Goles y prórroga
El motor produce marcador más probable, goles esperados, rangos probables de goles (local, visitante y total) y probabilidad de empate a los 90 minutos. La prórroga queda sin estimar hasta tener formato eliminatorio y estado de la serie fiables.

## Contratos
- `GET /api/v1/admin/laboratorio-pronosticos`: informe de solo lectura.
- `POST /api/v1/admin/laboratorio-pronosticos`: ingreso de un comparador autorizado; valida probabilidades completas y corte prepartido.
- `GET /api/v1/admin/laboratorio-pronosticos/partidos?fecha=` y `POST .../predicciones-humanas`: referencias humanas.
- `services.resultados._guardar_resultado`: reconcilia el resultado y calcula las métricas.

Los adaptadores viven en el backend y leen credenciales de `.env`; ningún endpoint acepta secretos.

## Promoción controlada
Un candidato necesita periodo fuera de muestra, cobertura suficiente, mejora consistente de calibración y revisión administrativa, y crea una versión de configuración nueva conservando el baseline. Nunca hay ajuste automático de pesos.
