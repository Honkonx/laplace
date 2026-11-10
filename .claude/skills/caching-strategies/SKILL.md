---
name: caching-strategies
description: Cache-aside, diseño de TTL, invalidación explícita (delete-on-write) y prevención de stampede — aplicable hoy al caché SQLite de Laplace (`stats_cache`, `leer_ligas_cache`) y a un futuro Redis si la Fase 2 lo introduce. Usar al agregar un nuevo tipo de dato cacheado, o al decidir el TTL de un dato que cambia con distinta frecuencia (fixture del día vs tabla de posiciones vs cuotas en vivo).
---

# caching-strategies

Laplace **ya tiene caché real** — `stats_cache` (TTL diferenciado por tipo de dato, ver
`db_query.py` v7.1: `leer_stats_cache`/`guardar_stats_cache`/`limpiar_stats_cache_expirado`) y
`leer_ligas_cache`/`guardar_ligas_cache` (caché lazy de partidos/ligas) — hoy implementado sobre
SQLite, no Redis. Esta skill aplica el mismo razonamiento (TTL, invalidación, stampede) sea el
backing store SQLite hoy o Redis si la Fase 2 lo introduce. Candidatos a cachear en el dominio de
Laplace: tabla de posiciones (cambia poco durante el día), resultados de búsqueda de equipos,
respuesta completa de un análisis ya calculado (`guardar_cache`/`verificar_cache`, ya existe) —
y **nunca** cuotas/odds en vivo cerca del kickoff sin un TTL muy corto, cambian rápido.

**Portado de**: `caching-strategies` (MIT License) del paquete `some_claude_skills-main` (`mios/listo/some_claude_skills-main/.claude/skills/caching-strategies/`). Ejemplos reescritos de TypeScript/`ioredis` a Python/`redis-py`, acorde al backend real (FastAPI síncrono, no Node).

---

## Qué NO cachear (antes de qué sí)

- **El límite de análisis/día del plan free** — un contador cacheado con TTL puede quedar desfasado
  bajo requests concurrentes de la misma cuenta (mismo problema de fondo que una lectura de stock
  obsoleta en un e-commerce: dos requests leen "todavía tengo cupo" antes de que el primero se
  confirme). Si se cachea, TTL ≤ unos segundos, y la verificación real antes de crear un job debe
  seguir leyendo la BD real (`verificar_limite`), no el valor cacheado.
- **Datos de plan/permisos del usuario** — si se agrega un cache del plan (free/pro) en el futuro,
  invalidación inmediata al cambiar de plan, nunca solo TTL (ver Anti-Patrón más abajo).

## Cache-Aside — el patrón por defecto

En lectura: revisa cache → si no está, lee BD → guarda en cache → devuelve. En escritura:
actualiza BD → **borra** la entrada del cache (no la sobrescribe — ver por qué abajo).

```python
import json
import redis

r = redis.Redis.from_url(settings.REDIS_URL)  # o el equivalente SQLite de stats_cache hoy
TTL_TABLA_POSICIONES_SEGUNDOS = 3600  # 1 hora — cambia poco durante el día

def get_tabla_posiciones_cacheada(liga_id: int) -> dict:
    key = f"tabla:{liga_id}"
    cached = r.get(key)
    if cached:
        return json.loads(cached)

    tabla = calcular_tabla_posiciones(liga_id)  # fuente real (api-football)
    r.setex(key, TTL_TABLA_POSICIONES_SEGUNDOS, json.dumps(tabla))
    return tabla

def invalidar_tabla_posiciones(liga_id: int):
    r.delete(f"tabla:{liga_id}")  # invalidar, NO sobrescribir — ej. tras un resultado nuevo
```

**Por qué borrar y no sobrescribir**: sobrescribir el cache justo después del `commit()` tiene una carrera posible — otro request pudo haber leído el valor viejo de la BD entre el commit y la escritura al cache, y si ese request escribe al cache DESPUÉS de esta actualización, deja el valor viejo cacheado. Borrar fuerza al siguiente lector a ir a la BD real, sin ambigüedad.

## TTL — presupuesto de staleness, no una "solución mágica"

| Dato | TTL sugerido | Por qué |
|---|---|---|
| Tabla de posiciones / fixtures del día | 30-60 min | Cambia poco durante el día |
| Resultados de búsqueda de equipos/ligas | 5-10 min | Balance entre frescura y no recalcular en cada tecla |
| Cuotas/odds en vivo cerca del kickoff | No cachear, o segundos | Ver sección "Qué NO cachear" arriba |
| Análisis completo ya calculado (`guardar_cache`) | TTL configurable por caso, ya existe | Ya gestionado hoy sin Redis, vía `input_hash` |
| Config/feature flags | Corto (60s) + invalidación explícita si cambia | Necesita propagarse rápido entre workers |

TTL nunca reemplaza invalidación explícita para datos donde el retraso de propagación es inaceptable (permisos, roles) — es un respaldo, no la estrategia principal.

## Prevención de Stampede (cache-miss simultáneo bajo carga)

Si el catálogo tiene tráfico suficiente para que muchas requests concurrentes puedan pegarle a la BD al mismo tiempo cuando expira una key popular (ej. la ficha de un producto muy buscado), usar un lock corto para que solo un worker recalcule mientras los demás esperan o devuelven el valor viejo:

```python
def get_con_lock(key: str, fetcher, ttl=3600):
    cached = r.get(key)
    if cached:
        return json.loads(cached)

    lock_key = f"lock:{key}"
    adquirido = r.set(lock_key, "1", nx=True, px=5000)  # lock de 5s

    if not adquirido:
        time.sleep(0.1)
        reintento = r.get(key)
        if reintento:
            return json.loads(reintento)
        raise CacheUnavailableError()

    try:
        valor = fetcher()
        r.setex(key, ttl, json.dumps(valor))
        return valor
    finally:
        r.delete(lock_key)
```

No implementar esto especulativamente sin tráfico real que lo justifique — con el volumen actual del proyecto, cache-aside simple con TTL alcanza.

## Anti-Patrón: TTL como única estrategia de invalidación

```python
# MAL — el usuario pierde el rol admin pero sigue accediendo a rutas admin hasta que expire el cache
r.setex(f"permisos:{user_id}", 300, json.dumps(permisos))

# BIEN — invalidación inmediata al cambiar el permiso
def revocar_admin(user_id: int):
    db_quitar_rol(user_id, "admin")
    r.delete(f"permisos:{user_id}")
```

## Anti-Patrón: Cache sin expiración

```python
# MAL — crece para siempre, garantiza datos viejos eventualmente
r.set(f"producto:{id}", json.dumps(data))

# BIEN — toda entrada tiene un límite de vida
r.setex(f"producto:{id}", 3600, json.dumps(data))
```

## Ver también

- `db_query.py` v7.1 — implementación real hoy de `stats_cache`/caché de ligas sobre SQLite.
- `.claude/rules/database-safety.md` — concurrencia y row-lock, mismo principio que aplica al
  límite de análisis/día bajo requests concurrentes.
- Si `frontend/` agrega un Service Worker/PWA en el futuro: ver
  `.claude/rules/deploy-safety.md` → nota de network-first para navegación, mismo principio de
  "no cachear lo que necesita estar fresco" aplicado del lado del cliente.
