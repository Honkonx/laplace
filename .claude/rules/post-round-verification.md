# Checklist de verificación post-ronda

> Adaptado 2026-09-04 de otro proyecto del usuario — el checklist original era para Kotlin/bash/
> XML de una app Termux; este es el equivalente real para el stack de Laplace (Python/FastAPI +
> SQLAlchemy/Alembic + SQLite, Kotlin/Compose, React/Vite en `frontend/` y `pwa/`).
> Actualizado 2026-09-10: `frontend/` ya no es Astro (reescrito a React+Vite el 2026-09-08) y
> `backend/python/` (que usaba `paths.py`) se archivó a `backend/_archive_python/` el
> 2026-09-10 — ver puntos 1, 6 y 7 corregidos abajo.

## Cuándo aplica

Al cerrar cualquier ronda de trabajo que tocó código — no hace falta para cambios puramente de
documentación. Cuanto más grande la ronda, más vale la pena correr el checklist completo en vez
de asumir que "corre en la cabeza".

## Checklist (correr lo que aplique según qué se tocó)

1. **Python** — `python -m py_compile <archivo>.py` sobre todo script nuevo o tocado, mínimo.
   `import requests` ya no es una restricción de diseño general (ver
   `un documento archivado del autor (no publicado)`) — solo importa si el archivo tocado es de los que
   siguen desplegándose hoy en Termux.
2. **SQLite/SQL** — ninguna sentencia nueva usa `DEFAULT (datetime('now'))`; fecha siempre
   explícita desde Python. Si ya se migró a Postgres (Fase 2), revisar el equivalente real de esa
   base (`now()` de Postgres sí es aceptable ahí — la regla original era específica de un bug de
   SQLite en ARM64, no universal).
3. **Kotlin** — sin `!!` nuevo (usar `?.` + Elvis); balance de llaves/paréntesis en todo `.kt`
   nuevo o tocado.
4. **JSON** — cualquier workflow n8n exportado o config tocada parsea sin error.
5. **`git status` confinado al alcance esperado** — los archivos tocados/nuevos son los que la
   tarea pedía, nada se filtró fuera de alcance.
6. **Rutas** — ningún path hardcodeado nuevo tipo `/data/data/com.termux/...` o `/root/...` en
   `backend/api/`. `paths.py` (el módulo que centralizaba esto) vive hoy solo en
   `backend/_archive_python/` (referencia, ya no se importa desde `backend/api/`) — el backend
   vivo usa `backend/api/core/config.py` (Pydantic `Settings`) para configuración de rutas/env.
7. **Web** — `frontend/` y `pwa/` son SPA puras (React+Vite, sin servidor propio ni proxy
   server-side — ya no hay "Astro API routes", el frontend se reescribió completo 2026-09-08).
   `fetch()` directo desde `frontend/src/`/`pwa/src/` al backend FastAPI (via
   `VITE_KAIROS_BACKEND_URL`) es el diseño esperado, no una violación. La regla real a verificar:
   ningún `fetch()` nuevo desde ese código de browser debe mandar el header `x-kairos-key` (ese
   secreto es solo para la app Android compilada, nunca para JS de navegador — un secreto en el
   bundle del browser es público por definición); la web usa JWT (`Authorization: Bearer`) para
   lo que requiere identidad.

## Nota

Este checklist es una ayuda mecánica (sintaxis, convenciones), no reemplaza revisión de
lógica/arquitectura — confirma "no rompí la sintaxis ni una regla dura conocida", no "la
funcionalidad es correcta" (para eso ver `empirical-verification-before-fix.md`).
