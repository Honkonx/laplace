# Archivos protegidos — no se tocan sin permiso explícito

> Formalizada 2026-09-04 como regla independiente; el contenido base ya existía como tabla en
> `CLAUDE.md` §"Archivos protegidos". Patrón de "regla dura de no-tocar" adaptado de otro
> proyecto del usuario, donde generó una corrección real cuando se editó un archivo protegido por
> un motivo que "parecía" no relacionado a la lógica protegida.

## Regla

Cuando un archivo está en la lista de protegidos (ver tabla abajo, o una lista que el usuario dé
explícitamente en una sesión puntual), **ningún cambio está permitido sin su permiso explícito y
fresco para ESE cambio puntual** — sin excepciones, incluyendo:

- Cambios que "parecen" separados de la parte sensible del archivo (ej. un comentario, un
  formateo, un fix chico).
- Cambios motivados por un bug real y verificado — un bug real no es autorización automática
  para tocar un archivo protegido. Se reporta el hallazgo y se pide permiso, no se arregla directo.

**Antes de editar cualquier línea de un archivo protegido**: parar, no aplicar el cambio, y
preguntar/reportar el hallazgo primero.

## Lista vigente (ver también CLAUDE.md)

```
app-android/build.gradle.kts            ← buildToolsVersion, compileSdk
app-android/gradle/libs.versions.toml   ← version catalog
```

> **Actualización 2026-09-08**: se retira `frontend/astro.config.mjs` y la protección de
> `frontend/package.json` de esta lista — el usuario ordenó explícitamente reescribir
> `frontend/` completo como React + Vite (backup de la versión Astro en
> `backend/_archive_frontend_astro/`), lo que requirió tocar ambos archivos con permiso fresco
> para ese cambio puntual. `astro.config.mjs` ya no existe (reemplazado por `vite.config.ts`).
> La razón original de proteger `package.json` ("no instalar en local, solo Vercel") ya no
> aplica — la web nueva se corre y desarrolla en local (`pnpm dev`) por diseño.
