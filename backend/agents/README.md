# Laplace-Agents

El agente de Laplace — no es el bot, es una extensión que lo mejora. El bot (Telegram, app,
web) nunca depende de que esto esté corriendo; si Laplace-Agents se cae, el bot sigue
funcionando exactamente igual. Misma relación que ya tiene el bot con la IA: mejora el
resultado cuando está disponible, nunca es un requisito para que el sistema funcione.

Vive en su propia carpeta en la raíz del repo (no dentro de `backend/`) a propósito — separación
física, no solo de código, para que la independencia del bot sea real y no solo una convención
que alguien puede romper sin darse cuenta.

## Por qué existe

Hallazgo real 2026-09-09: el verificador de resultados del backend (`resultados_scheduler.py`)
solo VERIFICA partidos que ya tienen un pronóstico guardado — y esa tabla solo se llenaba
cuando un usuario real pedía un análisis. Sin usuarios preguntando por un partido, ese partido
nunca se analizaba, nunca se guardaba, y nunca se podía verificar. Laplace-Agents existe para
que el sistema se auto-evalúe, sin depender del tráfico real de usuarios.

## Qué hace hoy (`laplace_agents/core.py`)

Corre una vez al día (8am hora Chile, antes del cron de Top Picks), independiente de cualquier
usuario:

1. Pide los fixtures reales del día (reusa la caché del backend).
2. Filtra a las ligas que el sistema conoce de verdad.
3. Analiza cada partido nuevo con el MISMO motor real que usa un request de usuario real (sin
   IA — esto es para calibración y para pre-calentar la caché, no para generar contenido
   editorial) y lo guarda en la base de datos del backend, en el mismo lugar que ya lee el
   verificador de resultados.

Efecto secundario real: un usuario que después pregunte por ese mismo partido lo encuentra ya
resuelto — carga más rápido.

**Cómo se conecta con el backend**: `laplace_agents` importa funciones reales de
`backend.api.services`/`backend.api.db` (el motor de análisis, el acceso a datos) — la
dependencia va en un solo sentido, `laplace-agents → backend`, nunca al revés. El backend
(`backend/api/main.py`, `backend/api/routers/scheduler.py`) decide CUÁNDO correr el ciclo (cron
diario + endpoint manual `POST /api/v1/scheduler/laplace-agents`), pero la lógica de qué hacer
vive acá.

## Roadmap — lo que pidió el usuario, no todo construido todavía

Ítems marcados construidos (✅) están en este repo hoy, verificados con tests reales. El resto
es la visión a la que se apunta, construida incrementalmente.

- ✅ **Auto-evaluación diaria** sin depender de usuarios (`core.py`).
- ✅ **Causa raíz de la uniformidad de predicciones arreglada**: `team_stats_fetch.py`
  conectado — antes, sin H2H real entre los 2 equipos específicos, el sistema caía directo a un
  promedio genérico de liga (mismo resultado para cualquier partido de la misma liga). Ahora
  prueba primero el promedio real de temporada de cada equipo. Medido: 92.6% → 56.7% de picks
  "Empate" en un día real.
- ✅ **Puntuar ligas/partidos por qué tan "prometedores" son** (`seleccion.py`) — por RIQUEZA DE
  DATOS real (cobertura de tabla/odds/H2H/team_stats), NO por precisión histórica — con el
  volumen real de partidos verificados todavía muy bajo, un score de precisión sería ruido, no
  señal (mismo principio que la calibración del motor completo).
- ✅ **Priorizar los partidos con más riqueza de datos** dentro del cap diario (`seleccion.py`)
  — hoy es sobre todo orden de prioridad, no exclusión (la cobertura real rara vez llega al
  cap).
- ✅ **Detector de uniformidad** (`consistencia.py`) — cada corrida reporta la distribución real
  de picks y marca una alerta si demasiados salen iguales. Verificado con datos reales: detectó
  92.6% "Empate" en un batch real sin intervención manual, replicando el hallazgo original.
- ✅ **Analizar HOY y MAÑANA** en la misma corrida (antes solo hoy).
- 🔜 **Auditoría de riqueza de datos por partido expuesta de forma persistente** — `fuente_goles`
  ya existe y se usa para el detector de uniformidad, pero todavía no se persiste columna a
  columna por partido para consulta posterior (hoy se recalcula en cada corrida).
- ✅ **Memoria SQL propia del agente** (`laplace_agents/memoria.py`, modelo
  `LaplaceAgentMemoria` en `backend/api/models/laplace_agents.py`) — antes el agente solo
  escribía en tablas compartidas del resto del sistema (`analisis_comparativo`, vía
  `USUARIO_SISTEMA`); ahora tiene su propia tabla de eventos (`tipo_evento` libre:
  `ciclo_diario`/`deriva_detectada`, `resumen` como JSON). 🔜 **migración Alembic real
  pendiente** — la tabla existe hoy solo vía `Base.metadata.create_all()` en los tests; falta
  `alembic revision --autogenerate` (deliberadamente fuera de esta ronda, ver commit/PR
  correspondiente) antes de que exista en `backend/db/bot_deportivo.db`.
- ✅ **Detector de deriva entre corridas** (`laplace_agents/deriva.py`) — compara la
  distribución de picks de la corrida actual contra la última registrada en la memoria del
  agente (no solo el nivel absoluto dentro de una corrida, eso ya lo hace `consistencia.py`) y
  marca una alerta simple y honesta (delta de proporción ≥ 25 puntos, con muestra mínima de 5
  partidos en ambos lados) — mismo criterio no-estadístico-sofisticado que `consistencia.py`,
  documentado y no calibrado con datos reales todavía. Cada corrida queda escrita en la memoria
  nueva (`tipo_evento="ciclo_diario"`); una alerta real agrega además
  `tipo_evento="deriva_detectada"`.
- ✅ (primer paso) **Interacción real con usuarios** — comando `/encuesta` en el bot (botones
  Local/Empate/Visitante), tabla `predicciones_usuario` con voto real por usuario, agregación
  real por partido. 🔜 el "por qué" en texto libre (falta un flujo de conversación en el bot)
  sigue pendiente.
- ✅ **`/encuesta` conectado al ciclo del agente** (`laplace_agents/votos.py`,
  `comparar_votos_vs_motor`) — el ciclo diario ahora lee los votos agregados de partidos YA
  resueltos (`predicciones_usuario_repo.leer_agregado`) y expone, en el resumen de cada corrida
  (`comparacion_usuarios_vs_motor`), qué tan seguido acertó el consenso mayoritario de usuarios
  vs. el `pick_final` del motor. **Esto NO es "la IA aprende de los votos"** — con el volumen
  real de hoy eso sería sobre-prometer (ver
  `INVESTIGACION_ARQUITECTURA_AGENTES_2026-09.md`); es solo exponer la
  comparación, ninguno de los dos valores alimenta ni ajusta al otro. "Auto-alimentarse y
  aprender" de verdad sigue siendo una decisión de diseño más grande, deliberadamente fuera de
  esta ronda.
- 🔜 **Supervisión/control del bot** — monitorear que el bot/scheduler sigan vivos, verificar
  resultados, y eventualmente poder actuar sobre el bot (no solo alimentarlo) — construido
  incrementalmente sobre la base de observabilidad que ya existe (`scheduler_runs`,
  `GET /api/v1/scheduler/status`).
- 🔜 **Stack polyglot** (Python + JavaScript/TypeScript + IA) — hoy 100% Python (consistente con
  el resto del backend, evita duplicar infraestructura antes de tener una razón concreta para
  JS/TS). Si aparece una pieza concreta que se beneficie de JS/TS (ej. un componente de
  automatización de navegador, una integración con una herramienta del ecosistema Node), se
  agrega ahí, no como reescritura completa.

## Cómo correr los tests

```
cd "bot deportivo"
.venv_backend/Scripts/python.exe -m pytest laplace-agents/tests -q
```

Independiente de la suite del backend (`pytest backend/tests/ -q`) — mismo patrón que
`frontend/`/`pwa/` tienen sus propios test runners, cada proyecto en la raíz es responsable de
sus propios tests.
