# Seguridad de base de datos — migraciones y concurrencia

> Creada 2026-09-04, destilada (no copiada) de las reglas de otro proyecto del usuario que ya
> pasó por incidentes reales de este tipo con SQLAlchemy/Alembic/Postgres. Aplica hoy a SQLite y
> queda lista para cuando la Fase 2 introduzca SQLAlchemy/Alembic de verdad.

## Una migración creada no está terminada hasta aplicarse y verificarse en la app real

Cuando el proyecto adopte SQLAlchemy/Alembic (Fase 2): crear una migración (`alembic revision
--autogenerate`) no es el fin de la tarea. Hay que **aplicarla** (`alembic upgrade head`) en el
entorno real donde se está trabajando y **verificar el endpoint/pantalla real que usa lo nuevo**
— no solo que la suite de tests pase. Motivo real observado en otro proyecto: los tests arman el
esquema con `Base.metadata.create_all()` (lo declaran los modelos), mientras el entorno real se
construye con las migraciones aplicadas — la suite puede quedar 100% verde con la base de datos
real rota (columnas/índices que el modelo declara pero la migración nunca creó).

**Aplica ya, sin esperar a Fase 2:** cualquier cambio al esquema de `bot_deportivo.db` (SQLite,
vía `db_query.py`) debería verificarse corriendo la operación real contra la BD real, no solo
revisando que el `CREATE TABLE`/`ALTER TABLE` se vea bien.

## Migrar datos o esquema entre entornos — siempre requiere permiso explícito

Nunca migrar/sincronizar la base de datos de producción (Termux, `bot_deportivo.db`) hacia un
entorno local/dev, ni al revés, sin permiso explícito del usuario para ESA sincronización
puntual — aunque la tarea general lo sugiera. Esto aplica con más fuerza aún si en el futuro
existe una BD Postgres de staging/VPS separada de la de producción.

## Concurrencia — row-level lock en escrituras concurrentes

Para operaciones que pueden ejecutarse en paralelo sobre el mismo registro (ej. la cola de jobs
de WF-B, invalidación de `stats_cache`, contadores de análisis/día del plan free) — al migrar a
SQLAlchemy/Postgres, usar lock a nivel fila (`with_for_update()`) en la transacción que modifica
el registro, no confiar en que "no va a pasar" solo porque hoy es SQLite de un solo proceso.

## Scripts que borran o modifican datos en masa

Cualquier script (actual o futuro) que borre o modifique muchas filas a la vez —
`actualizar_resultados.py`, futuros scripts de limpieza de caché o de migración de datos — debe
llevar, en el código (no solo en el docstring):

1. Guarda de entorno: abortar o pedir confirmación extra si no está claro contra qué BD corre.
2. Confirmación explícita para operaciones irreversibles.
3. Indicar en el mensaje de ayuda cuántas filas afecta y si es idempotente (re-ejecutarlo dos
   veces no debería duplicar datos, salvo que se documente lo contrario).
