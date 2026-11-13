# Motor de pronóstico

## Cómo se calcula
1. **Modelo histórico (Dixon-Coles)** por liga, entrenado con resultados reales y reajustado cada semana con los resultados que el propio sistema recoge (`ml/`; los artefactos se generan en `backend/api/ml/artefactos/`). Si falta uno de los dos equipos, la liga no valida o el modelo está muy desactualizado, no se usa o baja la confianza.
2. **Cuotas del mercado sin margen** (The Odds API y predicciones externas): un solo canal de mercado, aunque lleguen por dos proveedores.
3. **Consenso ponderado** (`services/consenso.py`): las cuotas y el histórico son las dos **anclas** que la evaluación walk-forward midió con información real; forma reciente, tabla y H2H pesan casi nada y un peso 0 equivale a módulo ausente.
4. **Puerta de calidad de datos** (`services/calidad_datos.py`): un pronóstico solo se publica con al menos 2 canales independientes de datos reales.

5. **Modelo propio de Laplace** (`ml/laplace/`): ratings Elo y tasas de gol con memoria exponencial alimentan una regresión logística jerárquica por liga. Pronostica 1X2, goles esperados, marcadores, ambos marcan y más o menos goles (solo se muestran los mercados que superaron a la tasa base fuera de muestra) y se combina con las cuotas sin margen cuando existen. Es una de las piezas del consenso y también se puede usar sola.
6. **Simulador de temporadas**: Monte Carlo de campeón, copa y descenso con incertidumbre de la fuerza de cada equipo. El cálculo caliente está en Rust (con respaldo en Go y en Python): se elige el primero que esté compilado y la respuesta dice cuál corrió. Se compila con `backend/scripts/construir_rust.py` y `construir_go.py`; sin ellos, todo sigue funcionando en Python.

La IA no interviene en las probabilidades: explica el resultado y contrasta, y sus cifras se depuran para que no cite porcentajes ajenos al motor.

## Usar el modelo sin Telegram
El modelo se ejecuta como un sistema, no solo por el bot:
- **HTTP**: `POST /api/v1/ml/predict` con `local` y `visitante` (obligatorios) y `liga`, `pais`, `liga_id` y `cuotas` (opcionales; el país desambigua ligas homónimas como la Serie B de Brasil o de Italia). Devuelve probabilidades que suman 1, `fuente`, `degradado` y el motivo cuando no hay pronóstico.
- **Línea de comandos**: `python backend/scripts/modelo_laplace.py predecir --entrada partidos.csv --salida pronosticos.csv` pronostica un lote (CSV o JSON) sin servidor y sin escribir en la base.
- **Biblioteca**: `backend.api.ml.laplace.servicio.pronosticar_partido`.

## Qué no incluye este repositorio
**Ni datos históricos ni modelos entrenados.** Salen de fuentes con licencias propias (ver [seguridad y datos](seguridad-y-datos.md)) y cada quien debe generarlos con las suyas:
- **Sin modelo histórico** el motor usa las cuotas del mercado (nivel N3); sin cuotas tampoco, el partido queda en N0 («sin pronóstico propio») con sus motivos. `laplace doctor` lo avisa.
- **Para entrenar tu propio modelo** necesitas resultados históricos y de cuotas con el formato que lee `backend/api/ml/datos.py` (carpeta `backend/data/datos/football-data/`), y correr `backend/scripts/reajustar_modelos.py --todas --aplicar` (con `-ConML`). El colector de resultados en vivo (`exportar_resultados_vivos.py`) construye la capa en vivo con **tus** claves de datos.
- Los scripts que descargan datos de terceros tampoco se publican: revisa antes los términos de cada fuente.

## Nivel de evidencia
| Nivel | Significa |
|---|---|
| N4 | histórico y cuotas, y las dos anclas coinciden en el partido |
| N3 | solo cuotas del mercado |
| N2 | solo histórico de la liga, con ambos equipos conocidos |
| N1 | histórico con un equipo sin historial (confianza máxima BAJA) |
| N0 | sin pronóstico propio: solo la frecuencia de la liga como referencia (y se explica por qué) |

## Confianza
ALTA si la probabilidad ponderada del pick es ≥ 0,60, MEDIA entre 0,50 y 0,60 y BAJA por debajo; sin ancla, como máximo MEDIA. Los umbrales salieron de frecuencias reales de acierto, no de una escala a ojo.

## Cómo se mide
- `backend/scripts/evaluar_modelo_historico.py` y `evaluar_consenso_historico.py`: evaluación walk-forward (cada partido se predice solo con lo anterior a su fecha) contra la **tasa base de la liga** y las **cuotas sin margen**, con RPS y log-loss.
- Los modelos nuevos corren primero en modo sombra (`laboratorio_pronosticos`) y no entran al consenso hasta tener evidencia en partidos reales.
- El sistema calcula la precisión real por usuario y por confianza («mis picks»); si el acierto real es malo, debe poder mostrarse.

Las evaluaciones necesitan numpy, scipy y scikit-learn (`backend/requirements-ml.txt`, opción `-ConML` del instalador). **Esto no es una promesa de rentabilidad:** un modelo que no mejora a las cuotas no aporta información nueva, y el sistema lo dice.
