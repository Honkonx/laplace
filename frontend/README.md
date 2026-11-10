# Laplace — Web (frontend/)

Web pública de Laplace — SPA en React + Vite + TypeScript + Tailwind 4, sin backend propio.
Consume directo la API real (`backend/api/`, FastAPI) por HTTP; no tiene lógica de predicción
propia ni base de datos propia.

## Páginas

| Página | Ruta | Descripción |
|---|---|---|
| `Home.tsx` | `/` | Partidos del día + predicciones |
| `Entrar.tsx` | `/entrar` | Login (JWT) |
| `Simulador.tsx` | `/simulador/:ligaSlug` | Simulador de tabla de posiciones |
| `Admin.tsx` (+ `admin/`) | `/admin/*` | Panel de administración |

## Desarrollo local

```bash
pnpm install
cp .env.example .env   # completar VITE_KAIROS_BACKEND_URL si el backend no corre en :9001
pnpm dev                # puerto fijo 9002 (vite.config.ts) — o usar scritp/iniciar-web.bat
```

Requiere el backend real corriendo (`backend/api/`, ver `README.md` de la raíz del repo) para
tener datos — esta web no tiene datos ni lógica propia.

## Tests

```bash
pnpm test
```

## Stack

- [React 19](https://react.dev/) + [React Router 7](https://reactrouter.com/)
- [Vite 6](https://vitejs.dev/) — sin SSR, sin servidor propio (SPA pura)
- TypeScript
- [Tailwind CSS 4](https://tailwindcss.com/)
- [Vitest](https://vitest.dev/) + Testing Library
