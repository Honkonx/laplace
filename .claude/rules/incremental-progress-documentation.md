# Documentar progreso EN VIVO, ítem por ítem — no diferir al final de la tanda

> Adaptado 2026-09-04 de otro proyecto del usuario, mismo principio general.

## Regla

Durante cualquier tarea que itere sobre una lista larga de ítems (módulos backend, pantallas de
la app, workflows n8n a migrar a FastAPI, skills a curar, etc.), actualizar el archivo de
progreso/checklist correspondiente **inmediatamente después de completar cada ítem** — no
acumular cambios para "documentar todo junto al final".

El commit real a git puede seguir siendo agrupado por lotes razonables (no exige un commit por
ítem). Pero el archivo de progreso en sí debe reflejar el estado real en todo momento.

## Por qué importa acá

Este proyecto va a pasar por una migración grande (n8n → FastAPI, posible SQLite → Postgres) en
varias rondas. Si una ronda se corta a mitad de la migración de un workflow, sin documentación
incremental no hay forma de saber desde una sesión nueva qué se migró y qué no — un archivo de
progreso creado al inicio pero no actualizado en vivo es peor que no tenerlo, porque miente sobre
el estado real.

## Cómo aplicarla

Antes de pasar al ítem N+1 de una lista larga (ej. el siguiente script a migrar a FastAPI), el
archivo de progreso ya debe reflejar el resultado real del ítem N.
