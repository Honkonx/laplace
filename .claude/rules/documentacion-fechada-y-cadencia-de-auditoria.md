# La documentación fechada no se corrige, y la auditoría tiene cadencia

> Creada 2026-10-19. Adaptada de `documentacion-fechada-y-cadencia-de-auditoria.md` (PAGINA1).
> Precisa `session-log-humano.md` y `docs-folder-organization.md`.

## Dos clases de documento, tratadas al revés
| | Describe el sistema de hoy | Es una foto con fecha |
|---|---|---|
| Dónde | `docs/arquitectura/`, `docs/backend/` (los de diseño vigente), `AGENTS.md`, `CLAUDE.md` | `docs/humano/`, `docs/backend/*_AAAA-MM-DD.md` (auditorías, evaluaciones, investigaciones), el registro de decisiones del autor (no publicado), `docs/archive/` |
| Si envejece | es un defecto: se corrige contra el código | es correcto: así era ese día |
| Qué se hace | actualizar in situ | no se toca el contenido; si algo cambió, va en un documento NUEVO |

Corregir una foto la falsifica. Lo único que sí se edita en una foto: una **ruta** que se movió (si no, el enlace
muere), un **secreto** (`session-log-humano.md`) o un dato **falso** descubierto después, con una nota fechada arriba.

Ejemplo vivo: `un documento archivado del autor (no publicado)` midió una fórmula de Poisson rota; no se
reescribió, se le antepuso una nota de corrección y el hallazgo corregido vive en documentos posteriores.

## Cadencia de auditoría
La documentación no se mantiene "al día" de forma continua: se audita (contra el código, no contra otros docs)
cuando hubo muchos cambios (una tanda grande, un área reescrita) o, si no, cada 3 meses. Entre auditorías solo es
obligatorio lo de siempre: el documento que toca un cambio se actualiza en la misma ronda
(`end-of-round-documentation.md`). **Próxima auditoría: 2027-01-19**, o antes si hay una tanda grande.
