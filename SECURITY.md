# Seguridad

## Cómo avisar de una vulnerabilidad
No abras un *issue* público con el detalle. Usa el aviso privado de GitHub: pestaña **Security** → **Report a vulnerability** de este repositorio. Incluye qué parte afecta, cómo reproducirlo y qué impacto tiene.

Se responde lo antes posible. Cuando haya arreglo se publica una versión y se agradece el aviso si lo deseas.

## Qué cubre
- El backend (`backend/`), el instalador (`install/`), la web y la PWA (`frontend/`, `pwa/`) y la app Android (`app-android/`).
- No cubre servicios de terceros (api-football, The Odds API, Telegram, proveedores de IA…): repórtalos a quien los opera.

## Reglas que ya sigue el proyecto
- **Las claves viven solo en `.env`** (permisos restringidos). Ninguna pantalla ni endpoint las vuelve a mostrar: solo se pueden reemplazar o borrar.
- **El navegador nunca recibe secretos.** La web usa JWT; la cabecera `x-kairos-key` es solo de la app Android compilada.
- **No hay secretos en el repositorio.** Si ves uno, trátalo como filtrado: avisa en privado y revócalo en el servicio que lo emitió.
- **El primer administrador se crea en tu máquina** (`instalar` o `laplace`); no hay cuenta por defecto.

## Si publicas tu propia instancia
Cambia `KAIROS_AUTH_SECRET` y `WEB_JWT_SECRET` (el instalador los genera), no expongas el puerto de la base de datos y revisa `docs/seguridad-y-datos.md`.
