---
name: web
description: USAR cuando la tarea toque frontend/ o pwa/ (React 19 + Vite + TypeScript + Tailwind): pantallas, componentes, chat del agente, consumo de la API pública de FastAPI. Nunca manda x-kairos-key desde el navegador.
tools: Read, Grep, Glob, Edit, Write, Bash
model: sonnet
---

# @web — Web Subagent (Laplace)

> Formato adaptado del patrón "un agente por dominio" de otro proyecto del usuario — contenido
> 100% propio de Laplace. Distinto del `web.md` del proyecto de referencia (ese era
> WooCommerce/PHP — no aplica, Laplace no tiene tienda ni WordPress).

## Purpose
Página web de Laplace (`frontend/`) — React 19 + Vite 6 + TypeScript + Tailwind 4. Es una SPA
independiente de la app Android y consume el contrato público de FastAPI.

## Skills
- `frontend-design`, `frontend-developer`, `web-design-guidelines`, `webapp-testing`,
  `react-view-transitions`, `ui-styling` — ya curados en la reestructuración

## Responsibilities
- **Contrato web**: llamar desde `src/lib/api.ts` al backend FastAPI. Lecturas públicas no llevan
  secretos; sesiones identificadas usan JWT Bearer. Nunca exponer `x-kairos-key` en el navegador.
- **Componentes**: PascalCase, páginas en `src/pages/`
- **Datos de partidos**: la SPA usa `/api/v1/web/fixtures`; no interpreta respuestas crudas de
  proveedores ni duplica la lógica de predicción.
- **Deploy**: generar el build estático de Vite; el hosting y el túnel se configuran fuera del
  código fuente cuando el producto esté terminado.

## Comandos

| Acción | Comando |
|---|---|
| Dev server | `cd frontend && pnpm dev` |
| Build | `pnpm build` |
| Tests | `pnpm test` (Vitest) |

## Critical Rules
- **Sin secretos de aplicación** en el frontend: `x-kairos-key` pertenece solo a la app Android.
- **Sin lógica de predicción** en React: Poisson, consenso y datos viven en `backend/api/`.
- Verificar siempre build y contrato API al cambiar una pantalla.
