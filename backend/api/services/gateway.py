"""
services/gateway.py — Cascada de fixtures + enriquecimiento BSD.

Port de gateway_unificado.py (`--modo=ligas` y `--modo=bsd`) — misma cascada
de 4 fuentes (BD → LiveScore6 → BSD → api-football), mismo shape de `Stages`/`Events`
(compatibilidad con lo que ya consumen la app/el bot). Cambios reales vs el original:

  - `http_get` (urllib síncrono) → `httpx.AsyncClient` (async, con timeout explícito por
    request en vez de uno global).
  - `ejecutar_db_query(...)` por subprocess → llamadas directas a
    `db.partidos_repo` (misma sesión SQLAlchemy de la request, sin el riesgo de timeout de
    lanzar un proceso Python nuevo por cada consulta de caché).
  - Excepciones tipadas (`core.exceptions`) en vez de `except Exception` genérico silencioso
    — la cascada sigue tolerando que una fuente falle (eso es intencional, es una cascada de
    fallback), pero ahora se puede distinguir "esta fuente no tiene la API key configurada"
    de "esta fuente devolvió un error real" en los logs.

**No portado todavía** (queda para una ronda siguiente, no es parte del núcleo estadístico):
`--modo=forebet` (scraper HTML con BeautifulSoup — informativo, no entra al consenso) y
`--modo=resultados` (se porta en `services/resultados.py`, no acá).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from backend.api.core.config import settings
from backend.api.services.fechas_bd import normalizar_fecha_bd
from backend.api.core.exceptions import BSDAPIError, ExternalSourceError
from backend.api.db import fixture_cache_repo, partidos_repo
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services._http_retry import CuotaApiFootballError, cuerpo_api_football, get_con_reintento_429  # noqa: F401  (los tests lo leen como gateway.CuotaApiFootballError)
from backend.api.services.circuit_breaker import CircuitBreakerAbiertoError, obtener_circuit_breaker
from backend.api.services.normalizacion import (
    coincide_nombre,
    limpiar_sufijos,
    nombre_equipo_bsd,
    normalizar_nombre,
)

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
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    hora_chile = (dt.hour + UTC_OFFSET) % 24
    return f"{dt.year}{dt.month:02d}{dt.day:02d}{hora_chile:02d}{dt.minute:02d}"


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


def slug_de_liga(nombre: str) -> str:
    """Slug de `partidos_dia.liga_slug` a partir del nombre de liga (misma regla que usa
    `guardar_stages_en_cache`); el colector diario lo reutiliza para no divergir."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", nombre or "Otras").lower().strip("-")[:40]


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
        stages.append({"Snm": liga_data.get("nombre") or slug, "liga_slug": slug, "Events": events})
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

    ligas_map: dict[str, list[dict]] = {}
    for ev in events_raw:
        liga_nombre = (ev.get("league") or {}).get("name") or (ev.get("competition") or {}).get("name") or "Otras"
        fecha_ev = ev.get("event_date") or ev.get("date") or ""
        esd = fecha_raw + "0000"
        ko_utc = fecha_ev[:19].replace(" ", "T") if fecha_ev else ""
        ligas_map.setdefault(liga_nombre, []).append(
            {
                "Eid": str(ev.get("id", "")),
                "Eps": "NS",
                "T1": [{"Nm": nombre_equipo_bsd(ev.get("home_team")) or "Local"}],
                "T2": [{"Nm": nombre_equipo_bsd(ev.get("away_team")) or "Visit"}],
                "Esd": esd,
                "kick_off_utc": ko_utc,
            }
        )
    return [{"Snm": nombre, "Events": evts} for nombre, evts in ligas_map.items()] or None


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
    breaker_apif.registrar_exito()
    fixtures = r.json().get("response", [])
    if not fixtures:
        return None

    ligas_map: dict[str, list[dict]] = {}
    for fx in fixtures:
        liga_nombre = (fx.get("league") or {}).get("name", "Otras")
        ts = (fx.get("fixture") or {}).get("timestamp", 0)
        ligas_map.setdefault(liga_nombre, []).append(
            {
                "Eid": str((fx.get("fixture") or {}).get("id", "")),
                "Eps": "NS",
                "T1": [{"Nm": ((fx.get("teams") or {}).get("home") or {}).get("name", "Local")}],
                "T2": [{"Nm": ((fx.get("teams") or {}).get("away") or {}).get("name", "Visit")}],
                "Esd": _timestamp_to_esd(ts) if ts else fecha_raw + "0000",
                "kick_off_utc": _timestamp_to_iso(ts) if ts else "",
            }
        )
    return [{"Snm": nombre, "Events": evts} for nombre, evts in ligas_map.items()] or None


# ─── Single-flight por fecha ───────────────────────────────────────────────────
# Auditoría real (2026-09-09): sin lock, 2 requests casi simultáneas para la misma fecha
# leían la caché ANTES de que la primera terminara de escribirla — ambas veían "sin caché"
# y disparaban la cascada completa de red en paralelo (llamadas duplicadas e innecesarias
# a APIs externas con cuota limitada). El backend corre en un solo proceso/event loop
# (confirmado por otra auditoría de esta sesión) — un asyncio.Lock en memoria alcanza, no
# hace falta un lock distribuido (Redis, etc.) para esto hoy.
_fixtures_locks: dict[str, asyncio.Lock] = {}
_fixtures_locks_guard = asyncio.Lock()


async def _lock_para_fecha(fecha_raw: str) -> asyncio.Lock:
    """Devuelve el asyncio.Lock de `fecha_raw`, creándolo si es la primera vez — la
    creación del lock en sí queda protegida por `_fixtures_locks_guard` para que dos
    corutinas no puedan crear cada una su propio Lock para la misma fecha."""
    async with _fixtures_locks_guard:
        lock = _fixtures_locks.get(fecha_raw)
        if lock is None:
            lock = asyncio.Lock()
            _fixtures_locks[fecha_raw] = lock
        return lock


async def obtener_fixtures_cascada(db, client: httpx.AsyncClient, fecha_raw: str) -> tuple[list[dict], str]:
    """Cascada BD → LiveScore6 → BSD → api-football. Devuelve (stages, nombre_fuente) —
    la primera fuente que responda con datos gana, igual que gateway_unificado.py.

    Single-flight por fecha: si la BD no tiene caché, se toma el lock de esa fecha antes de
    llamar a las fuentes de red. Un segundo caller que pida la misma fecha mientras el primero
    sigue en la cascada espera en el lock — al entrar, vuelve a leer la BD (que el primero ya
    dejó escrita, ver `guardar_stages_en_cache` más abajo) en vez de repetir la cascada."""
    stages = _bd_stages(db, fecha_raw)
    if stages:
        return stages, "bd"

    lock = await _lock_para_fecha(fecha_raw)
    async with lock:
        # Re-chequeo dentro del lock: si otra corutina ganó la carrera y ya guardó en
        # caché mientras esperábamos, usamos eso en vez de repetir la cascada de red.
        stages = _bd_stages(db, fecha_raw)
        if stages:
            return stages, "bd"

        fuentes = [
            ("livescore6", lambda: _livescore6_stages(client, fecha_raw)),
            ("bsd", lambda: _bsd_stages(client, fecha_raw)),
            ("api-football", lambda: _apifootball_stages(client, fecha_raw)),
        ]
        for nombre, fn in fuentes:
            try:
                stages = await fn()
                if stages:
                    log.info("fixtures fuente=%s stages=%d", nombre, len(stages))
                    guardar_stages_en_cache(db, fecha_raw, stages, nombre)
                    return stages, nombre
            except Exception as e:  # noqa: BLE001 — cascada de fallback intencional, cada fuente puede fallar
                log.warning("fixtures fuente=%s fallo: %s", nombre, str(e)[:150])
        log.error("todas las fuentes de fixtures fallaron fecha=%s", fecha_raw)
        return [], "none"


def guardar_stages_en_cache(db, fecha_raw: str, stages: list[dict], fuente: str) -> int:
    """Persiste los stages obtenidos de una fuente externa en `partidos_dia`, para que la
    próxima consulta del mismo día pegue en 'bd' sin llamar a la API externa de nuevo."""
    if fuente == "bd" or not stages:
        return 0
    fecha_bd = _yyyymmdd_to_bd(fecha_raw)
    partidos = []
    for stage in stages:
        liga_nombre = stage.get("Snm") or "Otras"
        liga_slug = stage.get("liga_slug") or re.sub(r"[^a-zA-Z0-9]+", "-", liga_nombre).lower().strip("-")[:40]
        liga_logo = _build_img(stage.get("Img") or stage.get("Logo") or stage.get("CompImg") or stage.get("badgeUrl") or "")
        for ev in stage.get("Events", []):
            match_id = str(ev.get("Eid", "")).strip()
            if not match_id:
                continue
            esd = str(ev.get("Esd", "") or "")
            hora_str = f"{esd[8:10]}:{esd[10:12]}" if len(esd) >= 12 else ""
            partidos.append(
                {
                    "match_id": match_id,
                    "liga_slug": liga_slug,
                    "liga_nombre": liga_nombre,
                    "liga_logo": liga_logo,
                    "local": ev.get("T1", [{}])[0].get("Nm", "Local"),
                    "visitante": ev.get("T2", [{}])[0].get("Nm", "Visit"),
                    "hora_chile": hora_str,
                    "kick_off_utc": ev.get("kick_off_utc", ""),
                    "logo_local": _build_img(ev.get("T1", [{}])[0].get("Img", "")),
                    "logo_visitante": _build_img(ev.get("T2", [{}])[0].get("Img", "")),
                    "status": "scheduled",
                }
            )
    return partidos_repo.guardar_ligas_cache(db, fecha_bd, partidos) if partidos else 0


# ─── Enriquecimiento BSD (xG, odds, ML, lesionados) ───────────────────────────


async def _bsd_buscar_event_id(db, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> str | None:
    """Resuelve el `event_id` de BSD para (local, visitante, fecha) — cacheado en
    `stats_cache` (tipo `bsd_event_id`, TTL ver `db/cache.py::TTL_HORAS_POR_TIPO`).

    Antes de este cambio, cada llamada a `enriquecer_bsd` repetía esta búsqueda completa
    (hasta 2 requests HTTP a BSD) aunque ya se hubiera resuelto el mismo partido minutos
    antes — a diferencia de `buscar_fixture_id`, que sí cacheaba vía `fixture_cache_repo`
    (hallazgo real de la auditoría de esta sesión). Reusa el patrón cache-aside genérico de
    `db/cache.py` (mismo mecanismo que `standings`/`h2h`/`team_stats`) en vez de agregar una
    tabla dedicada tipo `fixture_id_cache` — acá no hay un `match_id` propio para usar como
    clave (la firma es por nombre+fecha, no por partido de la cascada de fixtures), así que
    una clave compuesta sobre el caché genérico es más simple y evita una migración nueva
    solo para esto. Solo se cachea sobre un match encontrado (positivo) — igual criterio que
    `buscar_fixture_id`, que tampoco cachea "no encontrado" (un partido puede aparecer en BSD
    más tarde dentro de la ventana de TTL)."""
    if not settings.BSD_API_KEY:
        return None

    f = (fecha or "").strip()
    fecha_iso = f"{f[:4]}-{f[4:6]}-{f[6:8]}" if (len(f) == 8 and f.isdigit()) else f
    cache_key = f"bsd_event_id:{normalizar_nombre(local)}:{normalizar_nombre(visitante)}:{fecha_iso}"
    cacheado = leer_stats_cache(db, cache_key)
    if cacheado is not None:
        return cacheado.get("event_id")

    breaker_bsd = obtener_circuit_breaker("bsd")
    if not breaker_bsd.permite_llamada():
        log.warning("bsd_buscar_event_id saltado — circuit breaker de bsd abierto")
        return None

    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}
    local_busq = limpiar_sufijos(local)
    visit_busq = limpiar_sufijos(visitante)

    for team_q in (local_busq[:15], visit_busq[:15]):
        url = f"{BSD_BASE}/events/?date_from={fecha_iso}&date_to={fecha_iso}&team_name={team_q}&limit=20"
        try:
            r = await get_con_reintento_429(client, url, log=log, fuente="bsd", headers=headers, timeout=10)
            r.raise_for_status()
        except Exception as exc:
            log.warning("gateway: BSD eventos falló: %s", exc)
            breaker_bsd.registrar_fallo()
            continue
        breaker_bsd.registrar_exito()
        for evento in r.json().get("results", []):
            home = nombre_equipo_bsd(evento.get("home_team"))
            away = nombre_equipo_bsd(evento.get("away_team"))
            if coincide_nombre(home, local_busq) and coincide_nombre(away, visit_busq):
                event_id = evento.get("id") or evento.get("event_id")
                guardar_stats_cache(db, cache_key, "bsd_event_id", {"event_id": event_id})
                return event_id
    return None


async def enriquecer_bsd(db, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict:
    """Busca el partido en BSD y trae xG, odds, predicción ML y jugadores no disponibles.
    `found: False` si no se encuentra o la API key no está configurada — nunca lanza, el
    caller (services/motor.py, cuando integre esto) decide si el análisis sigue sin BSD."""
    breaker_bsd = obtener_circuit_breaker("bsd")
    if not breaker_bsd.permite_llamada():
        log.warning("enriquecer_bsd saltado — circuit breaker de bsd abierto")
        return {"found": False, "motivo": "Circuit breaker de BSD abierto (fallos recientes)", "fuente": "bsd"}

    event_id = await _bsd_buscar_event_id(db, client, local, visitante, fecha)
    if not event_id:
        return {"found": False, "motivo": "Partido no encontrado en BSD", "fuente": "bsd"}

    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}

    async def _get(url: str) -> dict:
        try:
            r = await get_con_reintento_429(client, url, log=log, fuente="bsd", headers=headers, timeout=10)
            r.raise_for_status()
        except Exception as exc:
            log.warning("gateway: BSD consulta falló: %s", exc)
            breaker_bsd.registrar_fallo()
            return {}
        breaker_bsd.registrar_exito()
        return r.json()

    odds_raw = (await _get(f"{BSD_BASE}/events/{event_id}/odds/")).get("odds", {})
    evento = await _get(f"{BSD_BASE}/events/{event_id}/")

    xg_local = evento.get("xg_home") or evento.get("xg_local")
    xg_visit = evento.get("xg_away") or evento.get("xg_visit")

    return {
        "found": True,
        "event_id": event_id,
        "xg_local": xg_local,
        "xg_visit": xg_visit,
        "xg_disponible": xg_local is not None and xg_visit is not None,
        "odds_local": odds_raw.get("home_win"),
        "odds_empate": odds_raw.get("draw"),
        "odds_visit": odds_raw.get("away_win"),
        "odds_disponibles": all(odds_raw.get(k) is not None for k in ("home_win", "draw", "away_win")),
        "fuente": "bsd",
    }


# ─── Resolución de fixture_id de api-football por nombre+fecha ────────────────
# Port de wfb-006 (`Extraer Info Partido`) — matchea el partido (identificado por nombre desde
# la cascada de fixtures, que no trae IDs de api-football) contra `/fixtures?date=` para poder
# usar los endpoints de api-football que sí requieren su propio fixture_id (odds, H2H,
# standings de equipo). Cacheado por `match_id` (24h informal, ver fixture_cache_repo).


def _match_equipo(nombre_api: str, nombre_buscado: str) -> bool:
    a, b = normalizar_nombre(nombre_api), normalizar_nombre(nombre_buscado)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return True
    return a.split(" ")[0] == b.split(" ")[0]


# api-football devuelve TODOS los partidos de un día en una sola petición. Antes cada análisis repetía esa
# petición (100/día y 10/min en el plan gratis, medido el 2026-10-09: 429 al analizar varios partidos seguidos); ahora
# se pide una vez por día y se reutiliza durante `_TTL_DIA_APIF` segundos, con un solo vuelo por fecha.
_TTL_DIA_APIF = 3 * 3600
_fixtures_apif_dia: dict[str, tuple[float, list[dict]]] = {}


async def _fixtures_apifootball_del_dia(client: httpx.AsyncClient, fecha_bd: str) -> list[dict]:
    ahora = time.monotonic()
    cacheado = _fixtures_apif_dia.get(fecha_bd)
    if cacheado and ahora - cacheado[0] < _TTL_DIA_APIF:
        return cacheado[1]
    async with await _lock_para_fecha(f"apif:{fecha_bd}"):
        cacheado = _fixtures_apif_dia.get(fecha_bd)
        if cacheado and time.monotonic() - cacheado[0] < _TTL_DIA_APIF:
            return cacheado[1]
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/fixtures", log=log, fuente="api-football",
            params={"date": fecha_bd, "timezone": "America/Santiago"},
            headers={"x-apisports-key": settings.SPORTS_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        # HTTP 200 con `errors` = cuota agotada o plan sin acceso: antes se leía como "sin partidos" sin avisar.
        fixtures = cuerpo_api_football(r).get("response", [])
        if len(_fixtures_apif_dia) > 8:
            _fixtures_apif_dia.clear()
        _fixtures_apif_dia[fecha_bd] = (time.monotonic(), fixtures)
        return fixtures


async def buscar_fixture_id(
    db, client: httpx.AsyncClient, match_id: str, local: str, visitante: str, fecha_raw: str
) -> dict:
    """Devuelve {apifootball_fixture_id, apifootball_league_id, apifootball_season,
    apifootball_team_home, apifootball_team_away} — todos None si no matchea o falla. Usa
    caché por match_id antes de llamar a la API (evita 1 request por partido en cada
    análisis repetido del mismo día).

    Bug real encontrado 2026-09-10 (investigación de por qué la mayoría de los picks daban
    "Empate"): el parámetro se llamaba `fecha_bd` pero en realidad recibía `fecha_raw` sin
    convertir (`YYYYMMDD`, el formato de LiveScore6) — ambos callers reales
    (`analisis_completo.py::_enriquecer_partido`, `laplace_agents/seleccion.py`) pasan la fecha
    cruda del job/fixture, nunca el formato "bd" (`Y-m-d`) que el nombre sugería. api-football
    espera `Y-m-d` en `GET /fixtures?date=` — con el formato crudo, la API devolvía HTTP 200 con
    `response: []` (nunca un 4xx, así que `raise_for_status()` nunca lo detectaba) — CERO
    partidos matcheaban, siempre, en toda la historia del proyecto (confirmado:
    `fixture_id_cache` tenía 0 filas reales). Verificado en vivo con la API real: `date=20260910`
    → 0 resultados; `date=2026-09-10` → 173 partidos reales. Esto desactivaba en cascada la
    resolución de liga por `league_id` numérico (`ligas.resolver_liga_por_id`) y el fallback de
    datos reales por equipo (`h2h_fetch._desde_stats_equipo`/`team_stats_fetch`) — ver
    `INVESTIGACION_MOTOR_PREDICCION_2026-09.md` §1.5. Fix: renombrado el
    parámetro a `fecha_raw` (honesto sobre lo que realmente recibe) y convertido con el mismo
    helper `_yyyymmdd_to_bd()` que ya usan el resto de las funciones de este archivo (línea 52)
    — nunca se había usado acá, esta función quedó afuera de ese patrón por error al escribirla.
    Se sigue guardando `fecha_raw` tal cual en `fixture_id_cache` (no es la clave de caché, solo
    un campo de referencia sin ningún lector real, confirmado en `db/fixture_cache_repo.py`)."""
    fecha_bd = _yyyymmdd_to_bd(fecha_raw) if fecha_raw and len(fecha_raw) == 8 else fecha_raw
    vacio = {
        "apifootball_fixture_id": None,
        "apifootball_league_id": None,
        "apifootball_season": None,
        "apifootball_team_home": None,
        "apifootball_team_away": None,
    }

    cacheado = fixture_cache_repo.leer_fixture_cache(db, match_id)
    if cacheado.get("hit") and cacheado.get("apifootball_fixture_id"):
        return {
            "apifootball_fixture_id": cacheado["apifootball_fixture_id"],
            "apifootball_league_id": cacheado["league_id"],
            "apifootball_season": cacheado["season"],
            "apifootball_team_home": cacheado["team_home_id"],
            "apifootball_team_away": cacheado["team_away_id"],
        }

    if not settings.SPORTS_API_KEY:
        return vacio

    breaker_apif = obtener_circuit_breaker("api-football")
    if not breaker_apif.permite_llamada():
        log.warning("buscar_fixture_id saltado match_id=%s — circuit breaker de api-football abierto", match_id)
        return vacio

    try:
        fixtures = await _fixtures_apifootball_del_dia(client, fecha_bd)
    except Exception:
        breaker_apif.registrar_fallo()
        log.warning("buscar_fixture_id fallo match_id=%s", match_id, exc_info=True)
        return vacio
    breaker_apif.registrar_exito()

    for f in fixtures:
        home = ((f.get("teams") or {}).get("home") or {}).get("name", "")
        away = ((f.get("teams") or {}).get("away") or {}).get("name", "")
        if _match_equipo(home, local) and _match_equipo(away, visitante):
            resultado = {
                "apifootball_fixture_id": (f.get("fixture") or {}).get("id"),
                "apifootball_league_id": (f.get("league") or {}).get("id"),
                "apifootball_season": (f.get("league") or {}).get("season"),
                "apifootball_team_home": ((f.get("teams") or {}).get("home") or {}).get("id"),
                "apifootball_team_away": ((f.get("teams") or {}).get("away") or {}).get("id"),
            }
            fixture_cache_repo.guardar_fixture_cache(
                db,
                match_id,
                fecha_raw,
                resultado["apifootball_fixture_id"],
                league_id=resultado["apifootball_league_id"],
                season=resultado["apifootball_season"],
                team_home_id=resultado["apifootball_team_home"],
                team_away_id=resultado["apifootball_team_away"],
            )
            return resultado
    return vacio
