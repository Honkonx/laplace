# Laplace — PWA (`pwa/`)

La versión instalable de la web: React + Vite + TypeScript, sin servidor propio. Habla con la API de `backend/` por HTTP y usa JWT; nunca lleva secretos.

## Páginas
`Home` (partidos del día), `Calendario`, `TopPicks`, `Agente` (chat), `Simulador`, `Perfil` y `Entrar` (login).

## Comandos (solo `pnpm`)
```
pnpm install --frozen-lockfile
pnpm dev          # servidor de desarrollo
pnpm lint         # ESLint
pnpm test         # pruebas
pnpm build        # tsc + vite build
```

## Configuración
`VITE_KAIROS_BACKEND_URL` apunta al backend (por defecto `http://127.0.0.1:9001`). El nombre conserva el prefijo histórico «KAIROS» (ver `docs/arquitectura/VISION_GENERAL.md`).

## Service worker
`public/sw.js`: la navegación (`index.html`) va siempre primero a la red y el caché es solo respaldo sin conexión; solo los archivos con hash en el nombre se sirven desde caché. Así una versión nueva llega sin dejar a nadie pegado a la vieja.
