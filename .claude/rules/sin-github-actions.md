# No hay workflows de GitHub Actions: la verificación se hace en local

> Creada 2026-11-09, orden explícita del usuario: "no quiero workflows en github, eso no sirve de nada para este proyecto, así
> que elimínalos". Se eliminaron `.github/workflows/backend-tests.yml`, `build-app.yml`, `build-native.yml` y `web-tests.yml`
> (siguen en el historial de git por si algún día se piden de nuevo).

## Regla
- **No se crean ni se restauran workflows de GitHub Actions** (ni `.github/workflows/`) sin una orden nueva y explícita.
- La verificación es local y la hace quien trabaja: `pytest` del backend, `pnpm test` / `pnpm exec tsc -b` / `pnpm build` en
  `frontend/` y `pwa/`, y la paridad de configuración con `.codex/scripts/verify-agent-config.ps1`.
- **La APK no se compila sin orden expresa** (`feedback`: nunca por iniciativa propia). Antes de subir cambios de Android se dice
  que no se compilaron; ya no hay un CI que los compile por nosotros.
- Un push no se considera "verificado por CI": se reporta lo que se corrió en local y lo que no.

## Qué cambia en la práctica
Sin CI, la red de seguridad es la suite local (1.191 tests de backend el 2026-11-09). Por eso las pruebas deben seguir
aislándose del `.env` y de la máquina (`conftest.py`), y un cambio de comportamiento lleva su test en el mismo commit.
