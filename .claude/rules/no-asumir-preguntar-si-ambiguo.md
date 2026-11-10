# No asumir estado del proyecto ni decisiones — preguntar si es ambiguo

> Creada 2026-09-04, corrección directa del usuario: asumí que el bot estaba en producción activa
> (basado en `AGENTS.md`/`ROADMAP_v2.md`, que dicen "Termux (producción) — Bot Telegram activo")
> y usé eso para justificar cautela extra (patrón strangler, migración incremental) en la
> propuesta de migración a FastAPI. El usuario corrigió: **el proyecto no está en producción** —
> la documentación existente sobre esto está desactualizada/incorrecta, no es fuente confiable
> por sí sola.

## Regla

Antes de actuar (o de recomendar un approach) basado en un hecho sobre el estado real del
proyecto que no se pueda verificar de forma independiente y objetiva (correr un comando, leer
código que confirme el hecho) — si la única fuente es un doc que podría estar desactualizado, o
una inferencia propia — **no asumir**. Si es ambiguo o no verificable con evidencia real, primero
preguntar al usuario en vez de proceder sobre una suposición.

Esto aplica en particular a:
- Estado operacional real (¿está en producción? ¿hay usuarios reales dependiendo de esto ahora?)
- Decisiones de arquitectura que el usuario podría tener ya definidas mentalmente aunque no las
  haya escrito (ej. "mejora el backend" sin especificar orden — preguntar si hay una prioridad)
- Cualquier cosa donde un doc del repo podría no reflejar la realidad actual (los docs se
  desactualizan; confirmar con el usuario o con evidencia de código/ejecución real antes de
  tratarlos como verdad absoluta)

## Cómo aplicarla

No preguntar por preguntar — solo cuando la ambigüedad es real y la respuesta cambiaría el
enfoque. Si algo se puede verificar leyendo código o corriendo un comando de solo lectura, hacer
eso primero en vez de preguntar. Preguntar es para lo que NO se puede confirmar así.

## Estado real corregido (2026-09-04)

El proyecto **no está en producción** — contradice lo que dice `DEPLOY_ENV.md`/`AGENTS.md`
("Termux — producción actual"). Esos docs quedan pendientes de corrección (no se tocan en la
ronda donde se escribió esta regla, por instrucción explícita del usuario de actualizar
documentación recién al final del trabajo de esa ronda). Hasta que se corrijan, no confiar en la
palabra "producción" de esos archivos sin volver a confirmar con el usuario.
