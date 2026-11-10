# Kotlin Control Flow Rules

> Traído 2026-09-04 desde otro proyecto del usuario — contenido genérico de lenguaje Kotlin, sin
> cambios (no tenía nada específico de ese proyecto que adaptar). Complementa las reglas propias
> del proyecto en `kotlin-style` (`.claude/skills/kotlin-style/`).

## when expressions
- Preferir `when` sobre cadenas de `if/else if` para sealed classes, enums, o 3+ ramas
- Usar `when (val x = expr)` para capturar el subject en scope
- `when` exhaustivo sobre tipos sealed; agregar `else` solo si es semánticamente válido
- `when` sin subject para cadenas de condiciones booleanas: `when { cond1 -> ...; else -> ... }`

## Guard conditions y early returns
- Usar `return`/`throw` temprano al inicio de funciones para reducir anidamiento
- Preferir `if (condition) return` sobre `if (condition) { ... }` anidado
- Usar `require()` y `check()` para precondiciones en vez de `if (x == null) throw` manual

## Smart casts
- Preferir `val x = expr; if (x is Type) { x.method() }` sobre cast explícito `(expr as Type)`
- Usar `let` con null-check: `value?.let { nonNull -> ... }`

## Branching con nulables
- `?:` (Elvis) para defaults: `val name = nullableName ?: "default"`
- `?.` para safe calls: `value?.property`
- `!!` — **prohibido en este proyecto** (regla dura de AGENTS.md §3.11), usar `?.` + Elvis siempre

## Reemplazar cadenas if/else
- `when` para 3+ ramas
- `if` como expresión: `val x = if (cond) a else b`
- Extraer lógica de condición a funciones nombradas para legibilidad
