# Simulador de liga: público (con plan) e interno (de desarrollo)

Dos cosas distintas con un solo motor (`ml/laplace/liga.py`, núcleo en Go con respaldo en Python).

| | Público | Interno |
|---|---|---|
| Quién | Planes **pro** y **max** y administradores (web, PWA, Telegram `/simular`, agente) | Quien desarrolla el proyecto |
| Para qué | Estimar campeón, copa y descenso de una liga con lo que ya pasó | Probar el modelo, el bot y el agente; backtests; escenarios sintéticos (`ml-2` con clave interna, `backtest_temporadas.py`) |
| Límites | 20.000 simulaciones como máximo, 10 por minuto por IP, 30 s de plazo y como máximo 2 simulaciones a la vez (la tercera recibe 503; el cupo se libera cuando el hilo termina, no cuando la petición se rinde) | Presupuestos mayores y datos de prueba |
| Se publica | Sí, con aviso «estimación, no certeza» | No: son mediciones |

## Cómo calcula el público (`services/simulador_propio.py`)
1. Junta TODO el histórico más los resultados recientes: maestro, capa `actual` (football-data.co.uk, se actualiza cada día a las 06:15) y capa del bot, sin duplicar (el maestro manda, luego `actual`, luego el bot).
2. Construye la tabla de la temporada en curso y deduce lo que falta: en una liga de todos contra todos a ida y vuelta, cada par local/visitante que aún no se jugó. Si faltan equipos, hay partidos repetidos o no hay una temporada anterior completa, **no simula** y dice por qué.
3. Estima los goles esperados de cada partido con el estado del modelo Laplace (Elo + tasas de gol, partido a partido) y simula el resto con incertidumbre de la fuerza de cada equipo (sigma 0,12; el backtest de 57 temporadas dio una cobertura de 0,90).
4. Devuelve por equipo: probabilidad de campeón, de copa (top 4), de descenso (últimos 3), posición promedio y rango de puntos finales, con `datos_hasta`, `motor` y `validado`.

## Acceso (`db/usuarios_repo.py::acceso_simulador`)
Administrador (lista del `.env` o rol) o plan pro/max vigente y activo. El plan se lee de la base en cada llamada: el claim de un token viejo no concede nada. Sin sesión: 401; sin plan: 403 con el motivo. `GET /api/v1/simulador` (lista de ligas y por qué alguna no está) es público; `GET /api/v1/simulador/{liga}` exige sesión.

## Ligas (hoy)
`premier`, `laliga`, `seriea`, `bundesliga`, `ligue1`, `eredivisie`, `primeirliga`, `superlig`, `championship`, `pro_league`, `scottish`, `brasileirao`. `scottish` no se simula todavía (sin una temporada anterior completa en los datos). Las ligas con fase final o dos fases (Argentina, México) no son de todos contra todos y quedan fuera.

## Mantener los datos al día
`python el actualizador de la capa «actual» (no publicado) (o el trabajo diario `RESULTADOS_ACTUALES_AUTOMATICO`). Escribe en `backend/data/datos/actual/`, que no se publica.
