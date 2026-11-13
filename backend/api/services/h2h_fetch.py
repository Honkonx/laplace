"""services/h2h_fetch.py — Historial Head-to-Head, ponderado por antigüedad.

Port de los nodos `GET H2H` (wfb-012) y `Preparar Datos con H2H` / `Preparar Datos sin H2H`
(wfb-014/wfb-015) de WF-B. Cascada api-football `/fixtures/headtohead` (cacheada 7 días) →
BSD `/events/` filtrado por nombre. Los goles promedio se ponderan por antigüedad (media
vida 180 días — un partido de hace 6 meses pesa la mitad que uno de ayer), igual que el
original.

Distinto de `services/h2h.py`, que ANALIZA conteos de victorias/empates ya resueltos — este
módulo construye esos conteos Y los goles promedio ponderados a partir del historial crudo.
El dict que devuelve usa las mismas claves que esperan `services/h2h.py::analizar()` y
`services/pronostico.py::analizar()`.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services import team_stats_fetch
from backend.api.services._http_retry import cuerpo_api_football, get_con_reintento_429
from backend.api.services.ligas import get_liga_avg
from backend.api.services.normalizacion import nombre_equipo_bsd

log = logging.getLogger("laplace.h2h_fetch")

APIF_BASE = "https://v3.football.api-sports.io"
BSD_BASE = "https://sports.bzzoiro.com/api/v2"

MEDIA_VIDA_DIAS = 180
MESES = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _sin_h2h(local: str, visitante: str, liga: str, liga_avg_input: float) -> dict:
    """Último fallback, cuando ni el historial H2H ni las estadísticas reales de temporada de
    cada equipo (`_desde_stats_equipo`) están disponibles: goles estimados desde el promedio de
    la liga (mitad por equipo, visitante ~10% menos) — mismo criterio que wfb-015.

    Hallazgo real 2026-09-09 (auditoría de uniformidad de predicciones, ver
    el registro de decisiones del proyecto): con 224 partidos reales/día y solo ~3% en ligas con tabla/odds
    curados, la mayoría de los partidos caían acá — y como este fallback depende SOLO de
    `liga_avg` (no de qué equipos juegan), partidos de equipos completamente distintos en ligas
    distintas terminaban con las MISMAS probabilidades byte a byte (confirmado: 10+ partidos
    reales con la tripleta 0.3594/0.4362/0.2044 idéntica). `fuente_goles="liga_generico"` deja
    esto trazable — es la señal real de "predicción sin ningún dato específico del partido"."""
    liga_avg = get_liga_avg(liga, liga_avg_input)
    goles_local = round(liga_avg / 2.0, 2)
    goles_visit = round(liga_avg / 2.0 * 0.9, 2)
    return {
        "h2h_disponible": False,
        "h2h_local_wins": 0,
        "h2h_visit_wins": 0,
        "h2h_empates": 0,
        "h2h_total": 0,
        "h2h_resumen": "Sin historial directo disponible.",
        "goles_local_avg": goles_local,
        "goles_visit_avg": goles_visit,
        "goles_contra_local_avg": goles_visit,
        "goles_contra_visit_avg": goles_local,
        "fuente_goles": "liga_generico",
    }


async def _desde_stats_equipo(
    client: httpx.AsyncClient, db: Session, team_id_local: int | None, team_id_visitante: int | None,
    league_id: int | None, season: int | None,
) -> dict | None:
    """Segundo fallback (2026-09-09, ver docstring de `_sin_h2h`): antes de caer al promedio
    genérico de liga, intenta el promedio REAL de temporada de CADA equipo por separado
    (`team_stats_fetch.py` — existía completo, con test propio, pero nunca se llamaba desde
    ningún pipeline real). No es head-to-head (`h2h_disponible` sigue en `False`, no hubo
    historial entre estos dos equipos específicos), pero es un dato real del equipo real que
    juega, no un promedio genérico de la liga — mucho mejor señal para el motor Poisson.
    Devuelve `None` si falta algún id, o si CUALQUIERA de los dos equipos no tiene stats reales
    (mezclar un equipo real con uno genérico sesgaría la comparación más que usar el fallback
    genérico simétrico)."""
    if not (team_id_local and team_id_visitante and league_id and season):
        return None

    stats_local, stats_visit = await asyncio.gather(
        team_stats_fetch.enriquecer_stats_equipo(client, db, team_id_local, league_id, season),
        team_stats_fetch.enriquecer_stats_equipo(client, db, team_id_visitante, league_id, season),
    )
    favor_local, contra_local = team_stats_fetch.extraer_goles_promedio(stats_local)
    favor_visit, contra_visit = team_stats_fetch.extraer_goles_promedio(stats_visit)
    if favor_local is None or favor_visit is None:
        return None

    return {
        "h2h_disponible": False,
        "h2h_local_wins": 0,
        "h2h_visit_wins": 0,
        "h2h_empates": 0,
        "h2h_total": 0,
        "h2h_resumen": "Sin historial directo — usando promedio real de temporada de cada equipo.",
        "goles_local_avg": favor_local,
        "goles_visit_avg": favor_visit,
        "goles_contra_local_avg": contra_local if contra_local is not None else favor_visit,
        "goles_contra_visit_avg": contra_visit if contra_visit is not None else favor_local,
        "fuente_goles": "stats_equipo_real",
    }


async def _apifootball_h2h(client: httpx.AsyncClient, db: Session, team_home: int, team_away: int) -> list[dict] | None:
    if not settings.SPORTS_API_KEY:
        return None
    min_id, max_id = min(team_home, team_away), max(team_home, team_away)
    cache_key = f"h2h:{min_id}-{max_id}"
    cacheado = leer_stats_cache(db, cache_key)
    if cacheado:
        return cacheado

    try:
        r = await get_con_reintento_429(
            client, f"{APIF_BASE}/fixtures/headtohead", log=log, fuente="api-football",
            params={"h2h": f"{team_home}-{team_away}"},  # el plan gratis rechaza `last` ("do not have access to the Last parameter")
            headers={"x-apisports-key": settings.SPORTS_API_KEY}, timeout=12,
        )
        r.raise_for_status()
        fixtures = cuerpo_api_football(r).get("response", [])
    except Exception:
        log.warning("api-football H2H fallo %s-%s", team_home, team_away, exc_info=True)
        return None

    if not fixtures:
        return None
    partidos = [
        {
            "fecha_iso": (f.get("fixture") or {}).get("date", ""),
            "local": ((f.get("teams") or {}).get("home") or {}).get("name", ""),
            "visitante": ((f.get("teams") or {}).get("away") or {}).get("name", ""),
            "goles_local": (f.get("goals") or {}).get("home"),
            "goles_visitante": (f.get("goals") or {}).get("away"),
        }
        for f in fixtures
    ]
    partidos = sorted(partidos, key=lambda p: p["fecha_iso"], reverse=True)[:10]  # los 10 más recientes, como pedía `last=10`
    guardar_stats_cache(db, cache_key, "h2h", partidos)
    return partidos


async def _bsd_h2h(client: httpx.AsyncClient, local: str, visitante: str) -> list[dict] | None:
    if not settings.BSD_API_KEY:
        return None
    headers = {"Authorization": f"Token {settings.BSD_API_KEY}"}
    local_corto = (local or "")[:15]
    try:
        r = await get_con_reintento_429(
            client, f"{BSD_BASE}/events/", log=log, fuente="bsd",
            params={"team_name": local_corto, "status": "finished", "limit": 20},
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        resultados = r.json().get("results", [])
    except Exception:
        log.warning("BSD H2H fallo local=%s", local, exc_info=True)
        return None

    norm_local = (local or "").lower().replace(" ", "")[:5]
    norm_visit = (visitante or "").lower().replace(" ", "")[:5]
    filtrados = []
    for ev in resultados:
        nombre_local_bsd = nombre_equipo_bsd(ev.get("home_team"))
        nombre_visit_bsd = nombre_equipo_bsd(ev.get("away_team"))
        hn = nombre_local_bsd.lower().replace(" ", "")
        an = nombre_visit_bsd.lower().replace(" ", "")
        if (norm_local in hn or hn[:5] in norm_local) and (norm_visit in an or an[:5] in norm_visit):
            filtrados.append(
                {
                    "fecha_iso": ev.get("start_time", ""),
                    "local": nombre_local_bsd,
                    "visitante": nombre_visit_bsd,
                    "goles_local": ev.get("home_score"),
                    "goles_visitante": ev.get("away_score"),
                }
            )
    return filtrados or None


def _dias_desde(fecha_iso: str) -> float:
    if not fecha_iso:
        return MEDIA_VIDA_DIAS * 2
    try:
        dt = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except Exception:
        log.debug("h2h_fetch: fecha ISO inválida al calcular antigüedad", exc_info=True)
        return MEDIA_VIDA_DIAS * 2


def _clave_nombre(nombre: str | None) -> str:
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", plano)


def _es_el_mismo_equipo(a: str | None, b: str | None) -> bool:
    ka, kb = _clave_nombre(a), _clave_nombre(b)
    return bool(ka and kb) and (ka == kb or (min(len(ka), len(kb)) >= 5 and (ka in kb or kb in ka)))


def _orientar_al_partido_actual(partidos: list[dict], local: str | None, visitante: str | None) -> list[dict]:
    """Reorienta cada cruce histórico al local/visitante del partido ACTUAL (2026-10-07).

    Hallazgo de la evaluación del consenso (F, `EVALUACION_CONSENSO_HISTORICO_2026-10-06.md`):
    los goles y victorias se sumaban desde el lado local del partido histórico sin importar quién
    juega de local hoy; con la orientación corregida el módulo h2h pasa de log-loss 1,1512 a 1,0842.
    Si el cruce se jugó con la localía invertida, se intercambian goles y equipos. Un cruce que no
    se puede asociar a ninguno de los dos equipos actuales se deja tal cual."""
    if not local or not visitante:
        return partidos
    orientados = []
    for p in partidos:
        invertido = _es_el_mismo_equipo(p.get("local"), visitante) and _es_el_mismo_equipo(p.get("visitante"), local)
        if invertido:
            p = {**p, "local": p.get("visitante"), "visitante": p.get("local"),
                 "goles_local": p.get("goles_visitante"), "goles_visitante": p.get("goles_local")}
        orientados.append(p)
    return orientados


def _ponderar_y_resumir(partidos: list[dict], local: str | None = None, visitante: str | None = None,
                        media_equipo: float | None = None) -> dict:
    """`local`/`visitante` (opcionales) orientan los cruces al partido actual. `media_equipo`
    (goles por equipo de la liga, `liga_avg / 2`) se usa como defensa NEUTRA del rival: sin ella
    `calcular_lambdas` multiplicaba el promedio de goles por sí mismo (λ ≈ g²/media)."""
    partidos = _orientar_al_partido_actual(partidos[:10], local, visitante)
    con_peso = []
    for p in partidos:
        dias = _dias_desde(p.get("fecha_iso", ""))
        peso = math.exp(-dias / MEDIA_VIDA_DIAS)
        con_peso.append((p, peso, dias))

    peso_total = sum(peso for _, peso, _ in con_peso) or 1.0
    goles_local_pond = sum((p.get("goles_local") or 0) * peso for p, peso, _ in con_peso)
    goles_visit_pond = sum((p.get("goles_visitante") or 0) * peso for p, peso, _ in con_peso)

    local_wins = visit_wins = empates = 0
    for p, _, _ in con_peso:
        gl, gv = p.get("goles_local") or 0, p.get("goles_visitante") or 0
        if gl > gv:
            local_wins += 1
        elif gv > gl:
            visit_wins += 1
        else:
            empates += 1

    total = len(con_peso)
    goles_local_avg = round(goles_local_pond / peso_total, 2) if total else 1.3
    goles_visit_avg = round(goles_visit_pond / peso_total, 2) if total else 1.0

    lineas = []
    for p, peso, dias in con_peso[:5]:
        estrellas = "★★★" if peso >= 0.7 else "★★" if peso >= 0.35 else "★"
        try:
            dt = datetime.fromisoformat(p["fecha_iso"].replace("Z", "+00:00"))
            fecha_corta = f" ({MESES[dt.month]}-{dt.year})"
        except Exception:
            log.debug("h2h_fetch: fecha ISO inválida al formatear", exc_info=True)
            fecha_corta = ""
        lineas.append(
            f"{p.get('local','?')} {p.get('goles_local','?')}-{p.get('goles_visitante','?')} "
            f"{p.get('visitante','?')}{fecha_corta} {estrellas}"
        )

    return {
        "h2h_disponible": True,
        "h2h_local_wins": local_wins,
        "h2h_visit_wins": visit_wins,
        "h2h_empates": empates,
        "h2h_total": total,
        "h2h_resumen": "\n".join(lineas),
        "goles_local_avg": goles_local_avg,
        "goles_visit_avg": goles_visit_avg,
        # Sin estadísticas de defensa por equipo, la defensa rival entra como neutra (1,0 × media de
        # liga): así λ_local = goles que el local suele marcar en el cruce, no ese valor al cuadrado.
        "goles_contra_local_avg": media_equipo if media_equipo else goles_visit_avg,
        "goles_contra_visit_avg": media_equipo if media_equipo else goles_local_avg,
        "fuente_goles": "h2h_real",
    }


MAX_CRUCES_PROPIOS = 10


def _cruces_propios(local: str, visitante: str, liga: str) -> list[dict]:
    """Cruces entre los dos equipos sacados del historial propio (maestro + resultados actuales + los del bot), más recientes primero.

    Solo si ambos equipos se resuelven a un nombre canónico EXACTO en una misma liga (nada de coincidencias aproximadas: dos equipos homónimos darían cruces que nunca existieron).
    Los nombres de cada cruce se escriben con los del partido actual, así queda orientado sin adivinar."""
    from backend.api.services import modelo_historico, simulador_propio

    r = modelo_historico._resolver({"liga": liga, "local": local, "visitante": visitante})  # noqa: SLF001 — mismo resolutor del consenso
    if not r or not r[0]:
        return []
    codigo, _modelo, canon_local, canon_visitante = r
    cruces = []
    for p in simulador_propio._partidos():  # noqa: SLF001 — caché de 10 minutos del conjunto completo
        if p["liga"] != codigo or {p["local"], p["visitante"]} != {canon_local, canon_visitante}:
            continue
        mismo_orden = p["local"] == canon_local
        cruces.append({"local": local if mismo_orden else visitante, "visitante": visitante if mismo_orden else local, "goles_local": p["gl"], "goles_visitante": p["gv"],
                       "fecha_iso": p["fecha"].isoformat() + "T12:00:00+00:00", "dia": p["dia"]})
    cruces.sort(key=lambda x: -x["dia"])
    return cruces[:MAX_CRUCES_PROPIOS]


async def obtener_h2h(
    client: httpx.AsyncClient, db: Session, team_id_local: int | None, team_id_visitante: int | None,
    local: str, visitante: str, liga: str, liga_avg_input: float = 2.6,
    league_id: int | None = None, season: int | None = None,
) -> dict:
    """Cascada completa. Siempre devuelve el shape que esperan `services/h2h.py` y
    `services/pronostico.py`, más `fuente_goles` (2026-09-09, auditoría de uniformidad —
    "h2h_real" > "stats_equipo_real" > "liga_generico", trazabilidad real de qué tan
    específico del partido es cada análisis).

    `league_id`/`season` (opcionales, ver `services/gateway.py::buscar_fixture_id`) habilitan
    el segundo fallback real (`_desde_stats_equipo`) antes de caer al promedio genérico de
    liga — sin ellos, se salta directo al fallback genérico de siempre (comportamiento sin
    cambios para callers que no los pasen)."""
    partidos: list[dict] | None = None
    if team_id_local and team_id_visitante:
        partidos = await _apifootball_h2h(client, db, team_id_local, team_id_visitante)
    if not partidos:
        partidos = await _bsd_h2h(client, local, visitante)
    # Con 3+ cruces el H2H es la fuente más específica del partido. Con 1-2 (la mayoría) no alcanza para que `h2h` se
    # cuente como fuente (mínimo 3, `calidad_datos`), y antes cortaba aquí sin probar las estadísticas de temporada de
    # cada equipo: auditoría 2026-10-09. Ahora cae a esas estadísticas y, si tampoco existen, conserva el H2H corto.
    if partidos and len(partidos) >= 3:
        return _ponderar_y_resumir(partidos, local, visitante, get_liga_avg(liga, liga_avg_input) / 2.0)

    # Las fuentes externas dieron menos de 3 cruces (el plan gratis de API-Football no trae la temporada actual y BSD cubre poco): se usa el historial propio, que existe aunque ninguna fuente responda.
    try:
        propios = await asyncio.to_thread(_cruces_propios, local, visitante, liga)
    except Exception:  # noqa: BLE001 — una pieza de respaldo: si falla, sigue la cascada de siempre
        log.warning("h2h_fetch: no se pudo leer el historial propio", exc_info=True)
        propios = []
    if len(propios) >= 3 and len(propios) > len(partidos or []):
        return {**_ponderar_y_resumir(propios, local, visitante, get_liga_avg(liga, liga_avg_input) / 2.0), "fuente_h2h": "historial_propio"}

    desde_stats = await _desde_stats_equipo(client, db, team_id_local, team_id_visitante, league_id, season)
    if desde_stats:
        return desde_stats
    if partidos:
        return _ponderar_y_resumir(partidos, local, visitante, get_liga_avg(liga, liga_avg_input) / 2.0)

    return _sin_h2h(local, visitante, liga, liga_avg_input)
