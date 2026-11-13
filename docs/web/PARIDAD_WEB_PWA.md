# Paridad web ↔ PWA

Regla (`.claude/rules/prioridad-de-interfaces-telegram-web-pwa.md`): la web y la PWA son casi iguales; lo nuevo se hace en las dos en la misma ronda. Estado medido el 2026-11-12 comparando `frontend/` y `pwa/`.

## Igual en las dos
Entrar y registrarse (términos aceptados por la persona, códigos de activación, rol), inicio, simulador (acceso por plan, ligas disponibles, rango de puntos, fecha de los datos), historial y precisión, estado y transparencia, ruta inexistente. Mismas llamadas a la API, mismos mensajes.

## «Mis seguimientos» (2026-11-13)
Las dos tienen la pantalla: la web en «Seguidos» y la PWA en «Perfil → Mis seguimientos» (`/seguimientos`). Mismas llamadas (`/api/v1/agent/seguimientos`, `/seguimientos/consentimiento`, `/seguimientos/avisos` y `/perfil`), mismos textos, mismos topes por plan y el mismo mensaje del agente; solo cambian los estilos. Probada con `fetch` simulado (web 11 pruebas y PWA 11); **falta verla en pantalla con el backend real**.

## Solo en la web (brecha)
- **Administración** (`/admin`: usuarios, códigos, trabajos, conexiones y proveedores de IA, historial de planes, intentos de acceso).
- **Agente completo:** sesiones, memoria, aprobaciones, tareas, subagentes, capacidades, uso y feedback (la PWA tiene la conversación básica).
- Predicciones del agente por partido.

## Solo en la PWA
Calendario, Top Picks y Perfil con instalación y modo sin conexión (por diseño de una PWA, con barra inferior).

## Brecha que se cierra primero
El agente completo, porque Telegram y la web ya lo tienen; la administración puede quedar solo en la web (es de un administrador en su escritorio) salvo orden contraria.

## Ligas con país (2026-11-12)
El catálogo devuelve `league.name` con el país («Premier League (Inglaterra)») y `league.country`; la web y la PWA muestran `name` tal cual, así que cambian a la vez. Verificado en el backend y con pruebas de la API; no se miró en pantalla.
