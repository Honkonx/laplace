---
name: error-handling-patterns
description: Jerarquía de excepciones tipadas, retry con backoff/jitter, y circuit breaker para las integraciones externas de Laplace (The Odds API, api-football, BSD API, OddsPapi, Forebet, Claude API, Telegram Bot API). Complementa `calidad-codigo` (que ya prohíbe catches vacíos) y `backend-core` (mapeo de excepciones a HTTPException) — usar esta skill para diseñar CÓMO reintentar/clasificar errores de una fuente externa nueva o existente.
---

# error-handling-patterns

`calidad-codigo` prohíbe `except Exception: pass` y exige capturar tipos específicos;
`backend-core` define el mapeo `ValueError`/`KeyError`/`RuntimeError` → `HTTPException` (Fase 2).
Esta skill cubre lo que falta entre ambas: cómo diseñar la jerarquía de excepciones de un
servicio, y cuándo/cómo reintentar una llamada a una API externa — relevante para las fuentes de
datos que ya usa Laplace (`datos.py` orquesta llamadas a The Odds API, api-football, BSD API,
OddsPapi, Forebet) y para las integraciones directas (Claude API, Telegram Bot API).

**Portado de**: `error-handling-patterns` (MIT License) del paquete `some_claude_skills-main` (`mios/listo/some_claude_skills-main/.claude/skills/error-handling-patterns/`). Recortado a la mitad Python (el proyecto no tiene TypeScript en el backend) y a los patrones de retry/circuit breaker, que son la parte genuinamente nueva — la jerarquía de excepciones Python ya coincide en espíritu con lo que `backend-core` documenta.

---

## Clasificar el error antes de decidir qué hacer

Todo error de una integración externa se clasifica en dos ejes antes de decidir si reintentar:

| | **Transitorio** (puede resolverse solo) | **Permanente** (reintentar no ayuda) |
|---|---|---|
| **Accionable por el usuario** | Rate limit del proveedor (429) | Input inválido, token OAuth revocado |
| **Del sistema** | Timeout de red, proveedor caído (503) | Credenciales mal configuradas, schema cambiado por el proveedor |

Solo la columna "Transitorio" justifica un retry automático. Reintentar un error permanente (ej. un 401 por token expirado sin refrescar primero) solo demora el fallo y puede activar rate-limiting adicional del proveedor.

## Jerarquía de Excepciones por Servicio — patrón a seguir

Cada fuente externa (`odds.py`/The Odds API, `tabla_pos.py`/api-football, un futuro
`bsd_provider.py`) debería tener su propia excepción base, para que el caller pueda distinguir
"el proveedor está caído" de "el input es inválido" sin parsear strings de mensaje:

```python
class OddsAPIError(Exception):
    """Base para errores de la integración con The Odds API."""

class OddsAPITransientError(OddsAPIError):
    """Error temporal — reintentar puede funcionar (timeout, 503, rate limit)."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after

class OddsAPIPermanentError(OddsAPIError):
    """Error permanente — no reintentar (401 por API key inválida, 404, payload rechazado)."""

# En el punto de llamada
try:
    resultado = odds_client.get("/sports/soccer/odds", params)
except httpx.TimeoutException as e:
    raise OddsAPITransientError("timeout al pedir cuotas") from e
except httpx.HTTPStatusError as e:
    if e.response.status_code in (429, 502, 503):
        raise OddsAPITransientError("proveedor sobrecargado", retry_after=e.response.headers.get("Retry-After")) from e
    raise OddsAPIPermanentError(f"The Odds API rechazó el request: {e.response.text}") from e
```

`raise ... from e` (chaining) siempre al re-lanzar — preserva la traza original completa, necesario para diagnosticar sin adivinar la causa raíz (coherente con el Bug-Fix Protocol de `metodologia-dev`).

## Retry con Backoff Exponencial + Jitter

Nunca reintentar inmediatamente ni a intervalo fijo — un proveedor caído recibe una ráfaga sincronizada de reintentos de todos los workers a la vez (thundering herd) si no hay jitter:

```python
import random
import time

def con_retry(fn, max_intentos=3, base_segundos=1.0):
    for intento in range(max_intentos):
        try:
            return fn()
        except OddsAPITransientError as e:
            if intento == max_intentos - 1:
                raise  # se agotaron los intentos, propagar el error real
            espera = base_segundos * (2 ** intento) + random.uniform(0, 1)  # exponencial + jitter
            time.sleep(min(espera, e.retry_after or espera))
```

- Nunca reintentar `OddsAPIPermanentError` — propagar inmediatamente.
- Límite de intentos explícito (2-4 típico) — un retry sin límite ante un proveedor caído bloquea el worker indefinidamente.
- Si el proyecto adopta background jobs para estas integraciones (mencionado como pendiente en `backend-core` → Architecture Patterns), el retry con backoff vive naturalmente ahí en vez de bloquear un request HTTP síncrono.

## Circuit Breaker — cuándo vale la pena (probablemente no todavía)

Un circuit breaker evita seguir golpeando un proveedor que ya se sabe caído (abre el circuito tras N fallos consecutivos, deja de intentar por un tiempo, prueba de nuevo con una request de sondeo). Vale la pena solo si una integración externa se cae seguido y el retry simple ya no alcanza — no implementarlo especulativamente para las integraciones actuales sin evidencia de que el patrón simple de retry-con-límite no basta. Si se justifica en el futuro (ej. una fuente externa con caídas frecuentes documentadas), la forma mínima:

```python
class CircuitBreaker:
    def __init__(self, umbral_fallos=5, tiempo_abierto_s=60):
        self.fallos = 0
        self.abierto_desde: float | None = None
        self.umbral = umbral_fallos
        self.tiempo_abierto_s = tiempo_abierto_s

    def puede_intentar(self) -> bool:
        if self.abierto_desde is None:
            return True
        if time.monotonic() - self.abierto_desde > self.tiempo_abierto_s:
            return True  # ventana cumplida, permitir una request de sondeo
        return False

    def registrar_exito(self):
        self.fallos = 0
        self.abierto_desde = None

    def registrar_fallo(self):
        self.fallos += 1
        if self.fallos >= self.umbral:
            self.abierto_desde = time.monotonic()
```

## Anti-Patrón: Pokemon Exception Handling ("atraparlos a todos")

```python
# MAL — esconde errores de programación junto con errores esperables, silenciosamente
try:
    procesar_analisis(job)
except Exception as e:
    logger.error(f"algo falló: {e}")  # se pierde el tipo, no hay recovery real

# BIEN — maneja lo que sabe manejar, deja propagar el resto
try:
    procesar_analisis(job)
except LimiteAnalisisDiarioError as e:
    return JSONResponse(status_code=400, content={"detail": str(e)})
except OddsAPITransientError:
    encolar_reintento(job)
    return JSONResponse(status_code=202, content={"detail": "procesando, reintentando en background"})
# errores de programación (TypeError, AttributeError) NO se capturan — deben fallar ruidoso
```

Ya prohibido en principio por `calidad-codigo` ("No tragar errores"); esta skill agrega el motivo estructural: capturar `Exception` a secas trata un `TypeError` por un bug de código igual que un timeout de red esperable — el primero necesita arreglarse en el código, el segundo necesita un retry. Tratarlos igual esconde el bug real detrás de un log genérico.

## Errores string-typed — evitar parsear mensajes

```python
# MAL — el caller tiene que parsear el mensaje, se rompe con cualquier cambio de texto
raise Exception(f"RATE_LIMIT:{retry_after}")
# caller: if "RATE_LIMIT" in str(e): ...

# BIEN — tipado, refactor-safe
raise RateLimitError(retry_after_seconds=retry_after)
# caller: except RateLimitError as e: ... e.retry_after_seconds ...
```

## Ver también

- `la skill backend-core (no incluida en el repo publico)` → "Architecture Patterns" — mapeo de excepciones a `HTTPException` ya establecido, y providers intercambiables (Fase 2, ej. `odds_provider.py`) donde aplicar esta jerarquía.
- `la skill calidad-codigo (no incluida en el repo publico)` — regla ya vigente contra catches vacíos/genéricos.
- `la skill metodologia-dev (no incluida en el repo publico)` → Bug-Fix Protocol — diagnóstico riguroso antes de decidir cómo manejar un error recurrente.
