---
name: tech-debt
description: Dos modos ante deuda técnica — Modo Prevenir (mientras se hace un cambio, dejarlo en el estado final correcto, sin parches "por ahora") y Modo Triage (auditar deuda existente, categorizarla y priorizar un backlog de refactor). Usar al terminar un cambio que dejó un atajo/flag/alias temporal, o cuando se pida auditar qué refactorizar primero.
---

# tech-debt

Framework con dos modos, según el momento del ciclo de vida de la deuda técnica: **Prevenir** (durante el cambio) vs **Triage** (evaluando código ya existente).

**Fusionado de**: `claude-skills-main/tech-debt` (MIT License, ver `mios/listo/claude-skills-main/LICENSE`)

---

## Por qué esto es distinto de `calidad-codigo`

`calidad-codigo` es el gate de verificación al terminar cualquier tarea (nombres, tamaño de función, tests, docs). Esta skill es más específica: decide qué hacer con código que quedó **deliberadamente a medias** — un flag de modo, un alias de compatibilidad, un fallback "por si acaso" — durante un cambio en curso (Modo Prevenir), o evalúa deuda ya acumulada para decidir qué atacar primero (Modo Triage). Complementa la regla ya existente de `calidad-codigo`: "Nada especulativo. Sin parámetro opcional, flag de config, `enable_*`/`*_v2`/`*_mode` sin un caller real hoy (YAGNI)" — esta skill da el proceso completo alrededor de esa regla.

## Cuándo usar cada modo

**Modo Prevenir** — mientras se está escribiendo/editando código activamente:
- Se está por dejar un fallback, alias, flag de modo o wrapper "por si acaso" — verificar primero si tiene un caller real hoy.
- El usuario pidió explícitamente "hazlo bien, sin parches" o "sin dejar cosas a medias".
- Se está terminando una tarea que tocó un patrón viejo y sobra código del camino anterior.

**Modo Triage** — evaluando código existente, sin diff en curso:
- Se pide una auditoría de deuda técnica o "¿qué deberíamos refactorizar?".
- Hay que priorizar un backlog de mantenimiento — coincide con el propósito de `MEJORAS_PENDIENTES.md` en este proyecto (ver `general-rules.md`).
- La deuda se acumuló y nadie tiene claro qué atacar primero.

**Regla de cadena**: si un ítem triageado en Modo B se empieza a implementar, para ESE cambio puntual se pasa a Modo Prevenir.

**Cuándo NO usar ninguno de los dos**: un fix local obvio sin ángulo estructural (arreglarlo y seguir, sin invocar el framework), o nits de estilo/formato (eso lo atrapa `ruff`/el linter de frontend, no esta skill).

## Modo Prevenir — durante el cambio

Reescribir el cambio pensando en el **estado final que debería existir**, no en el camino que llevó al parche actual. Optimizar para el código que *debería* estar ahí; borrar rutas de compatibilidad muertas en vez de mejorarlas. Preferir un solo componente/flujo claro sobre un flag de modo que bifurca comportamiento.

Preguntas antes de dejar algo "por ahora":
- **¿Este fallback/alias/wrapper tiene un caller real hoy?** Si no, no se agrega — es exactamente lo que ya prohíbe `calidad-codigo` con YAGNI.
- **¿La ruta vieja sigue teniendo un uso legítimo, o solo la dejé por si algo se rompe?** Si es lo segundo, para eso está git — se puede recuperar del historial, no hace falta mantenerla viva en el código.
- **¿El cambio resuelve el problema de raíz, o solo agrega una bifurcación (`if modo_nuevo: ... else: ...`) encima del código viejo?** Un flag de modo que nunca se piensa quitar es deuda nueva, no una migración.

Ejemplo del patrón a evitar en este proyecto: durante la migración de `Product.stock` legacy a `stock_total`/`ProductStock` por sucursal (ver `project_stockbug_migracion_plan_debian_20260814` en memoria), dejar ambos campos leyéndose en paralelo "por si acaso" sin fecha de remoción es exactamente el tipo de deuda que este modo previene — si se necesita compatibilidad temporal real, documentar explícitamente cuándo se retira, no dejarlo indefinido.

## Modo Triage — auditando deuda existente

Identificar, categorizar y priorizar sistemáticamente. Para cada ítem de deuda encontrado, registrar:

- **Ubicación**: archivo/módulo concreto, no "el backend en general".
- **Categoría**: código muerto (nunca llamado), duplicación (misma lógica en 2+ lugares que debería ser una función), acoplamiento excesivo (un cambio ahí obliga a tocar 5 archivos más), flag de modo/compatibilidad sin fecha de retiro, dependencia desactualizada con CVE, test flaky o ausente en código crítico.
- **Impacto**: ¿frena cambios cercanos activamente, o es molestia cosmética?
- **Esfuerzo estimado**: chico (<1h), mediano (una sesión), grande (requiere coordinación/rama propia).

Priorizar por impacto/esfuerzo, no por antigüedad — un `TODO` de hace 2 años que nadie toca importa menos que un patrón que hoy mismo está causando bugs (ej. los flags `enable_*`/`*_v2` que `calidad-codigo` ya prohíbe agregar nuevos, pero pueden existir viejos sin auditar).

**Output**: lista priorizada con estimación de esfuerzo — alimenta `MEJORAS_PENDIENTES.md` (ya existente en este proyecto) en vez de crear un documento de backlog paralelo. No hace falta un veredicto único aprobar/rechazar todo el codebase — reportar por ítem.

## Checklist rápido

**Modo Prevenir** (antes de commitear un cambio con una ruta vieja/nueva conviviendo):
- [ ] ¿El fallback/alias/flag tiene un caller real HOY, no "podría necesitarse"?
- [ ] ¿Se borró la ruta muerta en vez de dejarla "por si acaso"?
- [ ] Si de verdad hace falta convivencia temporal, ¿está documentada con fecha/condición de retiro?

**Modo Triage** (al auditar):
- [ ] Cada ítem tiene ubicación concreta, categoría, impacto y esfuerzo
- [ ] Priorizado por impacto real, no por antigüedad
- [ ] Alimenta `MEJORAS_PENDIENTES.md`, no un doc nuevo separado
