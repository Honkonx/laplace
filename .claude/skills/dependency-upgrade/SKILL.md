---
name: dependency-upgrade
description: Estrategia segura para actualizar dependencias npm (3 frontends) y pip (backend) — staged upgrade de a una por vez, protección contra supply-chain attacks, y checklist pre/post-actualización. Usar al subir una versión mayor de una librería, al ver un CVE reportado, o antes de un `npm audit fix`/`pip install --upgrade` grande.
---

# dependency-upgrade

Gestión segura de actualización de dependencias: análisis de compatibilidad, staged rollout de a una dependencia por vez, protección básica contra ataques de cadena de suministro, y testing en cada paso.

**Fusionado de**: `claude-skills-main/dependency-upgrade` (MIT License, ver `mios/listo/claude-skills-main/LICENSE`) — adaptado de su versión original centrada en npm/Bun/pnpm/Socket CLI a la realidad real de este proyecto: `pip` + `requirements.txt` en `backend/`, `npm` en `frontend/`, `staff/`, `app/` (sin Bun/pnpm/Yarn, sin Socket CLI instalado).

---

## Por qué esto importa acá

Tres `package.json` independientes (`frontend/`, `staff/`, `app/`) más `requirements.txt` del backend — una actualización mal probada en uno no necesariamente se nota en los otros hasta que falla en producción. El proyecto ya tuvo un bug real de caché de Vite corrompiéndose en sesiones largas (`project_vite_dev_cache_bug_20260807`) — verificar siempre con `npm run build` limpio, no solo con el dev server, después de tocar dependencias.

## Principio central: una dependencia a la vez, con testing entre cada una

Nunca correr `npm update`/`pip install -U -r requirements.txt` a ciegas sobre todo el árbol. Por cada dependencia:

```bash
# 1. Rama dedicada
git checkout -b upgrade/<paquete>-<version>

# 2. Leer el changelog de la versión objetivo antes de instalar — breaking changes, deprecaciones
# 3. Instalar solo esa dependencia
npm install <paquete>@<version>          # frontend/staff/app
pip install <paquete>==<version>          # backend (actualizar requirements.txt a mano después)

# 4. Testear inmediatamente
npm run build && npm run lint             # frontend
ruff check backend/ && pytest tests/ -v   # backend

# 5. Commit y seguir con la próxima
git add -A && git commit -m "chore: actualizar <paquete> a <version>"
```

Subir de a una versión mayor por vez (1→2→3, no 1→3 directo) cuando el salto cruza breaking changes — saltarse versiones intermedias hace que un bug nuevo sea imposible de atribuir a un cambio específico.

## Protección básica contra supply-chain attacks

El vector de ataque #1 en incidentes reales de npm (Shai-Hulud, `event-stream`, ataques vía `postinstall`) es el script de instalación de un paquete comprometido publicado recientemente. Medidas de bajo costo aplicables a los 3 `package.json`:

- **`npm ci` en vez de `npm install` en cualquier proceso automatizado/CI** — instala exactamente lo que dice el lockfile, sin resolver versiones nuevas silenciosamente.
- **Nunca ejecutar `npm install <paquete>@latest` a ciegas** — fijar versión explícita después de leer el changelog, no confiar en "la más nueva es la mejor".
- **Revisar `package-lock.json` en el diff antes de commitear** — un lockfile que cambia decenas de paquetes no relacionados con el que se quiso actualizar es señal de alerta (dependencia transitiva resuelta distinto, o algo más raro).
- **Nunca commitear cambios a dependencias sin correr los tests primero** — igual que cualquier otro cambio de código en este proyecto (`general-rules.md`).
- En backend, mismo principio con `pip`: fijar versión exacta en `requirements.txt` (`paquete==X.Y.Z`), no rangos abiertos (`>=`) para dependencias de producción — evita que un `pip install -r requirements.txt` futuro traiga una versión no probada sin que nadie lo note.

## Checklist antes de actualizar

- [ ] Changelog de la versión objetivo leído — breaking changes identificados
- [ ] Rama dedicada creada (`upgrade/<paquete>-<version>`)
- [ ] Baseline: `pytest tests/ -v` (backend) / `npm run build` (frontend afectado) pasa ANTES de tocar nada

## Durante

- [ ] Una dependencia a la vez, nunca un `update -u` masivo
- [ ] Versión exacta fijada, no `latest`/rango abierto
- [ ] Errores de TypeScript corregidos si el tipo cambió (no `as any` para silenciar — ver regla de `frontend-rules.md` de no usar `any`)
- [ ] Peer dependencies revisadas si npm avisa conflicto

## Después

- [ ] `pytest tests/ -v` / `ruff check backend/` (si tocó backend) o `npm run build` + `npm run lint` (si tocó cualquiera de los 3 frontends) — sin errores
- [ ] Probado en navegador real si la dependencia afecta UI/render (ver `frontend-rules.md` regla 16 — un build limpio no prueba layout)
- [ ] `CHANGELOG.md` actualizado si la actualización cambia comportamiento visible
- [ ] Si es un cambio grande (major version de una librería core como React/FastAPI/SQLAlchemy): seguir la regla de sincronización a `prueba` de `general-rules.md` al cerrar la tarea, con autorización explícita del usuario

## Cuándo NO usar el flujo completo

Un patch/minor de una dependencia chica sin breaking changes conocidos (ej. `lucide-react` de una versión de parche a otra) no necesita rama propia ni el checklist completo — el criterio de `general-rules.md` de "cambio chico/ya probado → commit directo a main" aplica igual acá. Reservar el flujo completo para majors, dependencias core (React, FastAPI, SQLAlchemy, Tailwind), o cualquier cosa con un CVE reportado.

## Errores comunes a evitar

- Actualizar todas las dependencias de una sola vez ("mientras estoy aquí") — si algo se rompe, no hay forma de saber cuál de las N actualizaciones fue.
- Confiar en que el código fuente mostrado en npmjs.org es igual al tarball publicado — no es garantía; por eso instalar versión fijada y revisar el lockfile importa.
- Saltarse el testing "porque es solo una librería de utilidades" — una librería chica rota puede tumbar un build entero igual de fácil que una grande.
- No actualizar `package-lock.json`/`requirements.txt` junto con el cambio real, dejando el lockfile desincronizado del código.
