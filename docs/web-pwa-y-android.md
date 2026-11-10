# Web, PWA y app Android

## Web (`frontend/`)
React 19 + Vite + Tailwind. **No hace falta compilarla a mano:** el instalador compila `frontend/dist` y el backend la sirve en <http://127.0.0.1:9001/> (mismo origen, sin CORS). Pantallas: partidos con pronóstico, agente, historial, estado del bot, simulador y administración.

```
cd frontend
pnpm install --frozen-lockfile
pnpm dev        # http://localhost:9002 (apunta al backend en 9001)
pnpm test       # pruebas
pnpm exec tsc -b && pnpm build
```
La web usa JWT; nunca envía `x-kairos-key`. El service worker no cachea `index.html` ni `sw.js`; los archivos con hash en el nombre son inmutables.

## PWA (`pwa/`)
Misma pila, pensada para el móvil: inicio, calendario, Top Picks, agente, simulador y perfil. Mismos comandos (`pnpm dev` en el puerto 9003).

## App Android (`app-android/`)
Kotlin + Jetpack Compose (`applicationId` `com.laplace.mobile`, minSdk 24, targetSdk 36). Se compila a mano; **no hay APK en el repositorio**.

La configuración llega por propiedades de Gradle (en `~/.gradle/gradle.properties`, en la línea de comandos con `-P…` o por variable de entorno); nada de esto se versiona:

| Propiedad | Variable de entorno | Para qué |
|---|---|---|
| `laplaceBaseUrl` | `LAPLACE_BASE_URL` | URL de tu backend (por defecto `http://10.0.2.2:9001/`, el equipo anfitrión visto desde el emulador) |
| `laplaceApiKey` | `LAPLACE_API_KEY` | el mismo valor que `KAIROS_AUTH_SECRET` de tu `.env` |
| `laplaceAgentUrl` | `LAPLACE_AGENT_URL` | URL del agente (si queda vacía usa la del backend) |
| `laplaceCommunityUrl` | `LAPLACE_COMMUNITY_URL` | enlace de tu comunidad; vacío = el botón queda inactivo |

```
cd app-android
gradlew.bat assembleDebug     # Windows   (./gradlew assembleDebug en Linux/macOS)
```
**Aviso:** la app no habilita tráfico HTTP sin cifrar; para un teléfono real usa una URL `https` (por ejemplo, un túnel). El valor por defecto `http://…` solo sirve si habilitas ese tráfico en una compilación de depuración propia. Estos cambios de configuración de la app no se probaron compilando.
