# backend-api-seguridad

API contract design, logging patterns, and security hardening for the backend.
Use when designing APIs, implementing security, or setting up monitoring.

**Fusionado de**: `api-contract-review`, `logging-patterns`, `security-audit`, `VibeSec-Skill-main`, `fullstack-guardian`, `secure-code-guardian`, `security/*`, `anthropics/investigacion-bidireccional-2026-07-28` (puntos frágiles ya golpeados), `security-advisor-main` (exploit-path + gate de confianza), `tahr-security-skills-main/tahr-test-access-control` (matriz IDOR/BOLA/BFLA), `faos-skills-marketplace-main/owasp-api-top10` (BOLA/mass-assignment FastAPI), `skills-collections-main/antigravity-idor-testing` (checklist IDOR), `claude-skills-main` (`csrf-protection`, `xss-prevention`, `oauth-implementation`, `idempotency-handling`, `api-security-hardening`). Ver también `.claude/skills/seguridad-avanzada/SKILL.md` (threat modeling STRIDE, auditoría de dependencias, incidente de secretos, triage de vulnerabilidades, patrón de auditoría multi-agente) — fusionado de `claude-cybersecurity-main`, `superhacker-skill-main`, `security-compliance-hardening-main`.

---

## API Contract Design
- RESTful endpoints: `/api/v1/[recurso]`
- Proper HTTP verbs: GET (read), POST (create), PUT (full update), PATCH (partial), DELETE (soft-delete)
- Versioning via URL path (`/v1/`, `/v2/`)
- Response wrapper consistency across all endpoints
- Pagination: `skip` + `limit`, return `X-Total-Count` header
- Error format: `{"detail": "mensaje legible"}`, never expose stack traces in prod
- Breaking changes: bump version, never silently change contract
- Deprecation: announce with `Deprecation` and `Sunset` headers

## Security Hardening

### Access Control
- Every endpoint requires `get_current_user` dependency (except health + login)
- Role-based: `require_admin` for admin operations
- UUIDs over sequential IDs for public-facing resources
- Always validate ownership before updating/deleting

### Input Protection
- SQL Injection: ALWAYS parameterized queries / ORM — NO raw SQL
- XSS: output encoding, Content-Security-Policy header
- CSRF: token validation for state-changing operations
- SSRF: allowlist URLs, block internal IPs
- Path Traversal: canonicalize paths, validate boundaries
- XXE: disable external entity processing in XML parsers

### Auth & Secrets
- JWT: `python-jose` with HS256, validate algorithm to prevent confusion attacks
- Passwords: bcrypt hashing, min 8 chars, 1 letter + 1 number (si Laplace llega a tener login con
  contraseña — hoy la app/web se identifican por `device_id`, sin contraseña de usuario)
- NEVER hardcode secrets — always from `.env` via `settings`
- Rotate SECRET_KEY in production
- Rate limiting: slowapi, 30/min on login (por IP) + bloqueo por cuenta tras 5 intentos fallidos (15 min), 200/min global. Clave del limitador: usuario autenticado (JWT `sub`) cuando hay sesión, IP solo para tráfico sin autenticar (2026-08-17, NEW-48)

### File Uploads
- Validate MIME type server-side
- Max file size: 5MB for images
- Only allow: PNG, JPG, JPEG, WebP
- Store with UUID names, not user-provided filenames
- Scan for magic bytes to verify actual format

### Security Headers
- Content-Security-Policy
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Strict-Transport-Security (HSTS)
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy

## Structured Logging
- JSON format for AI/production analysis
- Fields: `timestamp`, `level`, `logger`, `message`, `request_id`, `user_id`, `path`
- MDC (Mapped Diagnostic Context) for request tracing
- Log levels: DEBUG (dev), INFO (flow), WARNING (anomaly), ERROR (failure)
- What to log: business events, external calls + timing, flow steps
- NEVER log: passwords, tokens, card numbers, PII

## JWT Security
- Store in HttpOnly cookies (not localStorage for production)
- Set `secure: true` and `sameSite: strict` for cookies
- Short-lived access tokens (8h) + remember me (24h)
- Validate `exp`, `iat`, `iss` claims
- Always specify `algorithms=["HS256"]` in decode

## Exploit-Path Obligatorio y Gate de Confianza (al Auditar/Revisar)
Un hallazgo de seguridad no es un hallazgo hasta que se puede escribir como ruta de ataque concreta. Antes de reportar cualquier problema (propio o en code review):
1. **Ubicación exacta**: `archivo:línea`, no una descripción vaga del área.
2. **Ruta de explotación en 3-5 pasos**: "paso 1, el atacante hace X; paso 2, el sistema responde Y; paso 3, el atacante ahora tiene Z". Si hay un salto de fe en el medio ("de alguna forma el usuario llega a admin"), todavía no es un hallazgo — seguir investigando o descartarlo.
3. **Puntaje de confianza 1-10**: por debajo de 7, no reportar como hallazgo confirmado ("podría ser" no cuenta). 7-8 se reporta con la etiqueta "necesita revisión humana"; 9-10 se afirma directamente.
4. **Barrido de variantes**: si se encontró un endpoint sin re-autenticación, grepear el resto del código por el mismo patrón — rara vez aparece una sola vez.
5. **Distinguir ausencia-de-hardening de presencia-de-vulnerabilidad**: "este endpoint no tiene rate limit" es MEDIUM como máximo, y solo si hay una amplificación concreta (fuerza bruta de auth, costo de API paga). "Falta CSP" es MEDIUM, no CRITICAL, salvo que haya un XSS real que amplificar. No inflar gaps de buenas prácticas a severidad crítica.

## Gate de Seguridad ANTES de Codear (no solo auditar después)
Otro proyecto de referencia encontró varios bugs de seguridad reales (escalación de privilegios,
lecturas obsoletas bajo concurrencia, firmas de webhook mal validadas) en rondas de auditoría
POST-HOC — el patrón preventivo vale igual para Laplace. Antes de implementar cualquier endpoint
nuevo que toque auth/datos sensibles, responder 3 preguntas primero:
1. **¿Quién puede llamar esto?** — ¿el `device_id`/plan correcto? (ver el header `x-kairos-key`
   hoy; `get_current_user`/`require_admin` si Fase 2 agrega auth real)
2. **¿Qué pasa si alguien más lo llama con datos de otro usuario?** — probar mentalmente
   escalación horizontal (mismo plan, otro `device_id`) y vertical (plan free intentando una
   acción de plan pro/admin)
3. **¿El mensaje de error revela algo que no debería?** (ej. "usuario no existe" vs "clave
   inválida" — no confirmar existencia)

## Puntos frágiles típicos en este tipo de arquitectura (patrón, no bugs reales de Laplace todavía)
Antes de tocar código cerca de estas áreas, en la Fase 2:
- **Registro de providers**: si se formalizan providers intercambiables (odds/stats/resultados),
  verificar con un test que el registro de providers NO esté vacío al importar el módulo — un
  provider que nunca se registra falla en producción de forma no obvia.
- **Contadores/límites concurrentes**: el límite de análisis/día del plan free (`verificar_limite`
  en `db_query.py`) puede sufrir el mismo problema que una lectura de stock obsoleta bajo
  concurrencia real — si se migra a SQLAlchemy/Postgres, usar `with_for_update()` y verificar el
  límite DESPUÉS de tomar el lock, no antes (ver `.claude/rules/database-safety.md`).
- **Escalada de privilegios**: horizontal (mismo plan, otro `device_id`) y vertical (plan menor
  ejecutando acción de plan mayor) — todo endpoint que reciba un `device_id`/`user_id` en el
  path/body debe validar que corresponde al caller actual.
- **Webhooks/callbacks sin verificar firma**: si algún día Laplace recibe un webhook entrante (ej.
  de un proveedor de pagos si se monetiza), validar firma/HMAC antes de procesarlo.

## Matriz de Control de Acceso — IDOR/BOLA/BFLA
Complementa la sección anterior: matriz para probar sistemáticamente cada endpoint nuevo o
modificado. Para cada operación que lee/escribe un recurso, definir sujeto (`device_id`, plan),
acción y recurso, y probar:
- **BOLA/IDOR** (OWASP API1): ¿el ID del recurso viene del path/body y se usa sin verificar que
  pertenece al `device_id` actual? Patrón malo: `db.query(Model).get(id)`. Patrón bueno:
  `db.query(Model).filter(Model.id == id, Model.device_id == current_device_id).first()` — y
  devolver 404 (no 403) tanto si no existe como si no pertenece, para no confirmar existencia.
- **BFLA** (OWASP API5, función/rol): ¿un endpoint admin-only (ej. forzar republicar el canal)
  depende solo de que el cliente no lo llame, o hay verificación real en el handler?
- **Mass assignment** (OWASP API3): ¿el endpoint de update acepta el body completo hacia el ORM,
  o usa un schema explícito con allowlist de campos editables? Campos que definen plan/límites
  NUNCA deben poder llegar por el body de un usuario no-admin.
- **Caso de prueba mínimo por endpoint nuevo**: `device_id` autenticado pero dueño de OTRO
  registro intenta leer/modificar — debe fallar. Plan free intenta una acción de plan pro — debe
  fallar.

## Idempotencia en endpoints reintentables
Si Laplace llega a recibir webhooks/callbacks externos, validar firma HMAC prueba que el evento es
legítimo, pero NO evita que se procese dos veces (reintentos del proveedor, timeout que dispara un
segundo POST). Firma válida + procesamiento no-idempotente igual permite duplicar un job de
análisis o un push.
- Guardar una tabla de claves de idempotencia (`idempotency_key` único, `request_hash`, `status:
  processing|completed|failed`, `response`, `expires_at`) y usar `INSERT ... ON CONFLICT DO
  NOTHING` para que solo una ejecución concurrente "gane" el procesamiento.
- Para proveedores que no mandan una clave de idempotencia propia, derivar una determinística:
  hash del `event_id` + tipo de evento, nunca un valor generado localmente que cambiaría en cada
  reintento.
- Limpiar claves expiradas periódicamente para que la tabla no crezca sin límite.

## OAuth2 — Checklist de Integración (hipotético — Laplace no tiene ninguna integración OAuth hoy)
Las APIs actuales de Laplace (The Odds API, api-football, BSD API, OddsPapi) usan API key simple
en header/query, no OAuth2. Si en el futuro se integra un proveedor con OAuth2 real:
- `state` aleatorio (`secrets.token_hex(16)`) generado antes del redirect y verificado byte a
  byte al volver en el callback — sin esto, el flujo es vulnerable a CSRF de login.
- `redirect_uri` exacto, no por prefijo.
- Client secret solo en el backend (`.env`), nunca expuesto al frontend ni en el `state`/query.
- Tokens de acceso de vida corta + refresh token rotado; guardar el refresh token cifrado o al
  menos fuera de logs.
- Scopes mínimos necesarios.
- El ciclo de renovación automática de credenciales debe fallar de forma visible (log + alerta),
  nunca silenciosamente dejar el token vencido sin avisar. Ver skill `oauth-oidc-implementer`
  para el flujo completo.

## Checklist Before Deploy
- [ ] All POST/PUT/DELETE require JWT
- [ ] Rate limiting active on auth endpoints
- [ ] Passwords validated (min 6, 1 letter + 1 number)
- [ ] SECRET_KEY is strong and in .env only
- [ ] File uploads have size + type limits
- [ ] No stack traces in error responses
- [ ] CORS restricted to known origins
- [ ] HTTPS enforced
- [ ] Security headers configured
