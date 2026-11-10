# pnpm es el único gestor de paquetes de Node: npm y npx están prohibidos

> Creada 2026-11-09, orden explícita del usuario: "queda prohibido usar npm y ahora se usará pnpm". Aplica a `frontend/`,
> `pwa/` y a cualquier proyecto de Node que se agregue (herramientas, scripts, CI).

## Regla
- **Se usa `pnpm`** para instalar, ejecutar scripts, correr tests y compilar: `pnpm install`, `pnpm dev`, `pnpm test`,
  `pnpm build`, `pnpm exec <bin>` (en lugar de `npx`), `pnpm dlx <paquete>` (para ejecutar sin instalar), `pnpm add` y
  `pnpm remove`.
- **Está prohibido `npm` y `npx`** (también `npm.cmd`, `npm ci`, `npm i`, `npm --prefix`). No se escriben en scripts,
  README, documentación vigente, agentes ni workflows de CI, y no se ejecutan en una sesión.
- **Lockfile único:** `pnpm-lock.yaml` en cada proyecto. Un `package-lock.json` o `yarn.lock` es un defecto: se convierte
  con `pnpm import` y se elimina el viejo. Cada `package.json` declara `"packageManager": "pnpm@<versión>"`.
- Instalar dependencias en local sigue permitido en `frontend/` y `pwa/` (la web se desarrolla en local por diseño).

## Cómo se hace cumplir (no depende de acordarse)
`un hook del repositorio de trabajo (no publicado)` es un hook `PreToolUse` de Claude Code (registrado en `.claude/settings.json`): rechaza
cualquier comando de Bash que ejecute `npm` o `npx` y dice qué `pnpm` usar. Solo mira el comando que se ejecuta, no un
texto que mencione "npm" (un `grep npm` o un nombre de archivo pasan).

## Excepciones
- La documentación **fechada** (`docs/humano/`, auditorías, el registro de decisiones del autor (no publicado)) conserva los comandos `npm` que se
  corrieron ese día: es una foto (`documentacion-fechada-y-cadencia-de-auditoria.md`).
- Las skills y referencias traídas de otros proyectos (`.claude/skills/`, `referencias/`) no se editan; si una skill
  recomienda `npm`, se aplica su equivalente de `pnpm`.
- No hay workflows de GitHub (`sin-github-actions.md`), así que no hay CI donde configurar pnpm.

## Por qué
Una sola herramienta evita lockfiles distintos según quién instaló, instala más rápido y ocupa menos disco (almacén
compartido), y encaja con el plan de instalación portable (`un documento archivado del autor (no publicado)`),
donde el instalador trae su propio Node y su propio pnpm.
