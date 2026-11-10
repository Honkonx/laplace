"""Pruebas de bajo volumen para conocer salud y cuota de fuentes deportivas."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.models.metricas import EstadoFuenteDeportiva


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _probe(
    client: httpx.AsyncClient,
    fuente: str,
    url: str,
    headers: dict[str, str],
    configurada: bool,
    params: dict[str, str] | None = None,
) -> dict:
    if not configurada:
        return {"fuente": fuente, "configurada": False, "saludable": False, "detalle": "Sin credencial configurada"}
    inicio = time.perf_counter()
    try:
        respuesta = await client.get(url, headers=headers, params=params, timeout=15)
        return {"fuente": fuente, "configurada": True, "saludable": respuesta.status_code == 200, "status_http": respuesta.status_code, "latencia_ms": round((time.perf_counter() - inicio) * 1000, 1), "cuota_restante": respuesta.headers.get("x-requests-remaining") or respuesta.headers.get("x-ratelimit-requests-remaining"), "detalle": None if respuesta.status_code == 200 else f"HTTP {respuesta.status_code}"}
    except Exception as exc:
        return {"fuente": fuente, "configurada": True, "saludable": False, "detalle": type(exc).__name__, "latencia_ms": round((time.perf_counter() - inicio) * 1000, 1)}


async def verificar_fuentes(
    db: Session,
    client: httpx.AsyncClient,
    *,
    incluir_cuota_costosa: bool = False,
) -> list[dict]:
    """Registra salud sin exponer secretos ni gastar cuotas evitables.

    The Odds API consume créditos incluso para comprobar disponibilidad. Por eso solo se
    consulta desde una verificación manual explícita; el monitor programado conserva el último
    resultado conocido y mide cada día las fuentes gratuitas o de cuota diaria.
    """
    checks = [
        ("livescore6", "https://livescore6.p.rapidapi.com/matches/v2/list-by-date?Category=soccer&Date=" + datetime.now().strftime("%Y%m%d"), {"x-rapidapi-key": settings.LIVESCORE6_KEY, "x-rapidapi-host": "livescore6.p.rapidapi.com"}, bool(settings.LIVESCORE6_KEY)),
        ("api-football", "https://v3.football.api-sports.io/status", {"x-apisports-key": settings.SPORTS_API_KEY}, bool(settings.SPORTS_API_KEY)),
        ("football-data", "https://api.football-data.org/v4/competitions/PD/standings", {"X-Auth-Token": settings.FOOTBALL_DATA_KEY}, bool(settings.FOOTBALL_DATA_KEY)),
        ("bsd", "https://sports.bzzoiro.com/api/v2/events/?limit=1", {"Authorization": f"Token {settings.BSD_API_KEY}"}, bool(settings.BSD_API_KEY)),
    ]
    if incluir_cuota_costosa:
        checks.append((
            "the-odds-api",
            "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/",
            {},
            bool(settings.the_odds_api_key),
            {"regions": "eu", "markets": "h2h", "apiKey": settings.the_odds_api_key},
        ))
    resultados = [await _probe(client, *check) for check in checks]
    resultados.append(await _probe(
        client,
        "oddspapi",
        "https://api.oddspapi.io/v4/account",
        {},
        bool(settings.oddspapi_sharp_key),
        {"apiKey": settings.oddspapi_sharp_key},
    ))
    for item in resultados:
        db.merge(EstadoFuenteDeportiva(fuente=item["fuente"], configurada=int(item["configurada"]), saludable=int(item["saludable"]), status_http=item.get("status_http"), latencia_ms=item.get("latencia_ms"), cuota_restante=item.get("cuota_restante"), detalle=item.get("detalle"), verificado_en=_now()))
    db.commit()
    return resultados
