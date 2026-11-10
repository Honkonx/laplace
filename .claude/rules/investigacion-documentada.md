# Toda investigación/análisis queda documentada en .md, basada en código real — nunca solo en la documentación existente

> Creada 2026-09-10, orden explícita del usuario: "añade esta regla todas las investigaciones,
> analisis etc deben quedar documenatdo en .md, ademas estas investigaciones y analisis que vas
> a ser no te bases en la documentacion, no te sesgues por la documentacion debe ser con base en
> el codigo y investigacion actual que haras". Formaliza como regla dura un patrón que ya se
> venía aplicando de facto en varias rondas de esta sesión (ver el registro de decisiones del autor (no publicado)
> 2026-09-09/2026-09-10) — a partir de acá es obligatorio, no opcional.

## Regla

Toda investigación, auditoría o análisis real de esta sesión (del código, del comportamiento en
producción, de opciones técnicas externas — librerías, métodos, servicios) debe:

1. **Basarse en el código y el comportamiento real, verificado en esta ronda** — nunca en lo que
   dice `docs/`/el registro de decisiones del autor (no publicado) sin confirmarlo de nuevo leyendo el archivo real o
   corriendo el comando/test real. La documentación existente puede estar desactualizada o
   reflejar una decisión que ya cambió — es un punto de partida para saber dónde mirar, nunca la
   fuente de verdad del hallazgo en sí. Mismo principio que ya cubre
   `.claude/rules/empirical-verification-before-fix.md` para fixes puntuales — esta regla lo
   extiende a cualquier investigación/análisis, no solo a la verificación de un fix ya decidido.
2. **Quedar documentada en un archivo `.md` real**, no solo en la respuesta de chat — un archivo
   nuevo en el lugar que corresponda según `.claude/rules/docs-folder-organization.md`
   (`docs/arquitectura/` para hallazgos transversales, `docs/backend/` para hallazgos específicos
   del motor/backend, etc.), o como parte de `el registro de sesiones del autor (no publicado)` de la ronda si el hallazgo
   es acotado y no amerita un documento propio — usar criterio real sobre el tamaño/alcance del
   hallazgo, no crear un archivo nuevo por cada detalle menor.
3. Citar evidencia real concreta (archivo:línea, resultado real de un comando/test, número real
   medido) — no una afirmación sin poder señalar de dónde sale.

## Por qué

Sin esto, cada investigación nueva corre el riesgo de repetir un hallazgo ya hecho (sin saberlo,
porque quedó solo en el chat de una sesión anterior) o de heredar un sesgo de una versión vieja
de la documentación que ya no refleja el código real — exactamente el patrón que motivó esta
regla: varias rondas de esta sesión encontraron hallazgos reales importantes (bugs de matching de
ligas, el bug crítico de `async with`, la causa raíz de la uniformidad de predicciones) que NO
estaban en ningún doc previo, precisamente por investigar el código real en vez de confiar en lo
que la documentación decía que pasaba.

## Cómo aplicarla

No aplica a preguntas sueltas de opinión sin trabajo real de investigación de por medio (ver
`global-rules.md` sobre distinguir pregunta/orden). Sí aplica a: auditorías de código, análisis
de causa raíz de un bug, investigación de librerías/métodos/servicios externos para una decisión
técnica, y cualquier ronda que produzca un hallazgo real que otra sesión futura necesitaría
conocer antes de tocar el mismo código o tomar una decisión similar.
