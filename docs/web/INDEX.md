# docs/web/ — Web y PWA (React + Vite)

Dos SPA sin servidor propio que hablan con la API por HTTP y usan JWT; el navegador nunca recibe secretos. Cada una tiene su README.

| Proyecto | Puerto de desarrollo | Qué es |
|---|---|---|
| `frontend/` | 9002 | La web. La sirve el backend ya compilada (`frontend/dist`). Incluye el panel de administración (stats, usuarios, códigos de acceso, historial de planes, intentos de login, jobs, conexiones e IA global) |
| `pwa/` | 9003 | Versión instalable con manifest y service worker |

Ambas tienen su propio `manifest.json`, `sw.js` y registro del service worker (`frontend/src/lib/registrarServiceWorker.ts`). El service worker va siempre primero a la red para la navegación y solo cachea archivos con hash.
Comandos (solo `pnpm`): `pnpm install --frozen-lockfile`, `pnpm dev`, `pnpm lint`, `pnpm test`, `pnpm build` (y `pnpm exec tsc -b`). El cliente HTTP de la web está dividido por área en `frontend/src/lib/api/` (`cliente`, `auth`, `partidos`, `prediccion`, `admin`, `agente`). El logo está en `art/logo.png` (lo muestra el README) y los íconos, favicons e ícono maskable de ambas apps en `icons/` de cada `public/`. Rutas que consumen: [`../backend/referencia/API.md`](../backend/referencia/API.md).
