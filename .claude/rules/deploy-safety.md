# Seguridad de despliegue — VPS/Docker (forward-looking, Fase 2)

> Creada 2026-09-04, destilada (no copiada) de las reglas de despliegue de otro proyecto del
> usuario que ya opera en VPS real con Docker Compose + Cloudflare tunnel — mismo mecanismo de
> túnel que ya usa Laplace hoy en Termux. Hoy Laplace no tiene VPS real (`DEPLOY_ENV.md` lo lista
> como "futuro"), pero el riesgo del túnel ya aplica ahora mismo en Termux/Cloudflare.

## Nunca `docker compose up -d` sin nombrar servicios, si hay un túnel compartido

`up -d --build` sin nombrar servicios levanta TODO lo definido en el compose — incluido un
`cloudflared` que podría usar el mismo token de túnel que producción. Dos conectores del mismo
túnel compiten y pueden enrutar tráfico real hacia un entorno de prueba desactualizado, sin
ningún error visible. **Aplica ya**: si alguna vez se levanta una segunda instancia de
`cloudflared` (local, WSL, staging) apuntando al mismo `CLOUDFLARE_TUNNEL_TOKEN` que usa
`<tu-dominio>`, verificar que no compita con el túnel real antes de dejarlo
corriendo.

## Flujo de deploy (cuando exista VPS real): siempre manual GitHub→VPS, nunca local→VPS directo

```
local (git push) → GitHub → [paso manual, humano decide cuándo] → SSH a la VPS → deploy real
```

Nunca `scp`/`rsync` código directo a un servidor real. Si algún día hay un botón de deploy en
GitHub Actions, tiene que ser `workflow_dispatch` (manual), nunca automático en cada push.

## Verificar que el backend REALMENTE se reinició — no solo el health check

Un `/health` en 200 no prueba que el código nuevo está cargado — puede seguir corriendo el
proceso viejo en memoria. Verificación real (aplicable ya al esquema n8n actual, y directo a
FastAPI en Fase 2): confirmar que un endpoint/campo nuevo del cambio recién desplegado aparece
en la respuesta real (o en `/openapi.json` cuando exista FastAPI), no solo el código de estado.

## Backups — siempre requieren autorización explícita del usuario, cada vez

Nunca correr un script de backup por iniciativa propia, aunque las condiciones (cambio grande,
antes de tocar algo riesgoso) lo sugieran — son señales de "cuándo tendría sentido", no
autorización para ejecutarlo. Aplica a `bot_deportivo.db` hoy y a cualquier backup de Postgres
que exista tras la Fase 2.

## Si en el futuro `frontend/` se vuelve una PWA — Service Worker nunca cache-first para navegación

Nota preventiva (incidente real documentado en otro proyecto, aplicable si Laplace web agrega un
Service Worker): la navegación (`index.html`) de un Service Worker de shell debe ser siempre
network-first (red real, caché solo de respaldo offline) — cache-first es seguro únicamente para
assets con hash en el nombre (JS/CSS de Vite/Astro), nunca para rutas de navegación. Sin esto, un
usuario puede quedar pegado indefinidamente a una versión vieja del sitio sin ningún error
visible, y el propio `sw.js` no se actualiza si Cloudflare/CDN lo cachea con un TTL de archivo
estático por defecto — si existe un `sw.js`, forzar `Cache-Control: no-cache` en su respuesta.

## Prioridad operativa vigente — terminar local antes del VPS

**La VPS es la última fase de esta etapa.** Antes de preparar, contratar o desplegar infraestructura
remota deben estar completos y verificados localmente el agente, el bot deportivo, sus contratos,
la web/PWA, los dos bots de Telegram, la persistencia, el motor de predicción, QA y la prueba real
del APK mediante Cloudflare Tunnel. Cloudflare Tunnel se usa para pruebas de integración web/APK
cuando corresponda; no adelanta el despliegue VPS.
