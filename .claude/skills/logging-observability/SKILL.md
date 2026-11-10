---
name: logging-observability
description: Estrategia de niveles de log, logging estructurado (JSON), correlation IDs entre backend/integraciones externas, y redacción de PII/secretos en logs de producción (VPS). Usar al agregar logging a un servicio nuevo, al diagnosticar un incidente en la VPS que requiere correlacionar logs entre backend/nginx/túnel, o al revisar que no se esté logueando algo sensible.
---

# logging-observability

El proyecto corre en una VPS real de producción (Postgres + Redis + backend + frontend + nginx + `cloudflared`, ver `docker-vps-ops`) con logging driver `json-file` + rotación ya configurado a nivel de Docker Compose, pero sin una estrategia explícita de QUÉ loguear ni de correlación entre servicios. Esta skill cubre eso — no reemplaza `docker-vps-ops` (que cubre la infraestructura de logs: rotación, límites de tamaño) ni `metodologia-dev` (que cubre logs de debug temporales taggeados durante investigación de bugs) — es sobre la estrategia de logging de producción día a día.

**Portado de**: `logging-observability` (MIT License) del paquete `some_claude_skills-main` (`mios/listo/some_claude_skills-main/.claude/skills/logging-observability/`). Recortado drásticamente: el original asume Node.js/Pino + stack completo de OpenTelemetry/Grafana/PagerDuty que este proyecto no tiene ni necesita con su tamaño actual (VPS único, sin equipo de guardia) — se mantiene solo lo aplicable: niveles de log, logging estructurado en Python, correlation ID simple, y redacción de PII.

---

## Cuándo usar esto vs otras skills de logging/debug

- Logs de debug temporales durante una investigación de bug (taggeados, se borran después) → `metodologia-dev` → Bug-Fix Protocol.
- Rotación de logs, límite de tamaño en disco de la VPS → `docker-vps-ops`.
- Qué nivel de log usar, formato estructurado, correlación entre servicios, qué NUNCA loguear → esta skill.

## Niveles de Log — cuándo usar cada uno

| Nivel | Cuándo | Ejemplo real de este proyecto |
|---|---|---|
| `ERROR` | Falló una operación, se reintenta o se degrada | Timeout contra The Odds API, BSD API caída, fallo al parsear un scraping de Forebet |
| `WARNING` | Condición inusual pero no falló | Rate limit de Claude API cerca del límite, token OAuth próximo a expirar |
| `INFO` | Evento de negocio significativo | Job de análisis creado, pick publicado en el canal, resultado verificado |
| `DEBUG` | Detalle para diagnosticar un problema específico | Query SQL ejecutada, payload completo de una request a un proveedor |

**Regla**: producción corre con `INFO` y superior. `DEBUG` solo se activa puntualmente (variable de entorno, no siempre encendido) — dejarlo siempre activo en la VPS real genera ruido que dificulta encontrar el `ERROR`/`WARNING` real entre miles de líneas de detalle.

## Logging Estructurado en Python (`structlog` o `logging` + `extra`)

Un log en texto libre no se puede filtrar ni agregar. El proyecto usa `logging` estándar de Python — el mínimo cambio de valor es loguear con campos, no con strings interpolados:

```python
import logging
logger = logging.getLogger("odds_api")

# MAL — no se puede filtrar por order_id ni por monto sin parsear texto
logger.info(f"Pedido {order_id} creado por ${monto} para usuario {user_id}")

# BIEN — campos estructurados, buscables si algún día se agrega un agregador de logs
logger.info("pedido_creado", extra={"order_id": order_id, "monto": monto, "user_id": user_id})
```

Si el volumen de logs de producción crece lo suficiente para justificarlo, `structlog` da JSON real por default sin cambiar el patrón de arriba — evaluar solo si el `logging` estándar se vuelve limitante, no adoptarlo especulativamente hoy.

## Correlation ID — mínimo viable sin OpenTelemetry

Con un solo backend (no microservicios), un correlation ID simple por request alcanza para poder buscar "todos los logs de esta request específica" cuando algo falla — sin necesitar un colector OTel completo:

```python
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        correlation_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-request-id"] = correlation_id
        return response
```

Al loguear dentro de un router/servicio durante esa request, incluir `correlation_id` en `extra` — permite reconstruir la secuencia completa de eventos de una request específica (ej. "este job de análisis específico: qué pasó con la llamada a odds.py, el consenso, la publicación en Telegram") sin adivinar por timestamp aproximado.

## Qué NUNCA loguear (relevante para este proyecto en concreto)

- Contraseñas, tokens JWT completos, API keys de The Odds API/api-football/BSD API/Claude, `TELEGRAM_BOT_TOKEN`, `x-kairos-key` (ya marcadas como sensibles en `.claude/rules/secrets-never-revealed.md`).
- Número de tarjeta o cualquier dato de pago si se integra Webpay en el futuro — ni siquiera truncado sin verificar el estándar PCI aplicable.
- El payload completo de una request de usuario sin filtrar campos — si hace falta loguear el body para debug, usar una lista explícita de campos permitidos (`{k: v for k, v in body.items() if k in CAMPOS_SEGUROS}`), no el dict completo.

```python
# MAL — puede filtrar credenciales de correo, tokens, etc. sin darse cuenta
logger.debug(f"Payload recibido: {request_body}")

# BIEN — allowlist explícito
CAMPOS_SEGUROS_LOG = {"order_id", "producto_id", "cantidad", "estado"}
logger.debug("payload_recibido", extra={k: v for k, v in request_body.items() if k in CAMPOS_SEGUROS_LOG})
```

## Log-and-Throw — no loguear el mismo error dos veces

```python
# MAL — el mismo error aparece 2 veces en los logs, con distinto contexto cada vez, confunde el diagnóstico
def procesar_pago(pedido_id):
    try:
        return cobrar(pedido_id)
    except PagoError as e:
        logger.error(f"Pago falló: {e}")  # log #1
        raise

def checkout(request):
    try:
        procesar_pago(request.pedido_id)
    except PagoError as e:
        logger.error(f"Checkout falló: {e}")  # log #2 — mismo error
        return JSONResponse(status_code=500, ...)

# BIEN — loguear solo en el punto donde se decide qué hacer con el error (el boundary)
def procesar_pago(pedido_id):
    return cobrar(pedido_id)  # sin try/except, deja propagar

def checkout(request):
    try:
        procesar_pago(request.pedido_id)
    except PagoError as e:
        logger.error("checkout_fallo", extra={"pedido_id": request.pedido_id, "error": str(e)})
        return JSONResponse(status_code=500, ...)
```

## Ver también

- `la skill docker-vps-ops (no incluida en el repo publico)` — rotación de logs ya configurada a nivel de Docker Compose (`json-file`, `max-size`).
- `la skill metodologia-dev (no incluida en el repo publico)` → Bug-Fix Protocol — logs de debug taggeados temporalmente durante una investigación puntual.
- `.claude/skills/seguridad-secretos/SKILL.md` — scanner de secretos, útil para verificar que no se filtró una credencial a un log ya escrito.
