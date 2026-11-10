# Un secreto guardado NUNCA se vuelve a mostrar

> Adaptado 2026-09-04 de otro proyecto del usuario, generalizado como principio de diseño —
> aplica a cualquier credencial que Laplace llegue a guardar (API keys de proveedores de datos
> deportivos/IA, `x-kairos-key`, tokens de Telegram, credenciales de BD tras la migración a
> Postgres/MySQL).

## Regla

Una vez que un secreto (API key, token, contraseña de BD) queda guardado de forma persistente
(`.env`, tabla de configuración, secret manager), ninguna UI ni endpoint debe ofrecer una acción
que muestre/revele su contenido de nuevo — ni un endpoint de debug, ni un log en texto plano.
Las únicas acciones válidas sobre un secreto ya guardado son:

- **Usarlo** (referenciado internamente, nunca devuelto en una respuesta HTTP o log).
- **Reemplazarlo** (el campo de reemplazo empieza siempre vacío, nunca pre-rellenado).
- **Borrarlo**.

## Checklist al tocar código de credenciales

- Ninguna función que lea `.env`/config devuelve el valor crudo a una capa que lo muestre en
  pantalla o en la respuesta de un endpoint — salvo el propio proceso que lo USA internamente
  (ej. pasarlo como header a una API externa).
- Ningún log incluye el valor del secreto en texto plano.
- `.env` nunca se commitea (ya cubierto por `.gitignore` — verificar que se mantenga así tras
  cualquier cambio de `.gitignore`).
- Un campo de "reemplazar" en cualquier UI (app, web) arranca vacío.

## Aplicable directo hoy

`x-kairos-key` (header de auth de WF-A2), tokens de Telegram (`TELEGRAM_BOT_TOKEN`), API keys de
The Odds API / api-football / BSD API — todas viven en `.env`, nunca hardcodeadas (ya es regla
en AGENTS.md §3.16), y nunca deberían aparecer en una respuesta JSON al cliente ni en un log
persistente.
