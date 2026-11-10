# Reglas globales de trabajo — Laplace (bot deportivo)

> Adaptado 2026-09-04 desde el patrón de reglas globales de otro proyecto propio del usuario
> (`<tu-carpeta>\kairos`). No es una copia — se tomó solo lo que aplica a este
> proyecto y a cómo el usuario trabaja en general, sin las particularidades de ese otro repo
> (Termux, rootfs, GitLab CI, etc.).

## Ejecutar órdenes en la misma ronda, no solo proponerlas

Cuando el mensaje del usuario ya es una orden explícita (auditar, mejorar, documentar, arreglar,
reestructurar, etc. — no una pregunta ni un pedido de opinión), y el trabajo produce un plan o
lista priorizada, **ese plan se ejecuta en la misma ronda** — no alcanza con presentarlo y
esperar una confirmación separada.

**Excepción real:** si el plan revela una decisión que solo el usuario puede tomar (ambigüedad
genuina, riesgo real de romper producción, elección de nombre/diseño con varias alternativas
válidas, o el propio mensaje pide explícitamente "dame tu opinión" sin orden de ejecutar) —
ahí sí corresponde parar y preguntar antes de ejecutar esa parte puntual.

**Cómo distinguir pregunta/opinión de una orden:** si el usuario pregunta "¿qué opinas de X?",
"¿tiene sentido Y?", eso NO autoriza a implementar X/Y — es una discusión, no una orden. Si el
usuario dice "hazlo", "impleméntalo", "sí, haz fase1", "arregla esto" — sí es una orden.

## Nunca eliminar documentación ni código sin instrucción explícita

Solo se fusiona, refactoriza, reorganiza, archiva o adapta (ver `nada-se-elimina` en AGENTS.md
§3.17, que sigue siendo la regla vigente del proyecto). Cuando algo queda obsoleto, se mueve a
`docs/archive/` o a `_archive/` en la raíz — nunca se borra directo, salvo artefactos
regenerables (`node_modules`, `__pycache__`, builds) que no son fuente de verdad de nada.

## Responder siempre en español

Texto de chat, resúmenes, explicaciones — siempre en español. El código, nombres de
variables/funciones y comentarios en scripts pueden seguir el idioma que ya use cada archivo
(el backend Python ya tiene comentarios en español; las skills genéricas traídas de otras
fuentes pueden tener contenido en inglés — no hace falta traducirlas).

## Verificar antes de asumir

No confiar en un resumen de conversación truncado, en memoria de una sesión anterior, o en lo
que "se recuerda" de un archivo — leer el estado real del archivo/carpeta antes de citarlo o
modificarlo. Ver también `multi-machine-continuity.md`.
