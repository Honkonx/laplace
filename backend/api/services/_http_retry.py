"""services/_http_retry.py — Manejo compartido de `429 Too Many Requests` hacia APIs externas.

Auditoría real de esta sesión (leyendo gateway.py, odds_fetch.py, standings_fetch.py,
h2h_fetch.py, team_stats_fetch.py): ninguno de estos módulos leía `Retry-After` ni
implementaba backoff — un 429 se trataba exactamente igual que cualquier otro fallo de red
(`except Exception` genérico + log + caída inmediata al siguiente fallback de la cascada),
agotando cuota sin darle a la fuente ninguna chance de recuperarse antes del próximo intento.

Extraído a un módulo compartido (no reimplementado 5 veces) siguiendo DRY de
`.claude/rules/clean-code-principles.md` — mismo patrón que `_matematica.py`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import httpx

from backend.api.core.exceptions import ExternalSourceError

# Tope real de espera: no bloquear el request del usuario (que está esperando su análisis)
# más de esto por una sola fuente, aunque la API pida más vía `Retry-After`.
ESPERA_MAXIMA_SEGUNDOS = 5.0

# Sin header `Retry-After` en la respuesta 429, esperar este default corto antes del único
# reintento — mejor que reintentar inmediatamente contra una fuente que recién dijo "pará".
ESPERA_DEFAULT_SEGUNDOS = 1.0


# api-football (plan gratis) permite 10 peticiones por minuto además de 100 por día: medido el 2026-10-09, varias
# llamadas en paralelo recibían 429 aunque quedaba toda la cuota diaria. Ventana deslizante compartida por todos los
# módulos que la usan; la espera tiene tope para no bloquear al usuario (pasado el tope, se intenta igual).
LIMITE_API_FOOTBALL_POR_MINUTO = 9
ESPERA_MAXIMA_LIMITADOR_SEGUNDOS = 12.0
_ventana_api_football: deque[float] = deque()
_candado_limitador = asyncio.Lock()


async def _esperar_turno_api_football() -> None:
    limite_espera = time.monotonic() + ESPERA_MAXIMA_LIMITADOR_SEGUNDOS
    while True:
        async with _candado_limitador:
            ahora = time.monotonic()
            while _ventana_api_football and ahora - _ventana_api_football[0] >= 60.0:
                _ventana_api_football.popleft()
            if len(_ventana_api_football) < LIMITE_API_FOOTBALL_POR_MINUTO or ahora >= limite_espera:
                _ventana_api_football.append(ahora)
                return
            hasta_liberar = 60.0 - (ahora - _ventana_api_football[0])
        await asyncio.sleep(min(max(hasta_liberar, 0.05), 1.0))


class CuotaApiFootballError(ExternalSourceError):
    """api-football respondió HTTP 200 pero con `errors` (cuota diaria agotada, plan sin acceso, token inválido)."""


def cuerpo_api_football(respuesta: httpx.Response) -> dict:
    """JSON de api-football; un `errors` no vacío es un fallo, no 'sin resultados' (antes se leía como lista vacía)."""
    cuerpo = respuesta.json()
    errores = cuerpo.get("errors") if isinstance(cuerpo, dict) else None
    if errores:
        raise CuotaApiFootballError(f"api-football devolvió errors: {str(errores)[:200]}")
    return cuerpo


def _segundos_retry_after(valor: str | None) -> float:
    """Parsea el header `Retry-After` (formato en segundos — el que usan api-football, The
    Odds API y BSD; ninguna de las 3 devuelve el formato alternativo HTTP-date). Tope de
    `ESPERA_MAXIMA_SEGUNDOS`; sin header o valor no numérico, usa `ESPERA_DEFAULT_SEGUNDOS`."""
    if not valor:
        return ESPERA_DEFAULT_SEGUNDOS
    try:
        return max(0.0, min(float(valor), ESPERA_MAXIMA_SEGUNDOS))
    except (TypeError, ValueError):
        return ESPERA_DEFAULT_SEGUNDOS


async def get_con_reintento_429(
    client: httpx.AsyncClient, url: str, *, log: logging.Logger, fuente: str, **kwargs
) -> httpx.Response:
    """`client.get(url, **kwargs)` con UN reintento cuando la respuesta es 429.

    Respeta `Retry-After` de la respuesta (tope `ESPERA_MAXIMA_SEGUNDOS` para no bloquear el
    request del usuario indefinidamente). Si tras el reintento sigue en 429 (o cualquier otro
    error), devuelve la respuesta tal cual — el caller sigue llamando `raise_for_status()`
    como ya hacía, y la excepción resultante cae al siguiente fallback de la cascada normal
    (mismo comportamiento de siempre, solo que ahora con un intento de recuperación real antes
    de rendirse).

    Logea en `warning` (no `debug`) cuando una fuente devuelve 429 — visibilidad real en
    producción de que se está por agotar cuota (hallazgo real: varios `except` de estos
    módulos solo dejaban rastro en `debug`, invisible en logs de producción)."""
    if fuente == "api-football":
        await _esperar_turno_api_football()
    r = await client.get(url, **kwargs)
    if r.status_code == 429:
        espera = _segundos_retry_after(r.headers.get("Retry-After"))
        log.warning(
            "429 (rate limit) fuente=%s url=%s — reintentando en %.1fs", fuente, url, espera
        )
        if espera > 0:
            await asyncio.sleep(espera)
        r = await client.get(url, **kwargs)
        if r.status_code == 429:
            log.warning("429 (rate limit) fuente=%s persiste tras reintento — cae a fallback", fuente)
    return r
