"""services/push_service.py — Notificaciones push vía Expo Push API.

ESTADO (2026-11-10, medido en el código): el ENVÍO funciona, pero el flujo no está completo. La app Android es nativa (Kotlin) y no tiene Firebase ni Expo, así que
ningún dispositivo obtiene un token de Expo; además `push_repo.guardar_push_token` no tiene ningún llamador. Resultado: `leer_push_tokens` devuelve una lista vacía y no sale ninguna
notificación. Para activarlo hace falta decidir el canal (Firebase Cloud Messaging o quitarlo), un proyecto de Firebase propio y un endpoint que registre el token del
dispositivo. Mientras tanto este módulo queda dormido a propósito: no falla, no envía y no inventa tokens.

Port de `send_push.py` (async, `httpx` en vez de `urllib.request`). El original
ya usaba Expo (`https://exp.host/--/api/v2/push/send`) — no BSD/OneSignal/FCM. Se preserva el
mismo batch-send (un solo POST con la lista de mensajes) y el mismo criterio de éxito/fallo
(`ticket.status == 'error'`).

Esto reemplaza WF-F (Push Sender) completo, y los puntos donde WF-B/WF-D/WF-E llamaban push con
`cmd: ''` roto (nunca se enviaba nada) — acá el envío es real.
"""
from __future__ import annotations

import logging

import httpx

from backend.api.db import push_repo
from sqlalchemy.orm import Session

log = logging.getLogger("laplace.push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# Deben coincidir EXACTAMENTE con los `NotificationChannel` reales que crea la app Android
# (fuente de verdad: app-android/app/src/main/java/com/laplace/mobile/service/NotificationService.kt
# — `NotificationHelper.createChannels`). Un channelId que no exista en el dispositivo hace que
# Android descarte la notificación en silencio (sin error visible acá ni del lado de Expo).
CANAL_PICKS = "laplace_picks"
CANAL_MATCHES = "laplace_matches"
CANAL_SYSTEM = "laplace_system"


async def _enviar_batch(client: httpx.AsyncClient, tokens: list[str], titulo: str, body: str,
                         data: dict | None = None, channel_id: str = CANAL_SYSTEM) -> dict:
    if not tokens:
        return {"enviados": 0, "fallos": 0, "error": "sin_tokens"}

    mensajes = [
        {
            "to": token,
            "title": titulo,
            "body": body,
            "sound": "default",
            "channelId": channel_id,
            "priority": "high",
            **({"data": data} if data else {}),
        }
        for token in tokens
    ]

    try:
        r = await client.post(
            EXPO_PUSH_URL,
            json=mensajes,
            headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
            timeout=15,
        )
        r.raise_for_status()
        resp_body = r.json()
    except Exception as exc:
        log.warning("Fallo enviando push a Expo (%d tokens)", len(tokens), exc_info=True)
        return {"enviados": 0, "fallos": len(mensajes), "error": str(exc)}

    tickets = resp_body.get("data")
    if not tickets:
        return {"enviados": len(mensajes), "fallos": 0, "detalle": resp_body}

    errores = sum(1 for t in tickets if t.get("status") == "error")
    return {"enviados": len(tickets) - errores, "fallos": errores, "detalle": tickets}


async def enviar_push(client: httpx.AsyncClient, token: str, titulo: str, body: str,
                       data: dict | None = None, channel_id: str = CANAL_SYSTEM) -> bool:
    """Envía a un único token Expo. Devuelve True si Expo lo aceptó sin error."""
    resultado = await _enviar_batch(client, [token], titulo, body, data, channel_id)
    return resultado["enviados"] > 0


async def enviar_push_a_device(client: httpx.AsyncClient, db: Session, device_id: str, titulo: str,
                                body: str, data: dict | None = None,
                                channel_id: str = CANAL_SYSTEM) -> dict:
    tokens = [t["expo_push_token"] for t in push_repo.leer_push_tokens(db, device_id) if t["expo_push_token"]]
    return await _enviar_batch(client, tokens, titulo, body, data, channel_id)


async def enviar_push_a_subscriptores_match(client: httpx.AsyncClient, db: Session, match_id: str,
                                             titulo: str, body: str, data: dict | None = None) -> dict:
    """Reemplaza el modo `match_id` de WF-E/WF-B: notifica a quienes pidieron un análisis
    de este partido desde la app. Va por el canal `laplace_matches` (resultado/estado de un
    partido puntual) — no `laplace_picks`, que es solo para los top picks del día."""
    tokens = [
        s["expo_push_token"]
        for s in push_repo.leer_match_subscriptores(db, match_id)
        if s["expo_push_token"]
    ]
    return await _enviar_batch(client, tokens, titulo, body, data, CANAL_MATCHES)


async def enviar_push_broadcast(client: httpx.AsyncClient, db: Session, titulo: str, body: str,
                                 data: dict | None = None) -> int:
    """Reemplaza el modo `broadcast=true` (WF-D `Enviar Push Top Picks`). Devuelve cuántos se
    enviaron OK. Va por el canal `laplace_picks` — es siempre un broadcast de top picks."""
    tokens = [t["expo_push_token"] for t in push_repo.leer_push_tokens(db) if t["expo_push_token"]]
    resultado = await _enviar_batch(client, tokens, titulo, body, data, CANAL_PICKS)
    return resultado["enviados"]
