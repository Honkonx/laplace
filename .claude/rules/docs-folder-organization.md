# Criterio de organización de `docs/` — qué va en cada carpeta

> Adaptado 2026-09-04 del patrón usado en otro proyecto del usuario. Regla del usuario, citada
> textual de ese proyecto y confirmada como criterio general suyo: "aunque sean 20 carpetas, lo
> importante es tener estructura". Las carpetas temáticas van **top-level dentro de `docs/`,
> nunca anidadas** dentro de otra carpeta temática — se crean nuevas cuando un tema crece lo
> suficiente, sin pedir permiso para el nombre exacto.

## Carpetas actuales y criterio

| Carpeta | Qué va acá | Qué NO va acá |
|---|---|---|
| `docs/arquitectura/` | Specs de diseño vigente, mapas transversales del sistema completo (inventario de archivos, contratos de interfaz entre componentes), planes/propuestas sin implementar | Documentación específica de un solo componente — eso va en `backend/`, `app/` o `web/` |
| `docs/backend/` | Documentación del motor Python + n8n: arquitectura del bot, mejoras planificadas, análisis de dominio (predicciones, ligas) | Contratos de interfaz cruzados con la app — eso es `arquitectura/` (`bot_utils.md`, `APP_BACKEND_BRIDGE.md`) |
| `docs/app/` | Documentación de la app Android (Kotlin/Compose): componentes, visión de producto, mejoras planificadas | — |
| `docs/web/` | Documentación de la web (Astro/React) — vacía hoy, se puebla conforme avance `frontend/` | — |
| `docs/deploy/` | Documentación de despliegue/infraestructura (Docker, hosting, futuro: FastAPI + Postgres) — vacía hoy, para cuando avance la Fase 2 de migración | `DEPLOY_ENV.md` (rutas/entornos actuales) sigue en la raíz del repo, no se duplica acá |
| `docs/humano/` | Log de sesión propio de este proyecto (ver `session-log-humano.md`) | — |
| `docs/archive/` | Documentación obsoleta de cualquier carpeta — ya existía antes de este reorden, se mantiene igual | Documentación vigente, aunque esté desactualizada — si algo vigente queda desactualizado, se corrige in-place |

## Regla dura al mover contenido entre carpetas

Corregir TODAS las referencias cruzadas rotas (rutas `docs/archivo.md` citadas desde otros docs
o skills) **en la misma ronda** que el movimiento — no dejarlo para después. Si el repo tiene
historial de git al momento del movimiento, usar `git mv` en vez de mover+borrar para preservar
la trazabilidad (no aplicaba en este reorden porque el repo se inicializó en la misma ronda, sin
commits previos).

## Actualización 2026-11-10 — `docs/` describe solo lo vigente
- Carpetas: `arquitectura/` (lo que cruza componentes), `backend/` (bot, IA, laboratorio y `referencia/` **generada del código**), `agente/`, `app/`, `web/`, `deploy/`, `qa/`, `humano/` (privado) y `archive/`.
- **Todo lo que es una foto con fecha** (auditorías, investigaciones, evaluaciones, rondas, planes, especificaciones, QA con fecha) y lo obsoleto (Termux, n8n, Kairos, la app React Native) va a `archive/<tema>/`
  (`auditorias`, `investigaciones`, `evaluaciones`, `rondas`, `planes`, `especificaciones`, `qa`, `obsoleto`, `kairos-termux`, `referencias`, `bocetos`), con `git mv` y las rutas corregidas en la misma ronda.
- Un documento vigente no lleva fecha en el nombre ni historia dentro: describe el código de hoy. Las referencias de `backend/referencia/` no se editan a mano: `python backend/scripts/generar_referencia_docs.py`.
