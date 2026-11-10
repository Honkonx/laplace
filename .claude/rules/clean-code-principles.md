# Clean Code Principles

> Adaptado 2026-09-04 de otro proyecto del usuario — contenido genérico de lenguaje, sin cambios
> de fondo (no tenía particularidades de ese proyecto que sacar).

## DRY (Don't Repeat Yourself)
- Extraer lógica duplicada a funciones, clases o constantes
- Un conocimiento debe tener una representación inequívoca
- Vigilar: bloques copy-pasteados, ramas if/else paralelas repitiendo el mismo patrón, validación similar repetida en distintos métodos

## KISS (Keep It Simple, Stupid)
- Preferir la solución más simple que funcione correctamente
- No agregar abstracciones antes de necesitarlas
- Una función debe hacer una sola cosa
- Más corto no siempre es más simple — legibilidad por sobre brevedad

## YAGNI (You Ain't Gonna Need It)
- No agregar funcionalidad hasta que realmente se necesite
- Preparar el código para hipotéticos futuros agrega complejidad accidental
- Eliminar código muerto, comentado, e imports sin usar

## Convenciones de nombres
- Clases/sustantivos: `PrediccionService`, `ConsensoEngine`
- Funciones/verbos: `guardar()`, `calcularConsenso()`, `esValido()`
- Funciones que devuelven boolean: prefijo `es`, `tiene`, `puede`, `debe`
- Evitar abreviaturas: `pred` → `prediccion`, `calc` → `calcular`

## Diseño de funciones
- Funciones pequeñas (típicamente < 20 líneas)
- Cada función hace una sola cosa (Single Responsibility a nivel función)
- Preferir 0-2 parámetros; extraer 3+ a un objeto/dataclass
- Evitar parámetros de salida; devolver valores en su lugar
- **Excepción real del proyecto:** código de coordinación de I/O externo con reintentos/timeout
  (ej. `datos.py` orquestando llamadas a múltiples fuentes en paralelo con `ThreadPoolExecutor`)
  legítimamente supera 20 líneas cuando dividirlo dispersaría pasos secuenciales fuertemente
  acoplados sin beneficio real de reuso — no forzar una extracción ahí solo por la métrica.

## Tamaño de archivos
- Si un archivo supera ~400 líneas, considerar dividirlo en varios — señal de que está haciendo
  más de una cosa (aplica tanto a scripts Python como a componentes de `frontend/` o pantallas
  Compose de `app-android/`)

## Comentarios
- Preferir código autoexplicativo sobre comentarios
- Usar comentarios solo para explicar el POR QUÉ, no el QUÉ
- Eliminar comentarios TODO cuando la tarea esté hecha
- El "por qué" debe citar evidencia real cuando exista (un bug real, una restricción del entorno
  ARM64/Termux, una decisión de una sesión anterior) en vez de quedar como explicación genérica
  sin fuente
