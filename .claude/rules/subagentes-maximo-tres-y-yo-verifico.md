# Subagentes: máximo 3 a la vez, no anidan, modelo explícito y SIEMPRE verifico lo que entregan

> Creada 2026-10-09, orden explícita del usuario: "solo puedes lanzar 3 subagentes como máximo y esos
> subagentes no pueden lanzar subagentes, además de usar sonnet 5.5 o haiku 5.5 dependiendo de la
> tarea, además tú siempre debes verificar el trabajo de los subagentes". Adaptada de las reglas
> equivalentes de los proyectos Kairos (`agents-max-3-parallel-and-verify.md`) y PAGINA1
> (`subagentes-maximo-tres-y-yo-verifico.md`), con las lecciones reales de este repo.

## Los cinco límites

1. **Máximo 3 subagentes vivos a la vez.** Si una tarea tiene más partes, se encolan en tandas de 3;
   nunca se lanza un cuarto mientras haya tres activos. Un agente que reporta "stopped with background
   work of its own" cuenta como vivo hasta que termine.
2. **Un subagente NO lanza subagentes.** Todo prompt de subagente incluye, literal: "No lances otros
   agentes ni subagentes: trabaja tú directamente con tus propias herramientas. Si la tarea te queda
   grande, dilo y devuélvela." El tope de 3 es el total real de agentes vivos. (Refuerzo estructural:
   los tipos de `.claude/agents/` creados para esto no tienen la herramienta `Agent`.)
3. **El modelo se elige a propósito y se pasa en el parámetro `model`** (nunca se hereda por omisión):

   | Tarea | Modelo |
   |---|---|
   | Buscar, listar, leer, resumir, comparar, contar | **Haiku** |
   | Escribir código acotado, tests, documentación, auditar con criterio, investigar con fuentes | **Sonnet 5.5** |
   | Diseño, decisiones de arquitectura, lo ambiguo | **lo hace el asistente principal** |

4. **Lo que NO se delega** (lo hace el asistente principal): cambios en `consenso.py`, `pronostico.py`
   y la lógica de selección del pick (regla `evidencia-historica-antes-de-promover.md`), seguridad y
   autenticación, migraciones de BD, cualquier escritura sobre `bot_deportivo.db` real, manejo de
   secretos, y decidir qué se construye. Un subagente ejecuta; elegir es del principal.
5. **Todo encargo es específico.** Un subagente no ve la conversación: si el prompt no dice contra qué
   verificar, vuelve con una opinión en vez de un hecho. Plantilla:

   ```
   QUE          la tarea, en una frase
   DONDE        archivos o rutas concretas; alcance de archivos EXCLUSIVO (disjunto del de los demás)
   CONTRA QUE   cómo se comprueba que quedó bien (comando, test, medición)
   QUE NO       lo que no puede tocar (commit, push, docs/humano, .memory, secretos, la BD real)
   COMO VUELVE  qué trae: archivos, cifras, comandos ejecutados, hallazgos y lo que no pudo verificar
   ```

## Verificar no es leer el informe

Un informe de subagente es una **afirmación**, no un hecho. Antes de darlo por bueno ni reportarlo:

- **Correr yo los tests** y ver el número (no repetir el que dice el informe).
- **Leer el diff** (`git diff`, `git status`) y comprobar que NO tocó lo que no debía.
- **Contrastar los hallazgos clave** con el código o la BD real (leer el archivo:línea, correr la consulta).
- **Si llegó a una pantalla o a un APK, mirarlo** (captura real, compilación manual).
- Al reportar al usuario: separar **lo que verifiqué yo** de **lo que solo afirma el agente**.

Casos reales de este repo que justifican la regla: un agente afirmó que el venv "no tiene numpy" (sí lo
tiene); otro dejó el Compose a medias con un parámetro inexistente (solo apareció al compilar a mano); un
test "fallaba por el entorno" y en realidad dependía de una clave real del `.env`; dos agentes perdieron
resultados porque `pytest --basetemp=<carpeta>` borra esa carpeta.

## Higiene de la delegación

- Alcances de archivos disjuntos entre los agentes de una misma tanda; si dos necesitan el mismo
  archivo, se serializan.
- Cada agente usa un nombre NUEVO para `--basetemp` (dentro de `.qa/`) y escribe sus temporales en `.qa/`.
- Si un agente insiste en un método que el usuario prohibió (p. ej. MCP de Android Studio para compilar),
  se detiene (`TaskStop`) y el asistente principal hace esa parte.
- Los subagentes no hacen commit ni push, no crean `humanoN.md` ni tocan `.memory/`, y no imprimen secretos.

## Emparentadas

`empirical-verification-before-fix.md`, `post-round-verification.md`, `end-of-round-documentation.md`.
