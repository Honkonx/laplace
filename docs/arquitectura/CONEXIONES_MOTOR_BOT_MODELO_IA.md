# Conexiones entre motor, bot, agente, modelo Laplace e IA

Cuatro piezas que **se usan entre sí y no dependen una de otra**. Cada conexión tiene un plazo propio y una salida de emergencia; ninguna pieza es indispensable para que las demás respondan.

## Mapa
```
                         ┌──────────────── EN PARALELO ────────────────┐
 consulta del usuario ──►│ motor/bot (consenso, fuentes, cuotas)        │──┐
 (Telegram, web, app,    │ modelo Laplace (/api/v1/ml/predict, 8 s)     │──┤──► EN SERIE ──► IA que explica/contrasta ──► mensaje
  agente)                └──────────────────────────────────────────────┘  │      (recibe lo que haya; si falta algo, lo dice)
                                                                           └──► texto determinista si la IA no responde
```
- **Paralelo:** motor/bot y modelo no comparten datos ni se esperan (`agent_tools.sports.predict` los lanza con `asyncio.gather`; el modelo con plazo de 8 s). Dentro del motor, el modelo se lee del puntero `vigente.json`, no de la base.
- **Serie:** la IA va después porque consume cifras ya calculadas; el prompt del análisis NO recibe el pronóstico del modelo (contraste independiente). La redacción del agente solo acepta cifras presentes en el JSON verificado.

## El orquestador `pronostico_conjunto`
`backend/api/services/pronostico_conjunto.py` es el único lugar donde se decide paralelo o serie: `ejecutar(paralelas, plazos, serie)` corre las piezas independientes a la vez, cada una con su plazo, y después las de la serie, que reciben
el `Conjunto` parcial para usar lo que haya o saltarse lo que falte. No importa el bot, el modelo ni la IA: solo las ejecuta y las mide (`ok`, `segundos`, `agotada`, `error`). Una pieza caída es un resultado, no una excepción hacia las demás.
Lo usa `sports.predict` del agente (bot ‖ modelo, plazos 60 s y 8 s) y deja `piezas` en la respuesta para auditoría. En el bot, el modelo es una pieza aislada dentro del motor (`motor._pronostico_modelo_laplace`, con su `try/except`), porque ahí el cálculo es local y no hay
espera de red que paralelizar.

## Qué pasa si cae cada pieza
| Cae… | Efecto | Prueba |
|---|---|---|
| el modelo Laplace | el bot y el agente responden igual; el bloque `modelo_laplace` queda `null` | `test_ml_conexiones.py` |
| el bot / el motor | el agente responde con la lectura del modelo y lo dice (`bot_disponible: false`) | `test_ml_conexiones.py` |
| la IA | texto determinista del agente y del bot, mismas cifras | pruebas existentes del agente |
| la base de datos | el modelo sirve por el puntero en disco; el motor sigue | `test_ml_laplace.py` |
| el modelo **y** el bot | el agente informa el error; no inventa un resultado | `test_ml_conexiones.py` |

## Contratos
Modelo: `POST /api/v1/ml/predict` (`ml-1`), `GET /api/v1/ml/tools`, `GET /api/v1/ml/health`. Bot: `POST /api/v1/prediccion-web`. Agente: herramientas `sports.*`, `knowledge.*`, `modelo.pronosticar`.
Ver `docs/backend/MODELO_LAPLACE.md`.

## Qué viaja del modelo hacia el resto (2026-11-11)
`resumen_para_consumidores` entrega el 1X2 siempre y, por separado, `goles_esperados`, `btts_si`, `mas_2_5` y `marcador_mas_probable` **solo si el modelo los validó fuera de muestra** (si no, `null` y las pantallas no los nombran). `p1x2_con_mercado` llega solo cuando el partido trae cuotas y el apilador le ganó al mercado.
El motor del bot pasa las cuotas del partido al modelo (`odds_local`, `odds_empate`, `odds_visit`) cuando `odds_disponibles` es verdadero. El canal HTTP público acepta `cuotas` opcionales y pasa su salida por `servicio.publico`.
