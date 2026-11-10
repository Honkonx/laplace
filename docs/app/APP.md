# App Android

Cliente nativo Kotlin + Jetpack Compose (Material 3) para consultar los pronósticos de Laplace. No contiene lógica de pronóstico: consume el backend.

| | |
|---|---|
| Paquete | `com.laplace.mobile` (`app-android/app/src/main/java/com/laplace/mobile/`) |
| SDK | `minSdk` 24 · `compileSdk` / `targetSdk` 36 · versión 1.0.0 |
| Red | Retrofit (`data/remote/LaplaceApi.kt`): gateway `POST /webhook/kairos-app` (alias de `/api/v1/deportivo`), `/api/v1/auth/*`, `/api/v1/prediccion-web` y las rutas `/api/v1/agent/*` |
| Local | Room (`data/local/`), preferencias y sesión; WorkManager para sincronización y notificaciones |
| Permisos | `INTERNET`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE` |

## Pantallas (`ui/screens/`)
Inicio, partidos y ligas, calendario, Top Picks, pronóstico (`prediction`), estadísticas, historial, perfil, registro y onboarding, código de acceso, planes (`upgrade`), agente, notificaciones, ajustes (tema), registro de actividad y «acerca de». La navegación está en `navigation/` (`Screen`, barra inferior, cajón).

## Configuración y compilación
Propiedades de Gradle `laplaceBaseUrl`, `laplaceApiKey`, `laplaceAgentUrl` y `laplaceCommunityUrl` (o sus variables `LAPLACE_*`); detalle en `app-android/README.md`. Contrato con el backend: [`../arquitectura/APP_BACKEND_BRIDGE.md`](../arquitectura/APP_BACKEND_BRIDGE.md).
