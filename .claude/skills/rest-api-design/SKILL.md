---
name: rest-api-design
description: Versionado de API, envelope de respuesta consistente, paginación cursor vs offset, idempotency keys, headers de rate-limit y checklist de anti-patrones REST. Complementa `backend-core` (que ya cubre el patrón FastAPI/Pydantic/response_model básico de este proyecto) — usar esta skill para las decisiones de diseño de API que `backend-core` no detalla: versionado, paginación, e idempotencia.
---

# rest-api-design

Diseño de endpoints REST para el futuro backend FastAPI de Laplace (Fase 2, no implementado
todavía — hoy el contrato real es el de WF-A2, ver `AGENTS.md` §7) — complementa `backend-core`
con las decisiones de diseño de API que no están ahí: cómo versionar sin romper clientes, qué
forma de paginación usar, y cómo hacer idempotentes los endpoints que reciban reintentos (ej. un
futuro webhook de un proveedor de datos deportivos, o la propia app reintentando un POST).

**Portado de**: `rest-api-design` + `api-architect` (MIT License) del paquete `some_claude_skills-main`. Contenido reescrito de cero — los originales son Next.js/Zod (stack no usado en este proyecto); aquí se mantiene solo el razonamiento de diseño de API (versionado, envelope, idempotencia, anti-patrones) adaptado a FastAPI + Pydantic v2.

---

## Cuándo usar esto vs `backend-core`

- Estructura de router, `Depends()`, `response_model`, orden de rutas, mapeo de excepciones → `backend-core`.
- Estrategia de versionado, forma de la paginación, diseño del envelope de error, idempotencia de webhooks, headers de rate-limit → esta skill.

## Versionado — recomendado desde el día 1 de FastAPI

Versionar con prefijo de URL (`/api/v1/...`) — opción simple y correcta para una API con pocos
clientes conocidos (app Android, web, bot Telegram), sin necesidad de negociación de versión por
header. No introducir un segundo mecanismo de versionado (header `Accept`, query param) sin razón
concreta.

- Un cambio que rompe compatibilidad (quitar un campo, cambiar el tipo de un campo existente)
  requiere `/api/v2/` del recurso afectado, no modificar `/v1/` in-place — la app Android y la web
  dependen de la forma actual.
- Agregar un campo nuevo opcional a una respuesta NO es breaking — no requiere nueva versión.
- Antes de dar una ruta de `/v1/` por "deprecada", verificar que ni `app-android/` ni `frontend/`
  la siga llamando.

## Envelope de Respuesta — consistencia entre endpoints

Usar la convención de error `{"detail": "mensaje"}` (nativa de FastAPI vía `HTTPException`) desde
el primer endpoint — no introducir un envelope `{success, data, error}` distinto en unos y no en
otros, generaría dos formatos de error en la misma API.

Para listas paginadas, sí conviene un envelope consistente (`skip`/`limit` en query params):

```python
class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)
    items: list[T]
    total: int
    skip: int
    limit: int
```

Aplicar el mismo `PaginatedResponse[ProductOut]` a todo endpoint de listado nuevo — no inventar una forma distinta por endpoint (`{data: [...], count: N}` en uno, `{results: [...], meta: {...}}` en otro).

## Paginación — `skip`/`limit` (offset) vs cursor

Recomendado por defecto: `skip`+`limit` (offset-based) — suficiente para listados de tamaño
moderado (ej. historial de picks de un usuario, partidos del día) sin scroll infinito en tiempo
real ni escrituras concurrentes que reordenen resultados entre páginas.

- Offset-based (`skip`/`limit`) se degrada en `OFFSET` muy grande — no sería un problema para
  paginación de UI normal, pero sí para un export completo o miles de páginas.
- Si un endpoint necesita paginar un feed que cambia constantemente (ej. un futuro stream de
  resultados en vivo), usar cursor-based (`WHERE id > :last_id ORDER BY id LIMIT :limit`) en vez
  de offset — evita duplicados/saltos cuando se insertan filas entre páginas.

## Idempotencia en endpoints reintentables

Ver `.claude/skills/backend-api-seguridad/SKILL.md` → "Idempotencia" para el patrón completo —
**cualquier endpoint POST/PUT que un cliente pueda reintentar de forma ambigua** (ej. la app
reintentando `crear_job` tras un timeout de red, sin saber si el job ya se creó) debería
considerar el mismo patrón:

```python
@router.post("/jobs", response_model=AnalysisJobOut)
def crear_job(
    payload: AnalysisJobCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if idempotency_key:
        existing = db.query(AnalysisJob).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing  # misma respuesta, sin duplicar el efecto (ej. no crear 2 jobs del mismo partido)
    job = AnalysisJob(**payload.model_dump(), idempotency_key=idempotency_key)
    ...
```

Requiere una columna `idempotency_key` (única, nullable) en la tabla del recurso — considerar
solo para endpoints donde un doble-click/reintento de red crearía un duplicado con efecto real
(un job de análisis duplicado, un push duplicado), no agregarlo especulativamente a cada POST.

## Rate-Limit Headers — exponer lo que `slowapi` calcule

Si se usa `slowapi` para limitar la tasa de requests (ej. límite de análisis/día del plan free,
hoy manejado por `verificar_limite` en `db_query.py` sin headers HTTP): para que el cliente pueda
mostrar "espera N segundos" en vez de solo un 429 genérico, devolver los headers estándar:

```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0
Retry-After: 45
```

`slowapi` expone esto vía el handler de excepción de `RateLimitExceeded` — verificar que esté
conectado en `main.py` antes de asumirlo, cuando exista.

## Checklist de Anti-Patrones REST (aplicar al diseñar un endpoint nuevo)

- **URLs con verbos** (`/getPartidos`, `/crearJob`) → usar sustantivos + método HTTP (`GET /partidos`, `POST /jobs`).
- **Envelope inconsistente** entre endpoints similares (uno devuelve `{data: [...]}`, otro un array pelado) → ver sección Envelope arriba.
- **Sin paginación en un listado** que puede crecer sin límite → siempre `skip`/`limit` con un `limit` máximo forzado en el schema (`Query(le=100)`), nunca confiar en que el cliente pida un límite razonable.
- **Over-fetching** — un endpoint que devuelve 40 campos cuando el frontend usa 3, en un recurso con payload pesado (ej. `razonamiento`/`texto_completo` de un análisis en un listado) → considerar un schema de listado más angosto separado del de detalle.
- **Errores internos filtrados** (stack trace, mensaje de SQLAlchemy crudo) en la respuesta 500 → ver `backend-api-seguridad` para el manejo de excepciones, nunca `except Exception as e: return {"detail": str(e)}` con el error crudo de una librería.
- **Sin `response_model`** → ya es regla obligatoria de `backend-core` — repetido acá porque es el anti-patrón #1 más común en auditorías reales (expone campos internos que el schema de salida debería filtrar).

## Ver también

- `la skill backend-core (no incluida en el repo publico)` — patrones FastAPI/Pydantic/SQLAlchemy del día a día.
- `.claude/skills/backend-api-seguridad/SKILL.md` — idempotencia de webhooks, matriz IDOR/BOLA, auth por endpoint.
- `AGENTS.md` §7 y `docs/arquitectura/APP_BACKEND_BRIDGE.md` — contrato real de la API hoy (WF-A2), actualizar si un endpoint FastAPI nuevo introduce alguno de estos patrones.
