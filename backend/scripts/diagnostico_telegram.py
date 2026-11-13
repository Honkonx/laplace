"""diagnostico_telegram.py — comprueba contra el Telegram REAL que cada bot configurado puede recibir tus clics. Solo lectura: no envía mensajes ni consume actualizaciones ni gasta cuota.

  python backend/scripts/diagnostico_telegram.py

Para cada token configurado (`TELEGRAM_BOT_TOKEN` del bot deportivo y `AGENT_TELEGRAM_BOT_TOKEN` del agente) llama a `getMe`, `getWebhookInfo` y `getMyCommands` y avisa de lo que
impide recibir mensajes: token inválido, un webhook activo (con él, el modo de sondeo no recibe nada), actualizaciones acumuladas, el último error de entrega, o comandos del menú que ningún
manejador atiende. El token nunca se imprime.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.core.config import settings  # noqa: E402

API = "https://api.telegram.org"


def _llamar(token: str, metodo: str) -> dict:
    try:
        r = httpx.get(f"{API}/bot{token}/{metodo}", timeout=15)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": f"{type(exc).__name__}"}


def diagnosticar(nombre: str, token: str, esperados: set[str]) -> list[str]:
    if not token:
        return [f"[{nombre}] sin token configurado: ese bot no arranca"]
    avisos = []
    yo = _llamar(token, "getMe")
    if not yo.get("ok"):
        return [f"[{nombre}] token inválido o sin red ({yo.get('description')}): no puede recibir nada"]
    avisos.append(f"[{nombre}] conectado como @{yo['result'].get('username')} (id {yo['result'].get('id')})")
    hook = _llamar(token, "getWebhookInfo").get("result", {})
    if hook.get("url"):
        avisos.append(f"[{nombre}] PROBLEMA: hay un webhook activo ({hook['url'][:40]}…); con el sondeo (polling) el bot NO recibe mensajes mientras exista. Bórralo con deleteWebhook.")
    if hook.get("pending_update_count"):
        avisos.append(f"[{nombre}] hay {hook['pending_update_count']} actualización(es) pendiente(s) sin entregar")
    if hook.get("last_error_message"):
        avisos.append(f"[{nombre}] último error de entrega: {hook['last_error_message'][:80]}")
    menu = {c["command"] for c in _llamar(token, "getMyCommands").get("result", [])}
    if esperados:
        sin_manejador = sorted(menu - esperados)
        sin_menu = sorted(esperados - menu)
        if sin_manejador:
            avisos.append(f"[{nombre}] comandos del menú SIN manejador: {', '.join(sin_manejador)}")
        if sin_menu:
            avisos.append(f"[{nombre}] comandos con manejador que no están en el menú: {', '.join(sin_menu)}")
    return avisos


def _comandos_del_bot_deportivo() -> set[str]:
    import re

    fuente = (Path(__file__).resolve().parents[2] / "backend" / "api" / "bot" / "laplace_bot.py").read_text(encoding="utf-8")
    return set(re.findall(r'CommandHandler\("([a-z_]+)"', fuente))


def main() -> int:
    salida = []
    salida += diagnosticar("bot deportivo", settings.TELEGRAM_BOT_TOKEN, _comandos_del_bot_deportivo())
    salida += diagnosticar("agente", settings.AGENT_TELEGRAM_BOT_TOKEN, set())
    for linea in salida:
        print(linea)
    return 1 if any("PROBLEMA" in x or "inválido" in x for x in salida) else 0


if __name__ == "__main__":
    sys.exit(main())
