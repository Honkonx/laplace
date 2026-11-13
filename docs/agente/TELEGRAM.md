# Bot de Telegram del agente

Usa `AGENT_TELEGRAM_BOT_TOKEN`, distinto del token del bot deportivo. Sin token, el resto del backend funciona igual. Los mensajes y sesiones se guardan con `user_id=telegram:<id>`.

## Acceso
El agente responde a **todos** los usuarios de Telegram; los privilegios son solo del administrador (`SPORTS_ADMIN_IDS`).
- `AGENT_TELEGRAM_BLOCKED_IDS`: ids vetados (tiene prioridad).
- `AGENT_TELEGRAM_ALLOWED_IDS`: si tiene valores, solo esos ids y los administradores.
- `AGENT_TELEGRAM_RATE_PER_MIN`: mensajes por minuto y por chat (10 por defecto; el administrador tiene un tope mayor).
- Topes de IA: `AGENT_IA_MAX_POR_MINUTO` y `AGENT_IA_MAX_POR_DIA`.

## Comandos
| Comando | Quién | Qué hace |
|---|---|---|
| `/start`, `/ayuda` | todos | Alcance y ayuda |
| `/ia <consulta>` | todos | Pide IA para una consulta dentro del alcance |
| `/estado` | todos | Últimas tareas y cantidad de memoria privada |
| `/partidos`, `/ligas`, `/top` | todos | Partidos, cobertura de ligas y Top Picks publicados |
| `/predecir A vs B` | todos | Pronóstico de un partido |
| `/panel`, `/fuentes` | admin | Panel del sistema y salud de las fuentes |
| `/resultados`, `/toppicks`, `/publicar confirmo` | admin | Acciones con efectos (la publicación pide confirmación explícita) |
| `/aprobaciones` | admin | Aprobaciones pendientes |
| `/decidir <id> aprobar` | admin | Aprueba; **cualquier otro valor, o ninguno, rechaza** |

## Sesiones y retomar (2026-11-11)
- Cada chat sigue **su última sesión** (`agent_sesiones.ultima_sesion`); antes cada mensaje abría una sesión nueva. `/nuevo` abre otra, `/sesiones` lista las últimas cinco con mensajes y `/retomar` (o `/retomar <número>`) reactiva una y resume lo último que se pidió y el último partido. En lenguaje natural: «sigue donde quedamos», «resume nuestra conversación anterior» (`agent.resume`).
- **IA en el texto libre:** `AGENT_TEXTO_LIBRE_IA` = `nadie` | `admin` (por defecto) | `todos`; con `todos` aplica el tope diario de IA por usuario (`AGENT_IA_MAX_POR_DIA`). `/ia <consulta>` sigue disponible para todos.

## Jerga, fechas y permisividad con IA
- El enrutador entiende apodos que designan a un solo equipo («el barça», «los merengues», «los citizens»; los ambiguos como «millonarios» no), fechas relativas («mañana», «pasado mañana», «ayer», «el sábado», «este finde») y giros como «quién se lleva…», «cómo pinta…», «a quién le das…», «quién la gana: A o B». Los partidos de otro día piden ESA fecha.
- `AGENT_PERMISIVIDAD` (por defecto `abierto`): `estricto` (la IA solo redacta pronósticos verificados), `normal` (además charla de fútbol con etiqueta «no verificada») y `abierto` (además cultura de fútbol general: VAR, reglas, árbitros, fichajes, historia). Ningún nivel deja a la IA dar probabilidades ni marcadores sin herramienta, ni conversar fuera del fútbol.

## Campeonatos
- «tabla de la Premier», «clasificación de LaLiga», «cómo van mis ligas», «resumen de la jornada»: la tabla propia (5 primeros), la última jornada y, **solo para planes pro/max y administradores**, la simulación (campeón, copa y descenso). Sin plan, un aviso de que la simulación es de pro y max. «La liga» a secas es ambigua y el agente no la adivina; una liga sin datos suficientes dice por qué.

## Límites por plan
- Equipos y ligas que se pueden seguir y partidos avisados cada 24 h: free 3, 1 y 3; pro 5, 3 y 6; max y administradores 10, 6 y 12 (`services/planes_seguimiento.py`). Son los mismos en Telegram, el agente, la web y la PWA.

## Defensa contra la inyección de instrucciones
- Todo texto que no escribió el sistema (el mensaje, los nombres de equipo, el historial y los resultados de las herramientas) pasa por `services/agent_saneo.py` antes de llegar a un prompt: sin marcadores de plantilla ni delimitadores, un nombre de equipo con una instrucción se rechaza y el texto externo va en un bloque rotulado como no confiable. Además el agente no tiene herramientas de escritura ni shell y las cifras se verifican en código.

## Perfil de usuario
- «estoy en Chile» (zona horaria), «responde corto» o «responde técnico» (estilo; también «más corto», «más técnico» y «como antes», que lo ajustan y lo revierten), «me interesan goles y ambos marcan» (mercados, hasta 4), «mi perfil» para verlo y «borra mi perfil». Solo con el consentimiento de siempre; en modo sin memoria no se guarda. `/olvidame` lo borra todo. Va a la IA como una línea de preferencias de estilo (nunca cambia cifras) y a los avisos como la zona horaria.
- En el perfil de un equipo el agente añade la **memoria del modelo**: rating, goles a favor y en contra, forma y partidos, de la competición donde más partidos tiene.

## Seguir equipos y ligas, y avisos
- Se dice con palabras: «sigue al Barcelona», «sigue la Premier League», «deja de seguir al Barcelona», «qué sigo», «acepto» (el consentimiento que ya pide el bot), «activa los avisos» y «apaga los avisos». Una frase con «?» es una pregunta y no se ejecuta.
- Es el mismo almacén que el bot de partidos (`bot_preferencias.equipos_favoritos` y `usuarios.favoritos_ligas`), con el id de Telegram como identidad común (`telegram:<id>` ↔ `<id>`): lo que se sigue en uno lo ve el otro. Límites del bot: 5 equipos y 3 ligas. En modo sin memoria no se guarda nada.
- Si el partido que se pide incluye un equipo seguido, el agente pronostica sin preguntar «bot o IA»; sin seguimiento o con «solo IA» todo sigue igual.
- Los avisos (`services/avisos_favoritos.py`) son trabajos deterministas, sin IA: el aviso previo trae hora, rival, liga y el pronóstico del modelo si lo cubre (si no, sale sin pronóstico); el aviso de resultado dice el final y si el modelo acertó. Un aviso por partido, de 08:00 a 22:00 (Chile), con tope de 6 partidos por usuario en 24 h. Salen por el bot del agente (`AVISOS_CANAL=agente`; si no tiene token, por el bot deportivo) y solo a quien los activó (`AVISOS_FAVORITOS`, encendido por defecto). El horario (`AVISOS_HORA_INICIO` a `AVISOS_HORA_FIN`) y el tope (`AVISOS_MAX_PARTIDOS_24H`) se ajustan; la hora y el horario siguen la zona horaria de cada persona si la guardó.
