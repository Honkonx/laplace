# Contrato app Android ↔ backend

La app habla con el backend por dos vías: el **gateway de la app** (una sola ruta con acciones) y las rutas REST de sesión y agente. La lista completa y vigente de rutas está en [`../backend/referencia/API.md`](../backend/referencia/API.md); este documento explica el gateway, que es el contrato que más fácil se rompe al cambiar el backend.

## Gateway de la app

- **Ruta:** `POST /api/v1/deportivo` (`routers/app_gateway.py`). La app usa el alias `POST /webhook/kairos-app`, que apunta al mismo manejador (nombre heredado del proyecto original, se conserva por compatibilidad con las apps ya compiladas).
- **Base:** la URL sale de `BuildConfig.LAPLACE_BASE_URL` (propiedad de Gradle `laplaceBaseUrl`; por defecto `http://10.0.2.2:9001/`, el backend local visto desde el emulador).
- **Autenticación:** cabecera `x-kairos-key` con el valor de `KAIROS_AUTH_SECRET`. La app solo la envía si `LAPLACE_AUTH_KEY` (propiedad `laplaceApiKey`) no está vacía; si no coincide, el backend responde 401 con `{"detail": {"type": "error", "title": "No autorizado", ...}}`.
- **Cuerpo:** `{ "action": "...", "params": {...}, "device_id": "...", "timestamp": ... }`. Los campos de más se toleran. Si `device_id` viene vacío o es el marcador `laplace`, se toma del `sub` del JWT cuando lo hay.
- **Respuesta:** `{ "type": "...", "title": "...", "data": {...} }`. `type` es `button_list`, `prediction`, `text`, `error`, `top_picks_carousel` o `partido_info`.
- **Errores HTTP:** acción desconocida → 404; `params` que no validan contra el esquema de la acción → 422; ambos con el cuerpo anidado en `detail`.

## Acciones
Los `params` de cada acción están declarados en `backend/api/schemas/app_gateway.py` (`ACCIONES_CON_PARAMS`).

| Acción | Devuelve (`type`) | Qué hace |
|---|---|---|
| `juegos` | `button_list` | Partidos del día o de una liga: lee primero la base de datos y, si no hay ninguno, la cascada de fuentes (BD → LiveScore6 → BSD → API-Football) |
| `prediccion` | `prediction` | Crea un análisis. Responde `pendiente` (título «Análisis iniciado») y lanza el trabajo en segundo plano; si ya hay uno activo responde `procesando`; si existe en caché responde `job_id: "cache"` con `from_cache: true` |
| `check_job` | `prediction` | Estado de un análisis (`job_id`, `status`, `match_id`, `plan`, `message`) y, al terminar, `content` con `pick`, `confianza`, `score`, `fuente` (`claude` o `python`), `texto_completo` y `desglose`. Un `job_id` desconocido devuelve `error` «Job no encontrado» |
| `top` | `top_picks_carousel` | Top Picks del día (`recomendaciones_dia`, hasta 5) y `fecha` |
| `stats` | `text` | Estadísticas del bot: `total`, `evaluados`, `aciertos`, `winrate`, `alta_winrate`, `media_winrate`, `consenso_winrate`, `por_fuente`, `periodo_dias` |
| `profile` | `text` | Perfil del dispositivo (incluye `creado_en`, `limite_ia_diario`) más `picks_total` y `racha_user` |
| `activar_codigo` | `text` / `error` | Activa un código de plan; devuelve `success`, `message`, `plan`, `activo_hasta`. Código inválido → `error` «Código inválido» |
| `registrar_usuario` | `text` / `error` | Registra el nombre (3-20 caracteres); un nombre ocupado devuelve `error` |
| `verificar_partido` | `partido_info` | Estado del partido: si ya hay análisis o resultado |
| `historial` | `button_list` | Historial del dispositivo (`limit` entre 1 y 500; fuera de rango → 422). Cada elemento trae `resultado`, `job_id`, `fuente` y `completado_en` |
| `guardar_partidos` | `text` | Guarda partidos en `partidos_dia` (`guardados`) |
| `ping` | `text` | `{ ok, ts, version: "app-gateway-py-1.0" }` |

El `plan` puede ser `free`, `pro`, `max` o `admin`. El límite diario de análisis lo aplica el backend al crear un trabajo (`error` «Límite diario alcanzado», con datos para ofrecer el plan superior).

## Polling de un análisis
La app consulta `check_job` cada 2 s, hasta 10 consultas (`PredictionViewModel`: `ESPERA_ENTRE_CONSULTAS_MS = 2000`, `MAX_CONSULTAS = 10`).

## Otras rutas que usa la app
`/api/v1/auth/registro` y `/api/v1/auth/login`, `/api/v1/prediccion-web`, y del agente `/agent/chat`, `/agent/capabilities`, `/agent/usage`, `/agent/feedback`, `/agent/tasks`, `/agent/memory` y `/agent/subagents` (todas con JWT). Contrato en [`../backend/referencia/API.md`](../backend/referencia/API.md).

## Notificaciones
El backend envía una notificación push de «Resultado disponible» al verificar un resultado (`services/resultados_scheduler.py`). No hay notificaciones de «análisis listo» ni de Top Picks, y hoy ningún flujo de la app registra el token del dispositivo (`push_repo.guardar_push_token` solo lo llaman las pruebas).

## Qué rompe a la app si cambia el backend
- El nombre de la ruta o del alias, y el nombre y valor de `x-kairos-key`.
- Los nombres de acción y las claves de `data` que se listaron arriba.
- Los valores de `status` de un análisis (`pendiente`, `procesando`, `listo` y `error`).
- El 401/404/422 con el cuerpo anidado en `detail`.
