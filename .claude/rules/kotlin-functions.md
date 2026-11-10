# Kotlin Function Rules

> Traído 2026-09-04 desde otro proyecto del usuario — contenido genérico de lenguaje Kotlin.

## Member vs top-level vs extension functions

| Receiver | Tipo de función | Ejemplo |
|---|---|---|
| Clases propias | Member function | `class Prediccion { fun guardar() }` |
| Clases que no controlas, operación común | Extension function | `fun String.toFechaChile(): Date` |
| Utilidad sin receiver | Top-level function | `fun formatearFecha(fecha: Date): String` |
| Construcción de objeto compleja | Factory function | `fun Prediccion.crearDefault(): Prediccion` |

## Extension functions
- Preferir extensions para operaciones sobre tipos que no controlas
- Mantener extensions en archivos dedicados nombrados según el receiver: `Strings.kt`, `Flows.kt`
- No hacer shadow de miembros existentes con una extension

## Funciones de expresión única
- Usar sintaxis `=` cuando el cuerpo es una sola expresión: `fun double(x: Int): Int = x * 2`
- Omitir `return` y llaves para funciones de expresión única

## Parámetros default vs overloads
- Preferir valores default sobre overloading de funciones
- Usar named arguments en los call-sites cuando hay varios parámetros opcionales

## Funciones inline
- Usar `inline` solo para funciones que reciben lambdas, cuando el lambda ahorra allocation
- Marcar lambdas cross-inline con `noinline` cuando se guardan o pasan a funciones no-inline
- Marcar type parameters con `reified` solo en funciones inline
