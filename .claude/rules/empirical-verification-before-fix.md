# Verificación empírica real, no solo documentada — antes de dar un fix por bueno

> Adaptado 2026-09-04 de otro proyecto del usuario. El principio es genérico; los ejemplos
> originales eran de Android/Termux (no aplicables acá) — se reemplazan por el equivalente real
> de este proyecto.

## Regla

Cuando una solución a un bug depende de una práctica "conocida" (documentada en Stack Overflow,
en el README de una librería, o en experiencia previa) en vez de una causa raíz confirmada con
evidencia real de ESTE entorno específico (Windows/WSL/Termux, SQLite/Postgres real, n8n proot),
**no darla por buena solo porque está documentada en otro lado** — confirmarla empíricamente
antes: correr el script real, probar la query real, o descartar alternativas una por una hasta
encontrar la causa raíz real.

De la misma forma, cuando un script/endpoint termina una operación, **no confiar solo en el
exit code o en que no lanzó excepción** para declarar éxito — verificar la post-condición real
(¿el registro quedó en la BD con los campos esperados? ¿el job pasó a `status: listo`?) antes de
reportar un fix como resuelto.

## Ejemplo aplicable a este proyecto

Si en algún momento se reporta "el script ya no tira error", eso no confirma que la lógica sea
correcta — hay que confirmar la post-condición real: leer el registro en `bot_deportivo.db` (o
la tabla equivalente en Postgres tras la Fase 2), no solo el `{"ok": true}` que devuelve el
script.

## Cómo aplicarla en la práctica

- Antes de dar un fix de backend por bueno: ejecutar el script/endpoint real con datos reales (o
  de prueba) y leer la salida completa, no solo el código de salida.
- Antes de dar un fix de n8n por bueno: correr el workflow real, no solo revisar que el JSON
  "se ve bien".
- Antes de dar un fix de Kotlin/Compose por bueno: si hay forma de compilar/testear localmente,
  hacerlo — no asumir que "compila en la cabeza" es suficiente para cambios no triviales.
