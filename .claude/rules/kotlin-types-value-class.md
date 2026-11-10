# Kotlin Inline Value Class Rules

> Traído 2026-09-04 desde otro proyecto del usuario — contenido genérico de lenguaje Kotlin.

## Cuándo usar @JvmInline value class

Usar value classes para envolver un valor único cuando:
- Type safety: distinguir valores semánticamente distintos del mismo tipo primitivo (ej.
  `MatchId` vs `UserId` vs `String` crudo)
- Domain modeling: dar significado a tipos primitivos sin overhead de allocation
- Contratos de API: forzar rangos/formatos válidos en el momento de construcción

```kotlin
@JvmInline
value class MatchId(val value: String) {
    init { require(value.isNotBlank()) { "MatchId no puede estar vacío" } }
}
```

## Cuándo NO usarlas
- El wrapper agrega ceremonia sin beneficio real de type-safety
- El valor necesita múltiples propiedades (usar `data class`)
- La clase participa en herencia (value classes no se pueden extender)

## Implicancias en estabilidad de Compose
- Value classes con backing primitivo/String son stable por default en Compose
- Preferir value class sobre data class para wrappers de una sola propiedad usados en estado de
  UI de Compose — reduce overhead de recomposición

## Reglas
- Value classes deben tener exactamente una propiedad
- La propiedad backing debe ser `val` (inmutable)
- Usar bloque `init` para validación
- Preferir value class sobre typealias cuando importa la type safety
