---
name: debugging-sistematico
description: Framework de 4 fases para investigar la causa raíz de un bug antes de proponer un fix, más la técnica de rastreo hacia atrás por la call stack. Usar ante CUALQUIER bug, test que falla, o comportamiento inesperado — antes de proponer una solución, no después de la segunda vez que un fix no funciona.
---

# debugging-sistematico

Framework de 4 fases para investigar la causa raíz de un bug antes de tocar código, más la técnica de rastreo hacia atrás por la call stack para bugs que aparecen lejos de su origen real.

**Fusionado de**: `claude-skills-main/systematic-debugging`, `claude-skills-main/root-cause-tracing` (MIT License, ver `mios/listo/claude-skills-main/LICENSE`)

---

## Por qué existe esta skill en este proyecto

Varios bugs reales de este proyecto (stock obsoleto por lectura antes de lock, providers DTE nunca registrados, IDOR en `documents.py`, el bug de `String.toLocaleString()` no-op en el precio) tenían la causa raíz varios niveles arriba de donde el síntoma era visible. Un fix aplicado justo donde aparece el error casi siempre es un parche sobre el síntoma, no una solución — y en este proyecto ya se ha visto el patrón de "arreglar visualmente" y que el bug real siga ahí (ver `feedback_ui_repeated_complaint_structure.md` en memoria).

## La Ley de Hierro

```
NINGÚN FIX SIN INVESTIGACIÓN DE CAUSA RAÍZ PRIMERO
```

Si no se completó la Fase 1, no se puede proponer un fix. Esto aplica especialmente bajo presión de tiempo — adivinar y probar es más lento que investigar, no al revés (ver tabla de resultados abajo).

## Fase 1 — Investigación de causa raíz

1. **Leer el error completo.** Stack trace entero, línea y archivo exactos, no solo el mensaje de la primera línea.
2. **Reproducir de forma consistente.** ¿Se puede disparar siempre con los mismos pasos? Si no es reproducible, reunir más evidencia antes de adivinar — no proponer un fix para algo que no se puede confirmar que pasó.
3. **Revisar cambios recientes.** `git log`/`git diff` del área, dependencias nuevas, config, variables de entorno — qué cambió que podría causar esto.
4. **En sistemas de varios componentes** (backend → servicio externo → base de datos, frontend → API → BD): agregar logging temporal en cada frontera de componente ANTES de proponer un fix, correr una vez, y ver en qué capa se rompe realmente. Aplica directo a las integraciones de Laplace (The Odds API, api-football, BSD API, n8n/execSync hacia Python) — no asumir en qué lado está el problema sin verlo en logs.
5. **Rastrear el flujo de datos** cuando el error aparece lejos de su origen — ver la técnica completa abajo.

## Técnica de rastreo hacia atrás (root cause tracing)

Cuando un bug se manifiesta profundo en la ejecución (ej. un endpoint devuelve datos raros, pero el problema real está en cómo se armó una query tres funciones más arriba), el instinto de arreglar donde aparece el error es tratar el síntoma. En vez de eso:

1. **Observar el síntoma** tal cual se manifiesta (ej. "el stock mostrado no coincide con la BD").
2. **Encontrar la causa inmediata** — ¿qué línea de código produce directamente ese valor?
3. **Preguntar qué llamó a eso** — subir un nivel: ¿quién invocó esa función, con qué argumento?
4. **Seguir subiendo** hasta encontrar dónde se originó el valor incorrecto — no detenerse en el primer nivel que "parece sospechoso".
5. **Arreglar en el origen**, no en cada punto intermedio donde el síntoma se hace visible.

Cuando el rastreo manual no alcanza, instrumentar con logging temporal antes de la operación problemática (nunca solo después de que falla) — incluir contexto completo (valores de entrada, estado relevante, timestamp) y quitar el logging una vez resuelto.

## Fase 2 — Análisis de patrón

- Buscar un ejemplo que SÍ funciona en el mismo código (un endpoint similar, un componente similar) y comparar línea por línea qué es diferente.
- Si se está implementando un patrón ya usado en el proyecto (ej. `PublishJob`/cola de revisión, `with_for_update()` para stock), leer la implementación de referencia completa antes de adaptarla — no adivinar el patrón a medias.
- Listar TODAS las diferencias encontradas, por pequeñas que parezcan — no descartar una a priori como "eso no puede importar".

## Fase 3 — Hipótesis y prueba

1. Formular UNA hipótesis explícita: "Creo que X es la causa raíz porque Y" — por escrito, no vaga.
2. Probar con el cambio más chico posible que aísle esa hipótesis — una sola variable a la vez.
3. Si no funcionó: nueva hipótesis, no apilar un segundo cambio encima del primero sin confirmar que el primero no sirvió.
4. Si genuinamente no se entiende algo, decirlo explícitamente ("no entiendo por qué X pasa") en vez de simular certeza.

## Fase 4 — Implementación

1. Crear primero un caso de reproducción (test automatizado con pytest/Vitest si el proyecto ya tiene el runner ahí, o un script puntual) — antes de arreglar, no después.
2. Un solo fix por vez dirigido a la causa raíz identificada — nada de "ya que estoy aquí" (eso es un cambio aparte, ver regla de `calidad-codigo`: "refactor y fix de bug son dos cambios distintos").
3. Verificar: el test nuevo pasa, `pytest tests/ -v` completo no rompió nada más, el síntoma original desapareció de verdad (no solo "ya no tira error" — comparar contra el resultado esperado real).
4. **Si el fix no funcionó, contar los intentos.** Menos de 3: volver a Fase 1 con la información nueva. **3 o más fixes fallidos en el mismo síntoma es señal de un problema arquitectónico, no de que falta un cuarto intento** — cada fix revela un problema nuevo en otro lugar, o requiere "refactor grande" para aplicarse. Ahí para y se discute la arquitectura antes de seguir parchando.

## Señales de alarma — volver a Fase 1

Si aparece alguno de estos pensamientos, es momento de parar y volver a investigar, no de seguir:
- "Fix rápido ahora, investigo después"
- "Pruebo cambiar X a ver si funciona"
- "Se ve simple, no necesito el proceso completo" (los bugs simples también tienen causa raíz)
- "Es una emergencia, no hay tiempo para investigar" (el proceso sistemático es más rápido que adivinar y volver a fallar — ver tabla abajo)
- Ya van 2+ intentos fallidos y se está por probar un tercero sin cambiar de enfoque

## Por qué el proceso es más rápido, no más lento

De la fuente original (contexto genérico, no medido en este proyecto): enfoque sistemático ronda 15-30 minutos hasta el fix real; adivinar y probar ronda 2-3 horas de intentos fallidos, con una tasa de acierto al primer intento de ~95% vs ~40%. No es una cifra propia de este proyecto — se cita como razón para no saltarse el proceso "por apuro", que es exactamente cuando más tienta saltárselo.

## Integración con otras skills de este proyecto

- **`revision-tecnica`** (sección "Taxonomía de Errores") clasifica el error DESPUÉS de encontrar la causa raíz (transient/permanent/partial/fatal) — esta skill es el paso anterior: encontrar qué pasó antes de decidir cómo manejarlo.
- **`calidad-codigo`** exige tests que prueben comportamiento real y "refactor y fix son dos cambios distintos" — coherente con la Fase 4 de acá.
- **`testing-qa`** define el veredicto Ship/Ship-with-mitigation/Hold al cerrar una tarea — el veredicto se apoya en haber completado este proceso, no en "ya no tira error visible".
