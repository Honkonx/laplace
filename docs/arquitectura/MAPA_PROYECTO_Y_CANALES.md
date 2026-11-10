# Mapa de Laplace

## Canales

```text
Telegram ──┐
Web + PWA ─┼──> FastAPI bot deportivo (9001) ──> SQLite (por defecto) o PostgreSQL
Android ──┘              │
                          └──> Agente (9100, proceso independiente)
```

- **Telegram:** bot bajo demanda y canal de Top Picks.
- **Web (`frontend/`) y PWA (`pwa/`):** SPA React + Vite que usan JWT. La PWA es la versión instalable con service worker.
- **Android:** cliente nativo Kotlin + Compose.
- **Bot deportivo:** pronóstico, partidos, resultados, laboratorio y planificador; funciona sin el agente.
- **Agente:** chat, memoria, tareas, subagentes y puente HTTP al bot; funciona con reglas y memoria si el bot no está.

## Carpetas
| Ruta | Responsabilidad |
|---|---|
| `backend/api/` | FastAPI: motor, API, Telegram, planificador y base de datos |
| `backend/agents/` | Autoevaluación y control de calidad del sistema (`laplace_agents`) |
| `backend/knowledge/` | Conocimiento declarativo del agente y del dominio deportivo |
| `backend/scripts/` | Scripts de operación, evaluación y mantenimiento |
| `backend/data/` | Datos de entrenamiento y calibración (se generan con las fuentes de cada quien; no vienen en el repo público) |
| `frontend/`, `pwa/` | Web y PWA |
| `app-android/` | App Android |
| `install/` | Instalador portable y asistente de claves |
| `docs/` | Esta documentación |

El producto se ofrece como servicio central: Telegram, web, PWA y Android consumen el mismo backend.
