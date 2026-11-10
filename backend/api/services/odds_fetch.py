"""services/odds_fetch.py — Cascada de obtención de cuotas 1X2 para un partido.

Port de los nodos `GET Odds` (wfb-010) y `Extraer Odds` (wfb-011) de WF-B. Cascada de 4
fuentes, en orden — la primera que resuelve las 3 cuotas (local/empate/visitante) gana:

  1. The Odds API (mejor cobertura Europa/MLS) — cacheada 2h por fixture_id y por liga; el resultado es la MEDIANA
     de todas las casas con 1X2 (descarta atípicas solo con 4+ casas).
  2. api-football `/odds` (fallback, mejor cobertura CONMEBOL).
  3. BSD API `/events/` + `/odds/` (fallback, sin límite de requests).
  4. api-football `/predictions` (último recurso — da un texto informativo, no cuotas reales).

Distinto de `services/odds.py`, que ANALIZA cuotas ya resueltas (calcula probabilidad
implícita, overround, etc.) — este módulo solo las CONSIGUE. El dict que devuelve
`obtener_odds_partido()` usa las mismas claves que espera `services/odds.py::analizar()` y
`services/pronostico.py::analizar()` (`odds_local`, `odds_empate`, `odds_visit`,
`odds_disponibles`).

Bug real corregido del original: el fallback de api-football (wfb-011) usaba una API key
hardcodeada `'PEGAR_AQUI_APIFOOTBALL_KEY'` que nunca se reemplazó — nunca funcionaba. Acá se
usa `settings.SPORTS_API_KEY`, la misma que ya usan el resto de las llamadas a api-football.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache, ttl_horas_odds_dinamico
from backend.api.services._http_retry import cuerpo_api_football, get_con_reintento_429
from backend.api.services.normalizacion import nombre_equipo_bsd, normalizar_nombre

log = logging.getLogger("laplace.odds_fetch")

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
APIF_BASE = "https://v3.football.api-sports.io"
RESERVA_CREDITOS_THE_ODDS = 20  # créditos mensuales que no se gastan en consultas a demanda
BSD_BASE = "https://sports.bzzoiro.com/api/v2"

# Alias de nombres de equipo — mismo diccionario que wfb-011 (Europa + CONMEBOL + resto).
# Sin esto, "Man City" (The Odds API a veces usa nombres cortos) no matchea contra
# "Manchester City" (nombre que trae la cascada de fixtures).
ALIAS: dict[str, list[str]] = {
    "manchester city": ["man city"],
    "manchester united": ["man united", "man utd"],
    "atletico madrid": ["atletico", "atletico de madrid"],
    "paris saint germain": ["psg", "paris sg", "paris saint-germain"],
    "internazionale": ["inter", "inter milan"],
    "red bull salzburg": ["salzburg", "rb salzburg"],
    "wolverhampton": ["wolves"],
    "tottenham hotspur": ["tottenham", "spurs"],
    "newcastle united": ["newcastle"],
    "brighton hove albion": ["brighton"],
    "west ham united": ["west ham"],
    "nottingham forest": ["nott m forest", "nottingham"],
    "athletic bilbao": ["athletic club"],
    "flamengo": ["clube de regatas do flamengo", "cr flamengo"],
    "fluminense": ["fluminense fc"],
    "atletico mineiro": ["atletico mg", "atletico-mg"],
    "boca juniors": ["boca", "ca boca juniors"],
    "river plate": ["river", "ca river plate"],
    "racing club": ["racing"],
    "estudiantes": ["estudiantes la plata"],
    "nacional": ["club nacional", "nacional de football"],
    "penarol": ["club atletico penarol"],
    "universidad de chile": ["la u", "u de chile"],
    "colo colo": ["cd colo-colo"],
}


def _expandir_alias(nombre: str) -> set[str]:
    norm = normalizar_nombre(nombre)
    resultado = {norm}
    palabras = norm.split(" ")
    if len(palabras) == 1 and len(palabras[0]) >= 4:
        resultado.add(palabras[0])
    for canon, variantes in ALIAS.items():
        todas_norm = {normalizar_nombre(v) for v in [canon, *variantes]}
        if any(
            v == norm or (len(norm) >= 6 and len(v) >= 6 and (v in norm or norm in v)) for v in todas_norm
        ):
            resultado |= todas_norm
    return resultado


def _coincide_equipos(nombre_a: str, nombre_b: str) -> bool:
    set_a, set_b = _expandir_alias(nombre_a), _expandir_alias(nombre_b)
    for a in set_a:
        for b in set_b:
            if a == b:
                return True
            if len(a) >= 6 and len(b) >= 6 and (a in b or b in a):
                return True
    return False


def _odds_vacias(fuente: str = "ninguna") -> dict:
    return {
        "odds_local": None,
        "odds_empate": None,
        "odds_visit": None,
        "odds_disponibles": False,
        "odds_source": fuente,
    }


# Costo real de una consulta a The Odds API: 1 crédito por mercado y por región. Se piden
# `h2h,totals` en región `eu` => 2 créditos por petición. Cuota mensual del plan ~500 créditos.
CREDITOS_POR_PETICION_THE_ODDS = 2

# Consenso entre casas: una casa se descarta como atípica si alguna de sus probabilidades
# implícitas (normalizadas) se aleja de la mediana más que este margen absoluto. Solo aplica con
# 4 o más casas — con menos, no hay masa suficiente para decidir quién es el atípico.
UMBRAL_OUTLIER_PROB = 0.06
MIN_CASAS_PARA_DESCARTAR_OUTLIERS = 4


def _clave_cache_odds(odds_key: str, fixture_id: str, local: str, fecha: str) -> str:
    # Bug real (auditoría 2026-09-09): sin fixture_id (cobertura de ligas real es baja), la
    # clave caía a `odds:{odds_key}:{local}` — dos partidos del mismo equipo local en fechas
    # distintas dentro de la ventana de 2h de TTL podían compartir la misma entrada de caché
    # y devolver las cuotas de OTRO partido. Se agrega `fecha` a la clave de fallback.
    return f"odds:{fixture_id}" if fixture_id else f"odds:{odds_key}:{local}:{fecha}"


def _clave_cache_odds_liga(odds_key: str) -> str:
    """Una sola respuesta de The Odds API trae TODOS los eventos de la liga en la ventana: se
    comparte entre los partidos de esa liga en vez de gastar una petición por partido."""
    return f"odds_liga:{odds_key}"


def _clave_consumo_odds(ahora: datetime | None = None) -> str:
    return f"consumo:the_odds_api:{(ahora or datetime.now(timezone.utc)).strftime('%Y-%m-%d')}"


def consumo_odds_hoy(db: Session) -> dict:
    """Peticiones/créditos que ESTE backend gastó hoy (UTC) en The Odds API, más el último
    `x-requests-remaining` visto en una respuesta real. Sirve de tope diario al job de refresco
    (`services/refresco_cuotas.py`) y de auditoría de cuota."""
    datos = leer_stats_cache(db, _clave_consumo_odds())
    return datos or {"peticiones": 0, "creditos": 0, "restante_api": None}


def _registrar_consumo_odds(db: Session, restante_api: str | None) -> None:
    try:
        actual = consumo_odds_hoy(db)
        nuevo = {
            "peticiones": int(actual.get("peticiones", 0)) + 1,
            "creditos": int(actual.get("creditos", 0)) + CREDITOS_POR_PETICION_THE_ODDS,
            "restante_api": restante_api if restante_api is not None else actual.get("restante_api"),
        }
        guardar_stats_cache(db, _clave_consumo_odds(), "consumo", nuevo, ttl_horas_override=48)
    except Exception:
        log.warning("No se pudo registrar el consumo de The Odds API", exc_info=True)


async def _pedir_eventos_the_odds_api(
    client: httpx.AsyncClient, db: Session, odds_key: str, kick_off_utc: str | None,
    claves_cache: list[str],
) -> list | None:
    """Única función que gasta cuota real de The Odds API: cuenta el consumo y guarda la
    respuesta bajo todas las `claves_cache` (por partido y por liga)."""
    restante = (consumo_odds_hoy(db) or {}).get("restante_api")
    try:
        if restante is not None and float(restante) <= RESERVA_CREDITOS_THE_ODDS:
            # Plan gratis ≈ 500 créditos al mes: el último tramo se reserva (la API respondió `x-requests-remaining`).
            log.warning("The Odds API: quedan %s créditos (reserva %s) — no se consulta", restante, RESERVA_CREDITOS_THE_ODDS)
            return None
    except (TypeError, ValueError):
        pass
    from_ = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_ = (datetime.now(timezone.utc) + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = await get_con_reintento_429(
            client, f"{ODDS_API_BASE}/sports/{odds_key}/odds/", log=log, fuente="the_odds_api",
            params={
                "apiKey": settings.the_odds_api_key,
                "regions": "eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "commenceTimeFrom": from_,
                "commenceTimeTo": to_,
            },
            timeout=15,
        )
        r.raise_for_status()
        eventos = r.json()
    except Exception as exc:
        # Sin `exc_info`: The Odds API recibe la clave como `?apiKey=` y el mensaje de `HTTPStatusError`
        # trae la URL completa, así que la traza imprimiría la API key en el log JSON (revisión de
        # seguridad 2026-10-07). Solo tipo de error y código HTTP.
        estado = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning("The Odds API fallo odds_key=%s error=%s http=%s", odds_key, type(exc).__name__, estado)
        return None
    _registrar_consumo_odds(db, r.headers.get("x-requests-remaining"))
    # TTL dinámico (2026-09-09): más corto cerca del kickoff real — las cuotas se mueven más
    # rápido a medida que se acerca el inicio. `None` -> TTL fijo normal de "odds".
    ttl = ttl_horas_odds_dinamico(kick_off_utc)
    for clave in claves_cache:
        guardar_stats_cache(db, clave, "odds", eventos, ttl_horas_override=ttl)
    return eventos


def _evento_de_partido(eventos: list | None, local: str, visitante: str) -> dict | None:
    for evento in eventos or []:
        if _coincide_equipos(evento.get("home_team", ""), local) and _coincide_equipos(
            evento.get("away_team", ""), visitante
        ):
            return evento
    return None


def _cuotas_por_casa(evento: dict) -> list[dict]:
    """Una tripleta 1X2 completa por cada casa que la ofrece (la misma respuesta ya las trae
    todas — leerlas no cuesta peticiones extra)."""
    home, away = evento.get("home_team", ""), evento.get("away_team", "")
    casas: list[dict] = []
    for bookmaker in evento.get("bookmakers", []):
        h2h = next((m for m in bookmaker.get("markets", []) if m.get("key") == "h2h"), None)
        if not h2h:
            continue
        outcomes = h2h.get("outcomes", [])
        oh = next((o.get("price") for o in outcomes if o.get("name") == home), 0)
        od = next((o.get("price") for o in outcomes if o.get("name") == "Draw"), 0)
        oa = next((o.get("price") for o in outcomes if o.get("name") == away), 0)
        if oh and od and oa and min(oh, od, oa) > 1.0:
            casas.append({
                "casa": bookmaker.get("title") or bookmaker.get("key") or "?",
                "local": float(oh), "empate": float(od), "visit": float(oa),
            })
    return casas


def _probs_normalizadas(casa: dict) -> tuple[float, float, float]:
    inversas = (1 / casa["local"], 1 / casa["empate"], 1 / casa["visit"])
    total = sum(inversas)
    return inversas[0] / total, inversas[1] / total, inversas[2] / total


def consenso_cuotas(casas: list[dict]) -> dict | None:
    """Consenso robusto entre casas: descarta las atípicas (probabilidad implícita normalizada
    a más de `UMBRAL_OUTLIER_PROB` de la mediana, solo con 4+ casas) y devuelve la MEDIANA de
    la cuota decimal de cada resultado. Con una sola casa equivale a usarla tal cual.

    Nota de integración (`services/odds.py`, dueño: agente B): el módulo `odds` de producción
    normaliza por proporción y el apilador se entrenó con Shin; este consenso solo elige qué
    cuotas crudas se le entregan, no cambia esa normalización."""
    if not casas:
        return None
    usadas = casas
    if len(casas) >= MIN_CASAS_PARA_DESCARTAR_OUTLIERS:
        probs = [_probs_normalizadas(c) for c in casas]
        medianas = [statistics.median(p[i] for p in probs) for i in range(3)]
        filtradas = [
            c for c, p in zip(casas, probs)
            if max(abs(p[i] - medianas[i]) for i in range(3)) <= UMBRAL_OUTLIER_PROB
        ]
        usadas = filtradas or casas
    return {
        "odds_local": round(statistics.median(c["local"] for c in usadas), 3),
        "odds_empate": round(statistics.median(c["empate"] for c in usadas), 3),
        "odds_visit": round(statistics.median(c["visit"] for c in usadas), 3),
        "odds_disponibles": True,
        "odds_source": "the_odds_api",
        "odds_consenso": "mediana" if len(usadas) > 1 else "casa_unica",
        "odds_n_casas": len(usadas),
        "odds_n_casas_descartadas": len(casas) - len(usadas),
        "odds_casas": sorted({c["casa"] for c in usadas}),
    }


def _dentro_de_la_ventana(kick_off_utc: str | None) -> bool:
    """True si el partido cae en la ventana que pide `_pedir_eventos_the_odds_api` (de -12 h a +36 h). Sin hora de inicio
    conocida se asume que sí (no se descarta por falta de dato)."""
    if not kick_off_utc:
        return True
    try:
        inicio = datetime.fromisoformat(str(kick_off_utc).replace("Z", "+00:00"))
    except ValueError:
        return True
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    ahora = datetime.now(timezone.utc)
    return ahora - timedelta(hours=12) <= inicio <= ahora + timedelta(hours=36)


async def _the_odds_api(
    client: httpx.AsyncClient, db: Session, local: str, visitante: str, odds_key: str, fixture_id: str, fecha: str,
    kick_off_utc: str | None = None,
) -> dict | None:
    if not settings.the_odds_api_key or not odds_key:
        return None
    cache_key = _clave_cache_odds(odds_key, fixture_id, local, fecha)
    evento = _evento_de_partido(leer_stats_cache(db, cache_key), local, visitante)
    if evento is None:
        # La respuesta de liga cacheada por otro partido sirve si ya contiene este evento;
        # si no lo contiene (ventana distinta, partido nuevo) se consulta la red.
        evento = _evento_de_partido(leer_stats_cache(db, _clave_cache_odds_liga(odds_key)), local, visitante)
    # Cada petición cuesta créditos (el plan gratis tiene ~500 al mes). No se gasta una si el partido no puede estar
    # en la ventana que se pide (de -12 h a +36 h): la respuesta no lo traería (auditoría 2026-10-09).
    if evento is None and _dentro_de_la_ventana(kick_off_utc):
        eventos = await _pedir_eventos_the_odds_api(
            client, db, odds_key, kick_off_utc, [cache_key, _clave_cache_odds_liga(odds_key)]
        )
        evento = _evento_de_partido(eventos, local, visitante)
    return consenso_cuotas(_cuotas_por_casa(evento)) if evento else None


async def refrescar_odds_liga(
    client: httpx.AsyncClient, db: Session, odds_key: str, kick_off_utc: str | None = None
) -> bool:
    """Una petición real que deja cacheados los eventos de toda la liga (`odds_liga:*`). La usa
    el job de refresco; gasta cuota, así que el caller es quien aplica el tope diario."""
    if not settings.the_odds_api_key or not odds_key:
        return False
    eventos = await _pedir_eventos_the_odds_api(client, db, odds_key, kick_off_utc, [_clave_cache_odds_liga(odds_key)])
    return eventos is not None


async def _apifootball_odds(client: httpx.AsyncClient, fixture_id: str) -> dict | None:
    if not settings.SPORTS_API_KEY or not fixture_id:
        return None
    try:
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/odds", log=log, fuente="api-football",
            params={"fixture": fixture_id},
            headers={"x-apisports-key": settings.SPORTS_API_KEY}, timeout=10,
        )
        r.raise_for_status()
        bookmakers = (cuerpo_api_football(r).get("response") or [{}])[0].get("bookmakers", [])
    except Exception:
        log.warning("api-football odds fallo fixture_id=%s", fixture_id, exc_info=True)
        return None

    for bk in bookmakers:
        mercado = next((b for b in bk.get("bets", []) if b.get("name") == "Match Winner"), None)
        if not mercado:
            continue
        valores = mercado.get("values", [])
        oh = next((float(v["odd"]) for v in valores if v.get("value") == "Home"), 0)
        od = next((float(v["odd"]) for v in valores if v.get("value") == "Draw"), 0)
        oa = next((float(v["odd"]) for v in valores if v.get("value") == "Away"), 0)
        if oh and od and oa:
            return {
                "odds_local": oh, "odds_empate": od, "odds_visit": oa,
                "odds_disponibles": True, "odds_source": "apifootball",
            }
    return None


def _fecha_iso_bsd(fecha: str) -> str:
    f = (fecha or "").strip()
    if len(f) == 8 and f.isdigit():
        return f"{f[:4]}-{f[4:6]}-{f[6:8]}"
    return f


def _evento_bsd_del_partido(resultados: list[dict], local: str, visitante: str, fecha: str) -> dict | None:
    """Primer evento de BSD cuyo local Y visitante coinciden y cuya fecha (si la trae) es `fecha`.
    La búsqueda es por `team_name` del local: el primer resultado puede ser OTRO partido del
    mismo equipo (bug hallado en la auditoría 2026-10-06), por eso se verifican ambos equipos."""
    fecha_iso = _fecha_iso_bsd(fecha)
    for evento in resultados:
        if not (
            _coincide_equipos(nombre_equipo_bsd(evento.get("home_team")), local)
            and _coincide_equipos(nombre_equipo_bsd(evento.get("away_team")), visitante)
        ):
            continue
        fecha_evento = str(evento.get("event_date") or evento.get("date") or "")[:10]
        if fecha_evento and fecha_iso and fecha_evento != fecha_iso:
            continue
        return evento
    return None


async def _bsd_odds(client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    if not settings.BSD_API_KEY:
        return None
    fecha_iso = _fecha_iso_bsd(fecha)
    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}
    local_corto = (local or "")[:15]
    try:
        r = await get_con_reintento_429(
            client, f"{BSD_BASE}/events/", log=log, fuente="bsd",
            params={"team_name": local_corto, "date_from": fecha_iso, "date_to": fecha_iso, "limit": 10},
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        resultados = r.json().get("results", [])
    except Exception:
        log.warning("BSD eventos fallo local=%s", local, exc_info=True)
        return None

    evento = _evento_bsd_del_partido(resultados, local, visitante, fecha_iso)
    event_id = evento.get("id") if evento else None
    if not event_id:
        return None
    try:
        r = await get_con_reintento_429(
            client, f"{BSD_BASE}/events/{event_id}/odds/", log=log, fuente="bsd", headers=headers, timeout=8
        )
        r.raise_for_status()
        o = r.json().get("odds", {})
    except Exception:
        log.warning("BSD odds fallo event_id=%s", event_id, exc_info=True)
        return None

    if o.get("home_win") and o.get("draw") and o.get("away_win"):
        return {
            "odds_local": float(o["home_win"]), "odds_empate": float(o["draw"]),
            "odds_visit": float(o["away_win"]), "odds_disponibles": True, "odds_source": "bsd",
        }
    return None


async def _apifootball_predictions(client: httpx.AsyncClient, fixture_id: str) -> dict | None:
    """Último recurso — no da cuotas numéricas, solo un texto informativo (`odds_info`).
    Devuelve `odds_disponibles=False` siempre (no hay cuota real que analizar)."""
    if not settings.SPORTS_API_KEY or not fixture_id:
        return None
    try:
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/predictions", log=log, fuente="api-football",
            params={"fixture": fixture_id},
            headers={"x-apisports-key": settings.SPORTS_API_KEY}, timeout=10,
        )
        r.raise_for_status()
        pred = (r.json().get("response") or [{}])[0].get("predictions")
    except Exception:
        log.warning("api-football predictions fallo fixture_id=%s", fixture_id, exc_info=True)
        return None

    if not pred:
        return None
    pct = pred.get("percent", {})
    ganador = (pred.get("winner") or {}).get("name", "?")
    texto = f"Sin odds exactas. Predicción api-football: {pct.get('home','?')} | Empate {pct.get('draw','?')} | {pct.get('away','?')} | Favorito: {ganador}"
    return {**_odds_vacias("predictions"), "odds_info_externo": texto}


async def obtener_odds_partido(
    client: httpx.AsyncClient, db: Session, local: str, visitante: str,
    odds_key: str | None, fixture_id: str | None, fecha: str,
    kick_off_utc: str | None = None,
) -> dict:
    """Cascada completa. Siempre devuelve un dict con las claves `odds_local/odds_empate/
    odds_visit/odds_disponibles/odds_source` — `odds_disponibles=False` si las 4 fuentes
    fallan (igual que WF-B, que en ese caso deja el análisis seguir sin cuotas).

    `kick_off_utc` (2026-09-09, opcional): cuando se conoce, acorta el TTL de la caché de odds
    si el partido arranca en menos de 2h — ver `db/cache.py::ttl_horas_odds_dinamico`."""
    if odds_key:
        resultado = await _the_odds_api(client, db, local, visitante, odds_key, fixture_id or "", fecha, kick_off_utc)
        if resultado:
            return resultado
    if fixture_id:
        resultado = await _apifootball_odds(client, fixture_id)
        if resultado:
            return resultado
    resultado = await _bsd_odds(client, local, visitante, fecha)
    if resultado:
        return resultado
    if fixture_id:
        resultado = await _apifootball_predictions(client, fixture_id)
        if resultado:
            return resultado
    return _odds_vacias()
