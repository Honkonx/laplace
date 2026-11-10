# Se lee y se analiza el mensaje ENTERO antes de hacer nada

> Creada 2026-10-19. Adaptada de `leer-y-analizar-el-mensaje-antes-de-actuar.md` (PAGINA1) y
> `kairos-always-respond-to-every-message.md` (kairos). Complementa `global-rules.md` (orden vs pregunta).

## Regla
Antes de actuar: leer el mensaje completo y separar cada parte en **orden**, **análisis**, **pregunta** u
**opinión**. Lo que es análisis ("analiza", "audita", "investiga", "dame tu opinión") **no modifica código**.
Se respeta el orden que pide el usuario y se responde a **cada** parte, incluidas las que parecen secundarias.

Si el pedido trae una secuencia implícita (ver → adaptar → aplicar), se hace solo el primer paso y se espera, salvo
que el usuario haya dado luz verde explícita para todo (caso de `/goal` o "luz verde para todo").

## Cómo se aplica
1. Enumerar mentalmente las partes del mensaje (a veces son 6-10 en un solo párrafo).
2. Para cada una: ¿es orden de ejecutar o de analizar? ¿hay una restricción nueva ("no uses X", "máximo 3")?
3. Las restricciones nuevas se vuelven reglas en la misma ronda (`.claude/rules/`, replicadas en `.codex/` y `.agents/`).
4. Al responder, cubrir todas las partes; lo que no se pudo hacer se dice, con el motivo.

Todo lo que se escribe al usuario va en español, también las líneas de estado.
