# Bot de Telegram y agente

## Bot principal (`TELEGRAM_BOT_TOKEN`)
| Comando | Qué hace |
|---|---|
| `/start`, `/ayuda`, `/mi_id` | bienvenida, ayuda y tu id de Telegram (para `SPORTS_ADMIN_IDS`) |
| `/juegos`, `/ligas` | elige día y liga, luego un partido, y recibe el análisis |
| `/hoy` | los partidos de hoy con pronóstico propio |
| `/top` | los Top Picks del día |
| `/stats` | rendimiento real del bot |
| `/encuesta`, `/favoritos` | votos y ligas favoritas |
| `/vincular`, `/misplanes` | vincular la cuenta web y ver el plan |
| `/generarcodigos`, `/listarcodigos`, `/gestionarusuario` | solo administrador |

Si un partido no tiene pronóstico propio, el mensaje dice por qué (máximo 3 motivos) y qué lo habilitaría, con la frecuencia de la liga como referencia.

## Agente (`AGENT_TELEGRAM_BOT_TOKEN`, puerto 9100)
Chat que consulta herramientas deportivas del backend, recuerda el contexto del usuario y deja trazadas sus acciones. Reglas: no inventa datos si faltan, no reemplaza al motor (las probabilidades siguen saliendo del backend) y las acciones sensibles requieren aprobación. Su definición y sus reglas están en `backend/agents/.laplace/`.
Se usa por la web (`/agente`), por la PWA y por su propio bot de Telegram si configuras el token.

## Canal y grupo
`TELEGRAM_CANAL_ID` (canal para los Top Picks) y `TELEGRAM_GRUPO_URL` son opcionales. Vacíos, el bot no publica en ningún canal y no muestra esos enlaces.
