"""
services/gateway_fuentes.py — Fuentes de fixtures de la cascada (BD, LiveScore6, BSD, api-football)
y los helpers de fechas/imágenes que comparten. Dividido de `gateway.py` sin cambiar comportamiento;
`gateway.py` reexporta estos nombres.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from backend.api.core.config import settings
from backend.api.core.exceptions import BSDAPIError, ExternalSourceError
from backend.api.db import partidos_repo
from backend.api.services._http_retry import CuotaApiFootballError, cuerpo_api_football, get_con_reintento_429
from backend.api.services.circuit_breaker import CircuitBreakerAbiertoError, obtener_circuit_breaker
from backend.api.services.fechas_bd import normalizar_fecha_bd
from backend.api.services.normalizacion import nombre_equipo_bsd

log = logging.getLogger("laplace.gateway")

LIVESCORE6_URL = "https://livescore6.p.rapidapi.com/matches/v2/list-by-date?Category=soccer&Date={fecha}"
BSD_BASE = "https://sports.bzzoiro.com/api/v2"
APIF_BASE = "https://v3.football.api-sports.io"

UTC_OFFSET = -4  # Chile


def _yyyymmdd_to_bd(fecha_raw: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD validando el calendario. Antes partía el texto en [:4]/[4:6]/[6:8]
    sin validar y, con una fecha ya ISO, producía claves basura (`2026--0-9-`) en `partidos_dia`
    (631 filas en la BD real, auditoría 2026-10-06). Ahora lanza `FechaBdInvalida`."""
    return normalizar_fecha_bd(fecha_raw)


def _timestamp_to_esd(ts: int) -> str:
    # La hora local se calcula sumando el desfase al instante, no restándolo solo a la hora: un partido a las 02:30 UTC es del día ANTERIOR en Chile
    # (antes quedaba con el día UTC y la hora local, p. ej. 2026-11-10 22:30 en vez de 2026-11-09 22:30; hallazgo de la prueba de cobertura 2026-11-10).
    local = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=UTC_OFFSET)
    return f"{local.year}{local.month:02d}{local.day:02d}{local.hour:02d}{local.minute:02d}"


def _timestamp_to_iso(ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        log.debug("gateway: timestamp inválido", exc_info=True)
        return ""


def _build_img(raw: str | None) -> str:
    if not raw or not isinstance(raw, str) or not raw.strip():
        return ""
    r = raw.strip()
    if r.startswith("http"):
        return r
    return "https://lsm-static-prod.livescore.com" + (r if r.startswith("/") else "/" + r)


def slug_de_liga(nombre: str, pais: str | None = None) -> str:
    """Slug de `partidos_dia.liga_slug`: nombre + país (`services/ligas_ident.py`); sin país, el de siempre. Lo reutilizan el guardado y el colector diario para no divergir."""
    from backend.api.services import ligas_ident

    return ligas_ident.slug_competicion(nombre, pais)


def _texto_pais(valor: object) -> str:
    """El país que declara una fuente puede venir como texto o como objeto con `name`."""
    if isinstance(valor, dict):
        valor = valor.get("name") or valor.get("country")
    return str(valor).strip() if isinstance(valor, str) and valor.strip() else ""


# ─── Fuentes de la cascada ────────────────────────────────────────────────────


def _bd_stages(db, fecha_raw: str) -> list[dict] | None:
    fecha_bd = _yyyymmdd_to_bd(fecha_raw)
    data = partidos_repo.leer_ligas_cache(db, fecha_bd)
    if not data.get("hit") or data.get("total", 0) == 0:
        return None
    stages = []
    for slug, liga_data in data.get("ligas", {}).items():
        partidos = liga_data.get("partidos", [])
        if not partidos:
            continue
        events = []
        for p in partidos:
            hora = p.get("hora_chile", "") or ""
            esd = fecha_raw + hora.replace(":", "") if hora else fecha_raw + "0000"
            events.append(
                {
                    "Eid": str(p.get("match_id", "")),
                    "Eps": "NS",
                    "T1": [{"Nm": p.get("local", "Local"), "Img": p.get("logo_local", "")}],
                    "T2": [{"Nm": p.get("visitante", "Visit"), "Img": p.get("logo_visitante", "")}],
                    "Esd": esd,
                    "kick_off_utc": p.get("kick_off_utc", ""),
                }
            )
        stages.append({"Snm": liga_data.get("nombre") or slug, "Cnm": liga_data.get("pais") or "", "liga_slug": slug, "Events": events})
    return stages or None


async def _livescore6_stages(client: httpx.AsyncClient, fecha_raw: str) -> list[dict] | None:
    if not settings.LIVESCORE6_KEY:
        raise ExternalSourceError("LIVESCORE6_KEY no configurada")
    url = LIVESCORE6_URL.format(fecha=fecha_raw)
    r = await get_con_reintento_429(
        client, url, log=log, fuente="livescore6",
        headers={"x-rapidapi-key": settings.LIVESCORE6_KEY, "x-rapidapi-host": "livescore6.p.rapidapi.com"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("Stages") or None


async def _bsd_stages(client: httpx.AsyncClient, fecha_raw: str) -> list[dict] | None:
    if not settings.BSD_API_KEY:
        raise BSDAPIError("BSD_API_KEY no configurada")
    breaker_bsd = obtener_circuit_breaker("bsd")
    if not breaker_bsd.permite_llamada():
        log.warning("fixtures fuente=bsd saltada — circuit breaker abierto (fallos consecutivos previos)")
        raise CircuitBreakerAbiertoError("bsd")
    fecha_bd = _yyyymmdd_to_bd(fecha_raw)
    url = f"{BSD_BASE}/events/?date_from={fecha_bd}&date_to={fecha_bd}&status=notstarted&limit=200"
    try:
        r = await get_con_reintento_429(
            client, url, log=log, fuente="bsd", headers={"Authorization": f"Token {settings.BSD_API_KEY}"}, timeout=15
        )
        r.raise_for_status()
    except Exception:
        breaker_bsd.registrar_fallo()
        raise
    breaker_bsd.registrar_exito()
    events_raw = r.json().get("results", [])
    if not events_raw:
        return None

    ligas_map: dict[tuple[str, str], list[dict]] = {}
    for ev in events_raw:
        liga_nombre = (ev.get("league") or {}).get("name") or (ev.get("competition") or {}).get("name") or "Otras"
        pais = _texto_pais((ev.get("league") or {}).get("country") or (ev.get("competition") or {}).get("country") or ev.get("country"))
        fecha_ev = ev.get("event_date") or ev.get("date") or ""
        esd = fecha_raw + "0000"
        ko_utc = fecha_ev[:19].replace(" ", "T") if fecha_ev else ""
        ligas_map.setdefault((liga_nombre, pais), []).append(
            {
                "Eid": str(ev.get("id", "")),
                "Eps": "NS",
                "T1": [{"Nm": nombre_equipo_bsd(ev.get("home_team")) or "Local"}],
                "T2": [{"Nm": nombre_equipo_bsd(ev.get("away_team")) or "Visit"}],
                "Esd": esd,
                "kick_off_utc": ko_utc,
            }
        )
    return [{"Snm": nombre, "Cnm": pais, "Events": evts} for (nombre, pais), evts in ligas_map.items()] or None


async def _apifootball_stages(client: httpx.AsyncClient, fecha_raw: str) -> list[dict] | None:
    if not settings.SPORTS_API_KEY:
        raise ExternalSourceError("SPORTS_API_KEY no configurada")
    breaker_apif = obtener_circuit_breaker("api-football")
    if not breaker_apif.permite_llamada():
        log.warning("fixtures fuente=api-football saltada — circuit breaker abierto (fallos consecutivos previos)")
        raise CircuitBreakerAbiertoError("api-football")
    fecha_bd = _yyyymmdd_to_bd(fecha_raw)
    url = f"{APIF_BASE}/fixtures?date={fecha_bd}&timezone=America%2FSantiago"
    try:
        r = await get_con_reintento_429(
            client, url, log=log, fuente="api-football", headers={"x-apisports-key": settings.SPORTS_API_KEY}, timeout=15
        )
        r.raise_for_status()
    except Exception:
        breaker_apif.registrar_fallo()
        raise
    try:
        cuerpo = cuerpo_api_football(r)  # un `errors` dentro de un 200 (plan sin acceso, cuota) es un fallo de la fuente, no «sin partidos»
    except CuotaApiFootballError:
        breaker_apif.registrar_fallo()
        raise
    breaker_apif.registrar_exito()
    fixtures = cuerpo.get("response", [])
    if not fixtures:
        return None

    ligas_map: dict[tuple[str, str], list[dict]] = {}
    for fx in fixtures:
        liga_nombre = (fx.get("league") or {}).get("name", "Otras")
        pais = _texto_pais((fx.get("league") or {}).get("country"))
        ts = (fx.get("fixture") or {}).get("timestamp", 0)
        ligas_map.setdefault((liga_nombre, pais), []).append(
            {
                "Eid": str((fx.get("fixture") or {}).get("id", "")),
                "Eps": "NS",
                "T1": [{"Nm": ((fx.get("teams") or {}).get("home") or {}).get("name", "Local")}],
                "T2": [{"Nm": ((fx.get("teams") or {}).get("away") or {}).get("name", "Visit")}],
                "Esd": _timestamp_to_esd(ts) if ts else fecha_raw + "0000",
                "kick_off_utc": _timestamp_to_iso(ts) if ts else "",
            }
        )
    return [{"Snm": nombre, "Cnm": pais, "Events": evts} for (nombre, pais), evts in ligas_map.items()] or None
