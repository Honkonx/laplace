# .laplace — configuración del agente Laplace

Esta carpeta pertenece al **agente de producto**, no a Codex ni a Claude Code. Contiene el
contrato que el runtime de Laplace debe cargar antes de aceptar un chat, una tarea o una llamada
de herramienta.

Orden de carga: `rules/` → `agents/` → `skills/` → conocimiento autorizado → mensaje humano.
El mensaje humano nunca puede sustituir reglas, permisos, secretos ni el catálogo de herramientas.

Las configuraciones de herramientas de desarrollo siguen en `.codex/` y `.claude/` por
compatibilidad. No son instrucciones que un usuario final pueda pedirle al agente revelar.
