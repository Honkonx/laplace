# Laplace — App Android (`app-android/`)

Cliente nativo en **Kotlin + Jetpack Compose** (Material 3). Muestra los partidos del día, el pronóstico de cada uno con su explicación, los Top Picks, el historial y las estadísticas del bot, y un chat con el agente. Laplace pronostica; no recibe dinero ni intermedia apuestas.

- `applicationId` / `namespace`: `com.laplace.mobile` · `minSdk` 24 · `compileSdk` y `targetSdk` 36 · versión 1.0.0.
- No contiene lógica de pronóstico: consume el backend (gateway `POST /api/v1/deportivo` y las rutas REST de sesión y agente). Contrato: `docs/arquitectura/APP_BACKEND_BRIDGE.md`.

## Estructura (`app/src/main/java/com/laplace/mobile/`)
| Carpeta | Contenido |
|---|---|
| `data/remote/` | `LaplaceApi` (Retrofit) y los DTO |
| `data/local/` | Room (`AppDatabase`, DAO, entidades), sesión (`AuthManager`) y preferencias |
| `data/repository/` | Repositorios de partidos, pronósticos, perfil y escudos |
| `domain/` | Modelos de dominio |
| `navigation/` | Rutas (`Screen`), barra inferior y cajón |
| `service/` | Notificaciones, sincronización y precarga |
| `ui/screens/` | Inicio, calendario, Top Picks, estadísticas, perfil, historial, agente, código de acceso, planes, ajustes, registro y más |
| `ui/components/` | Tarjetas, carruseles, escudos, gráficos y botones reutilizables |

## Configurar y compilar
Los valores propios no están en el código: se pasan como propiedades de Gradle (por ejemplo en `~/.gradle/gradle.properties`) o como variables de entorno.

| Propiedad | Variable | Para qué |
|---|---|---|
| `laplaceBaseUrl` | `LAPLACE_BASE_URL` | URL del backend. Por defecto `http://10.0.2.2:9001/` (el backend local visto desde el emulador) |
| `laplaceApiKey` | `LAPLACE_API_KEY` | Mismo valor que `KAIROS_AUTH_SECRET` del `.env` del backend; se envía en `x-kairos-key` si no está vacío |
| `laplaceAgentUrl` | `LAPLACE_AGENT_URL` | URL del agente (opcional) |
| `laplaceCommunityUrl` | `LAPLACE_COMMUNITY_URL` | Enlace del grupo o canal de Telegram; vacío deja inactivos los botones que lo abren |

```
./gradlew assembleDebug      # Windows: gradlew.bat assembleDebug
```
La clave de la API viaja dentro de la app compilada: úsala solo con un backend tuyo y no compartas el APK.

## Más
`docs/app/` (visión y estructura) · `docs/backend/referencia/API.md` (rutas) · licencia AGPL-3.0 (ver `LICENSE` en la raíz).
