# Visión general de la arquitectura

Cómo encajan las piezas: procesos, carpetas, datos y autenticación. El estado actual del pronóstico y del agente está en [`ESTADO_ACTUAL_BOT_AGENTE_Y_EVALUACION.md`](ESTADO_ACTUAL_BOT_AGENTE_Y_EVALUACION.md); el contrato con la app, en [`APP_BACKEND_BRIDGE.md`](APP_BACKEND_BRIDGE.md).

## Procesos y puertos
| Proceso | Puerto | Contiene |
|---|---|---|
| **Backend** (`backend.api.main:app`) | 9001 | API REST `/api/v1/*`, bot de Telegram (polling), planificador (APScheduler) y la web compilada (`frontend/dist`, mismo origen) |
| **Agente** (`backend.api.agent_main:app`) | 9100 | agente de chat independiente, su propio bot de Telegram opcional, memoria y herramientas |
| Web / PWA en desarrollo (`pnpm dev`) | 9002 / 9003 | servidores de Vite; en uso normal no hacen falta |

`laplace iniciar` enciende los dos primeros; `--sin-agente` deja solo el backend. Los procesos se controlan con PID propio (`runtime/pids/`) y escriben en `backend/logs/`.

## Carpetas
```
backend/api/       main.py, agent_main.py, web_estatico.py, alembic/ (migraciones)
  routers/         admin, agent, app_gateway, auth, deportivo, partidos, prediccion_web, resultados, scheduler, simulador, track_record, web, web_catalog
  services/        motor, consenso, pronostico, modelo_historico, odds*, h2h*, calidad_datos, nivel_evidencia, ai_client, agent_*, colector_resultados…
  ml/              dixon_coles, métricas, reajuste, capa en vivo; `alias/` (nombres de ligas). Los modelos entrenados no se publican: se generan en `artefactos/`
  bot/             bot principal y bot del agente (Telegram)
  db/ models/ schemas/ core/   repositorios, tablas SQLAlchemy, esquemas Pydantic, configuración y autenticación
backend/agents/    paquete `laplace_agents` (auto-evaluación, memoria, votos) y `.laplace/` (definición y reglas del agente)
backend/knowledge/ guías para el agente (agente, sports: glosario y fútbol general, betting, human)
backend/data/      (no se publica) datos históricos y capa de resultados en vivo; se crea al usarlo: ver [motor-de-pronostico](../motor-de-pronostico.md)
backend/scripts/   doctor, reajuste, evaluación, colector, administración
backend/tests/     pruebas (pytest)
```

## Datos
SQLite por defecto (`backend/db/bot_deportivo.db`, modo WAL); con `DATABASE_URL` distinta de SQLite se asume Postgres. Las migraciones se aplican con `alembic upgrade head` (lo hace el instalador). La BD debe vivir en un disco local, no en una carpeta de red ni en una sincronizada.

## Tareas programadas
Cron, función y propósito de cada trabajo (hora de Chile): [`../backend/referencia/TRABAJOS_PROGRAMADOS.md`](../backend/referencia/TRABAJOS_PROGRAMADOS.md), generado del código.

## Autenticación
- **Web y PWA:** JWT (`Authorization: Bearer`); el código del navegador nunca envía `x-kairos-key`.
- **Nombres heredados:** el proyecto nació con el nombre «Kairos» y cuatro nombres de la interfaz entre piezas lo conservan por compatibilidad: la variable `KAIROS_AUTH_SECRET`, la cabecera `x-kairos-key`, la variable `VITE_KAIROS_BACKEND_URL` y la ruta `/webhook/kairos-app`. Cambiarlos rompe los `.env` y las apps ya compiladas, por eso no se renombran sin una migración; el resto del código usa «Laplace».
- **App Android:** cabecera `x-kairos-key` con el secreto compartido `KAIROS_AUTH_SECRET`, que se inyecta al compilar y no está en el repositorio.
- Las rutas de administración exigen rol `admin`.
