"""services/top_picks.py — Orquestador de WF-D (Top 3 Picks Canal).

Flujo completo: fixtures del día (api-football) → guardar en `partidos_dia` → filtrar por
listas de ligas premium/standard → scoring rápido (predictions/odds/H2H disponibles) → analizar
el top 5-7 con el motor de consenso completo (`services/motor.py`, mismo que usa
`services/analisis_completo.py`) → Claude (`ai_prompt_canal`) → consolidar estadístico+IA a 2
vías (`services/consenso_ia.py`) → filtrar por umbral → publicar al canal + guardar
predicciones/recomendaciones. Confirmación admin cuando la confianza es baja: se deja
`confirmar_publicacion()` como función pura para que el bot de Telegram (hilo principal) la
conecte a los botones inline `pub_/nopub_` — este módulo no registra ningún handler de Telegram.

Fix real 2026-09-09 (bug de consistencia entre pipelines, confirmado leyendo el código): antes,
el pick de cada candidato salía de un voto ad-hoc a 3 vías (Poisson vs Forma vs Claude) que
NUNCA usaba h2h/odds/tabla para decidir, aunque esos datos se calculaban y se mostraban en el
mensaje del canal como si hubieran influido — inconsistencia real detectable (un partido con
h2h/odds fuertes a favor del visitante podía publicarse como pick "Local" en el canal, mientras
`analisis_completo.py` daba "Visitante" para el MISMO partido si el usuario pedía el análisis
completo al bot/app). Ahora `_analizar_candidato()` corre `services/motor.py::analizar_partido()`
(los mismos 5 módulos con pesos dinámicos que usa el bot/app: poisson+forma+h2h+odds+tabla) y
`generar_top_picks_dia()` consolida ese consenso con Claude vía
`services/consenso_ia.py::combinar_con_claude()` — la MISMA función que usa
`services/analisis_completo.py` — así que el pick que ve un usuario en el canal es el mismo que
vería pidiendo un análisis completo del mismo partido. Ver `backend/tests/test_top_picks.py`
para la verificación empírica (un caso con h2h/odds divergentes de poisson/forma que antes daba
un pick distinto y ahora coincide con `motor.analizar_partido()["consenso"]["pick_final"]`).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import partidos_repo
from backend.api.db.cache import guardar_stats_cache, leer_stats_cache
from backend.api.services import calidad_datos as calidad_datos_svc
from backend.api.services._http_retry import CuotaApiFootballError, cuerpo_api_football
from backend.api.services import consenso as consenso_svc
from backend.api.services import consenso_ia as consenso_ia_svc
from backend.api.services import motor as motor_svc
from backend.api.services.ai_prompt_canal import construir_prompt_canal, parsear_respuesta_canal
from backend.api.services.ai_client import AnalisisIAError, generar_texto_ia
from backend.api.services import ia_simple_laboratorio
from backend.api.services.ligas import get_liga_avg
from backend.api.services import laboratorio_pronosticos

log = logging.getLogger("laplace.top_picks")
# Reexportado desde top_picks_publicacion (la publicación al canal vive allí): los importadores externos no cambian.
from backend.api.services.top_picks_publicacion import (  # noqa: E402,F401
    MARCA_PUBLICADO_TTL_HORAS, NIVEL_IA_EMOJI, NIVEL_IA_TEXTO, UMBRAL_PROB_PUBLICAR, _PENDIENTES_CONFIRMACION,
    _clave_publicado, _formatear_mensaje_canal, _marcar_publicado, _ya_publicado_hoy, confirmar_publicacion,
    guardar_pendiente_confirmacion, publicar_top_picks, sacar_pendiente_confirmacion,
)

APIF_BASE = "https://v3.football.api-sports.io"
TZ_CHILE = ZoneInfo("America/Santiago")
UTC_OFFSET_CHILE = -4  # conservador (Chile UTC-3/-4 según horario de verano)

UMBRAL_PUBLICAR = 55  # score mínimo histórico; solo se conserva para mensajes y compatibilidad
UMBRAL_BAJA_CONFIANZA = 65
CAP_CANDIDATOS = 10
CAP_SCORING = 5
CAP_ANALIZADOS = 5



LIGAS_PREMIUM = {39, 140, 135, 78, 61, 2, 3, 848, 253, 262, 71, 128}
LIGAS_STANDARD = {
    88, 94, 203, 307, 72, 13, 11, 98, 188, 196, 136, 137, 40, 41, 79,
    65, 66, 103, 113, 119, 333, 239, 132, 200, 73,
}
LIGAS_OK = LIGAS_PREMIUM | LIGAS_STANDARD

LIGA_SLUG_POR_ID = {
    39: "premier", 140: "laliga", 135: "seriea", 78: "bundesliga", 61: "ligue1",
    2: "champions", 3: "europa", 848: "conference", 88: "eredivisie",
    94: "primeirliga", 203: "superlig", 307: "saudipro", 253: "mls", 262: "ligamx",
    13: "libertadores", 11: "sudamericana", 132: "copa_colombia", 200: "botola_pro",
    73: "copa_nordeste",
}


def _headers() -> dict:
    return {"x-apisports-key": settings.SPORTS_API_KEY}


async def _apif_get(client: httpx.AsyncClient, endpoint: str) -> dict:
    try:
        r = await client.get(f"{APIF_BASE}/{endpoint}", headers=_headers(), timeout=12)
        r.raise_for_status()
        return cuerpo_api_football(r)
    except CuotaApiFootballError as exc:
        # HTTP 200 con `errors` (plan sin acceso a la temporada, cuota agotada…): antes se leía como «día sin partidos» sin dejar rastro.
        log.warning("api-football rechazó %s: %s", endpoint, exc)
        return {"response": []}
    except Exception:
        log.debug("Fallo api-football GET %s", endpoint, exc_info=True)
        return {"response": []}


def _hora_chile(timestamp_utc: int) -> str:
    dt_utc = datetime.utcfromtimestamp(timestamp_utc)
    hora = (dt_utc.hour + UTC_OFFSET_CHILE) % 24
    return f"{hora:02d}:{dt_utc.minute:02d}"


async def _traer_y_guardar_fixtures_dia(db: Session, client: httpx.AsyncClient, fecha_api: str) -> list[dict]:
    """`GET Fixtures del Día` (wfd-003) + `Guardar Partidos Dia` (wfd-003b): trae TODOS los
    fixtures del día (no solo los de ligas ok) y los persiste en `partidos_dia` para que la
    acción `juegos` de la app/Telegram no dependa de LiveScore6."""
    data = await _apif_get(client, f"fixtures?date={fecha_api}")
    fixtures = data.get("response", [])

    partidos = []
    for f in fixtures:
        ts = f.get("fixture", {}).get("timestamp") or 0
        league_id = f.get("league", {}).get("id")
        partidos.append(
            {
                "match_id": str(f["fixture"]["id"]),
                "liga_slug": LIGA_SLUG_POR_ID.get(league_id, f"liga_{league_id}"),
                "liga_nombre": f.get("league", {}).get("name", "Liga"),
                "liga_codigo": str(league_id or ""),
                "liga_logo": f.get("league", {}).get("logo", ""),
                "local": f.get("teams", {}).get("home", {}).get("name", "Local"),
                "visitante": f.get("teams", {}).get("away", {}).get("name", "Visitante"),
                "hora_chile": _hora_chile(ts) if ts else "",
                "logo_local": f.get("teams", {}).get("home", {}).get("logo", ""),
                "logo_visitante": f.get("teams", {}).get("away", {}).get("logo", ""),
                "status": "scheduled" if f.get("fixture", {}).get("status", {}).get("short") == "NS"
                else f.get("fixture", {}).get("status", {}).get("short", "scheduled"),
                "kick_off_utc": dt.isoformat() if ts and (dt := datetime.utcfromtimestamp(ts)) else "",
                "goles_local": f.get("goals", {}).get("home"),
                "goles_visitante": f.get("goals", {}).get("away"),
            }
        )
    if partidos:
        # `guardar_partidos_dia` (agregada en paralelo por el agente de repos DB) acepta
        # goles_local/goles_visitante/apifootball_fixture_id además de lo que ya tenía
        # `guardar_ligas_cache` — misma tabla `partidos_dia`, más columnas.
        partidos_repo.guardar_partidos_dia(db, fecha_api, partidos)
    return fixtures


def _filtrar_candidatos(fixtures: list[dict], fecha_db: str, fecha_display: str) -> list[dict]:
    """`Filtrar Candidatos` (wfd-004): solo ligas premium/standard, desde las 7AM Chile, con
    algún dato de referencia real de la liga, máximo CAP_CANDIDATOS.

    Filtro de calidad de partido (agregado 2026-09-08, conservador a propósito): además del
    filtro existente por `league_id` (`LIGAS_OK`, ids curados a mano), se descarta un candidato
    cuando `services/ligas.py::es_liga_conocida(nombre)` es `False` — es decir, cuando el NOMBRE
    de liga que trae api-football no matchea NINGUNA entrada de la tabla unificada `LIGAS`, así
    que el sistema no tiene ni promedio de gol real, ni tabla, ni odds_key para esa liga. Es un
    caso objetivo (ausencia total de dato), no un juicio de "calidad" subjetivo — y es
    conservador porque nunca excluye una liga que SÍ tiene aunque sea un promedio de gol
    propio (`avg_goles` real), solo la que no tiene absolutamente nada. En la práctica actúa
    como red de seguridad: `LIGAS_OK` ya restringe a ligas top conocidas, pero el matching de
    `es_liga_conocida` es por texto (nombre exacto que devuelve api-football) mientras que
    `LIGAS_OK` es por `league_id` — pueden desalinearse si api-football cambia el nombre de una
    liga. El partido sigue guardado en `partidos_dia` igual (`_traer_y_guardar_fixtures_dia` ya
    persistió TODOS los fixtures del día antes de llegar acá) — solo no entra a la cascada
    cara de scoring/stats/H2H/standings/IA de Top Picks."""
    candidatos = []
    for f in fixtures:
        # Top Picks y el laboratorio solo admiten evidencia prepartido. Un fixture en juego,
        # terminado o aplazado no puede recibir un corte nuevo sin contaminar la evaluación.
        if f.get("fixture", {}).get("status", {}).get("short") != "NS":
            continue
        league_id = f.get("league", {}).get("id")
        if league_id not in LIGAS_OK:
            continue
        ts = f.get("fixture", {}).get("timestamp") or 0
        if not ts:
            continue
        hora_real = (datetime.utcfromtimestamp(ts).hour + UTC_OFFSET_CHILE) % 24
        if hora_real < 7:
            continue
        nombre_liga = f.get("league", {}).get("name", "Liga")
        candidatos.append(
            {
                "fixture_id": f["fixture"]["id"],
                "season": f.get("league", {}).get("season"),
                "local": f.get("teams", {}).get("home", {}).get("name", "Local"),
                "visitante": f.get("teams", {}).get("away", {}).get("name", "Visitante"),
                "team_id_local": f.get("teams", {}).get("home", {}).get("id"),
                "team_id_visitante": f.get("teams", {}).get("away", {}).get("id"),
                "liga": nombre_liga,
                "league_id": league_id,
                "hora_chile": _hora_chile(ts),
                "kick_off_utc": datetime.utcfromtimestamp(ts).isoformat() + "Z",
                "fecha_db": fecha_db,
                "fecha_display": fecha_display,
                "score_liga": 2 if league_id in LIGAS_PREMIUM else 1,
            }
        )
    candidatos.sort(key=lambda item: (item["score_liga"], item["hora_chile"]), reverse=True)
    return candidatos[:CAP_CANDIDATOS]


async def _score_rapido(client: httpx.AsyncClient, candidatos: list[dict]) -> list[dict]:
    """`Score Rápido Candidatos` (wfd-006): +3 predictions, +3/+2/-1 según rango de odds,
    +1 H2H disponible (≥3), -1 si no hay ni odds ni predictions."""
    scored = []
    for c in candidatos:
        score = c["score_liga"]
        pick_externo = None
        tiene_odds = tiene_predictions = tiene_h2h = False
        odd_home = odd_draw = odd_away = 0.0

        pred = (await _apif_get(client, f"predictions?fixture={c['fixture_id']}")).get("response") or []
        prediccion_externa = pred[0] if pred else None
        if pred:
            tiene_predictions = True
            score += 3
            pick_externo = (pred[0].get("predictions", {}).get("winner") or {}).get("name")

        odds_resp = (await _apif_get(client, f"odds?fixture={c['fixture_id']}")).get("response") or []
        bookmakers = (odds_resp[0].get("bookmakers") if odds_resp else []) or []
        for bk in bookmakers:
            mkt = next((b for b in bk.get("bets", []) if b.get("name") == "Match Winner"), None)
            if not mkt:
                continue
            valores = {v["value"]: float(v["odd"]) for v in mkt.get("values", [])}
            odd_home, odd_draw, odd_away = valores.get("Home", 0), valores.get("Draw", 0), valores.get("Away", 0)
            if odd_home > 0:
                tiene_odds = True
                break
        if tiene_odds:
            mejor = min(odd_home, odd_away)
            if 1.40 <= mejor <= 2.80:
                score += 3
            elif 1.25 <= mejor < 1.40:
                score += 2
            elif mejor < 1.25:
                score -= 1
            else:
                score += 2

        if c["team_id_local"] and c["team_id_visitante"]:
            h2h = (await _apif_get(
                client, f"fixtures/headtohead?h2h={c['team_id_local']}-{c['team_id_visitante']}&last=5"
            )).get("response") or []
            if len(h2h) >= 3:
                tiene_h2h = True
                score += 1

        if not tiene_odds and not tiene_predictions:
            score -= 1

        scored.append({
            **c, "score_datos": score, "pick_externo": pick_externo,
            "prediccion_externa": prediccion_externa,
            "odd_home_cached": odd_home, "odd_draw_cached": odd_draw, "odd_away_cached": odd_away,
            "tiene_odds": tiene_odds, "tiene_predictions": tiene_predictions, "tiene_h2h_rapido": tiene_h2h,
        })

    scored.sort(key=lambda x: x["score_datos"], reverse=True)
    return scored[:CAP_SCORING]


def _contar_forma(form_str: str) -> int:
    return (form_str or "")[-5:].count("W") if form_str else 2


def _estadisticas_desde_prediccion(prediccion: dict | None, lado: str) -> tuple[float, float, int, str] | None:
    """Extrae estadísticas de equipo de `predictions?fixture` cuando el endpoint específico
    `teams/statistics` no tiene cobertura. Es dato estructurado de API-Football, no el pick
    externo: el consenso no incorpora su ganador sugerido como voto."""
    try:
        equipo = (prediccion or {}).get("teams", {}).get(lado, {})
        liga = equipo.get("league", {})
        goles = liga.get("goals", {})
        gf = float(goles.get("for", {}).get("average", {}).get("total"))
        ga = float(goles.get("against", {}).get("average", {}).get("total"))
        forma = str(liga.get("form") or "")
    except (TypeError, ValueError):
        return None
    if gf < 0 or ga < 0:
        return None
    return round(gf, 2), round(ga, 2), _contar_forma(forma), forma[-5:]


async def _team_stats_cacheado(db: Session, client: httpx.AsyncClient, team_id: int, league_id: int, season: int) -> dict | None:
    key = f"team_stats:{team_id}:{league_id}:{season}"
    cached = leer_stats_cache(db, key)
    if cached is not None:
        return cached
    data = (await _apif_get(client, f"teams/statistics?league={league_id}&season={season}&team={team_id}")).get("response")
    if data:
        guardar_stats_cache(db, key, "team_stats", data)
    return data


async def _h2h_cacheado(db: Session, client: httpx.AsyncClient, team_a: int, team_b: int) -> list[dict]:
    key = f"h2h:{min(team_a, team_b)}-{max(team_a, team_b)}"
    cached = leer_stats_cache(db, key)
    if cached is not None:
        return cached
    data = (await _apif_get(client, f"fixtures/headtohead?h2h={team_a}-{team_b}&last=10")).get("response") or []
    if data:
        guardar_stats_cache(db, key, "h2h", data)
    return data


async def _analizar_candidato(db: Session, client: httpx.AsyncClient, c: dict, fecha_api: str) -> dict:
    """`Analizar Top 5 en Serie` (wfd-007): stats reales por equipo, H2H completo, odds
    (reusa cache del scoring), standings, y el motor de consenso completo
    (`services/motor.py`: poisson+forma+h2h+odds+tabla, mismo que usa el bot/app)."""
    season = int(c.get("season") or datetime.now().year)
    goles_local_avg, goles_visit_avg = 1.3, 1.0
    goles_contra_local_avg, goles_contra_visit_avg = 1.0, 1.3
    forma_local_wins, forma_visit_wins = 2, 2
    stats_local_str, stats_visit_str = "Sin datos", "Sin datos"
    pos_local, pos_visit = 10, 10

    stats_local_reales = stats_visit_reales = False
    if c["team_id_local"] and c["league_id"]:
        st = await _team_stats_cacheado(db, client, c["team_id_local"], c["league_id"], season)
        if st:
            gf, ga = st.get("goals", {}).get("for", {}).get("average", {}).get("total"), \
                st.get("goals", {}).get("against", {}).get("average", {}).get("total")
            forma = st.get("form", "") or ""
            if gf is not None and ga is not None:
                goles_local_avg = round(float(gf), 2)
                goles_contra_local_avg = round(float(ga), 2)
                stats_local_reales = True
            forma_local_wins = _contar_forma(forma)
            stats_local_str = f"Goles/P: {gf or '?'} | Rec: {ga or '?'} | Forma: {forma[-5:] or '?'}"
    if not stats_local_reales:
        fallback = _estadisticas_desde_prediccion(c.get("prediccion_externa"), "home")
        if fallback:
            goles_local_avg, goles_contra_local_avg, forma_local_wins, forma = fallback
            stats_local_reales = True
            stats_local_str = f"Goles/P: {goles_local_avg} | Rec: {goles_contra_local_avg} | Forma: {forma or '?'} (predictions)"

    if c["team_id_visitante"] and c["league_id"]:
        st = await _team_stats_cacheado(db, client, c["team_id_visitante"], c["league_id"], season)
        if st:
            gf, ga = st.get("goals", {}).get("for", {}).get("average", {}).get("total"), \
                st.get("goals", {}).get("against", {}).get("average", {}).get("total")
            forma = st.get("form", "") or ""
            if gf is not None and ga is not None:
                goles_visit_avg = round(float(gf), 2)
                goles_contra_visit_avg = round(float(ga), 2)
                stats_visit_reales = True
            forma_visit_wins = _contar_forma(forma)
            stats_visit_str = f"Goles/P: {gf or '?'} | Rec: {ga or '?'} | Forma: {forma[-5:] or '?'}"
    if not stats_visit_reales:
        fallback = _estadisticas_desde_prediccion(c.get("prediccion_externa"), "away")
        if fallback:
            goles_visit_avg, goles_contra_visit_avg, forma_visit_wins, forma = fallback
            stats_visit_reales = True
            stats_visit_str = f"Goles/P: {goles_visit_avg} | Rec: {goles_contra_visit_avg} | Forma: {forma or '?'} (predictions)"

    h2h_local_wins = h2h_visit_wins = h2h_empates = h2h_total = 0
    h2h_disponible = False
    h2h_resumen = "Sin historial directo."
    if c["team_id_local"] and c["team_id_visitante"]:
        partidos_h2h = await _h2h_cacheado(db, client, c["team_id_local"], c["team_id_visitante"])
        if len(partidos_h2h) >= 2:
            h2h_disponible = True
            h2h_total = len(partidos_h2h)
            lineas = []
            for p in partidos_h2h[:10]:
                gl, gv = p.get("goals", {}).get("home") or 0, p.get("goals", {}).get("away") or 0
                if gl > gv:
                    h2h_local_wins += 1
                elif gv > gl:
                    h2h_visit_wins += 1
                else:
                    h2h_empates += 1
                if len(lineas) < 5:
                    home, away = p["teams"]["home"]["name"], p["teams"]["away"]["name"]
                    lineas.append(f"{home} {gl}-{gv} {away}")
            h2h_resumen = "\n".join(lineas)

    if c["odd_home_cached"]:
        odds_local, odds_empate, odds_visit = c["odd_home_cached"], c["odd_draw_cached"], c["odd_away_cached"]
        odds_disp = True
    else:
        odds_local = odds_empate = odds_visit = None
        odds_disp = False

    standings = (await _apif_get(client, f"standings?league={c['league_id']}&season={season}")).get("response") or []
    tabla = ((standings[0].get("league", {}).get("standings") or [[]])[0] if standings else [])
    tabla_local_real = tabla_visit_real = False
    for s in tabla:
        if s.get("team", {}).get("id") == c["team_id_local"]:
            pos_local = s.get("rank", 10)
            tabla_local_real = True
        if s.get("team", {}).get("id") == c["team_id_visitante"]:
            pos_visit = s.get("rank", 10)
            tabla_visit_real = True

    fuente_goles = "stats_equipo_real" if stats_local_reales and stats_visit_reales else (
        "h2h_real" if h2h_total >= 3 else "liga_generico"
    )
    fuentes_crudas = {
        "estadisticas_equipo": stats_local_reales and stats_visit_reales,
        "tabla": tabla_local_real and tabla_visit_real,
        "h2h": h2h_total >= 3,
        "odds": odds_disp,
    }

    d = {
        "local": c["local"], "visitante": c["visitante"], "liga": c["liga"],
        "partido_id": str(c["fixture_id"]), "fecha": fecha_api,
        "goles_local_avg": goles_local_avg, "goles_visit_avg": goles_visit_avg,
        "goles_contra_local_avg": goles_contra_local_avg, "goles_contra_visit_avg": goles_contra_visit_avg,
        "liga_goles_avg": get_liga_avg(c["liga"], 2.60),
        "pos_local": pos_local, "pos_visit": pos_visit,
        "forma_local_wins": forma_local_wins, "forma_visit_wins": forma_visit_wins,
        "h2h_local_wins": h2h_local_wins, "h2h_visit_wins": h2h_visit_wins,
        "h2h_empates": h2h_empates, "h2h_total": h2h_total, "h2h_disponible": h2h_disponible,
        "odds_local": odds_local, "odds_empate": odds_empate, "odds_visit": odds_visit,
        "odds_disponibles": odds_disp,
        "forma_datos_reales": stats_local_reales and stats_visit_reales,
        "fuente_goles": fuente_goles,
    }

    # Puerta única compartida con `analisis_completo` (`calidad_datos.calcular_calidad_datos`):
    # evaluada con `d` ya armado para saber si `historico` participa antes de decidir.
    calidad_datos = calidad_datos_svc.calcular_calidad_datos(fuentes_crudas, d)

    # Fix 2026-09-09: antes acá corrían `pronostico_svc.analizar(d)` + `form_recent_svc.analizar(d)`
    # sueltos y el pick final del candidato salía de un voto ad-hoc a 3 vías (Poisson/Forma/IA)
    # que nunca pesaba h2h/odds/tabla — aunque `d` ya traía esos datos completos. Ahora corre el
    # MISMO motor de consenso que usa `services/analisis_completo.py` (bot/app) para que el pick
    # sea consistente entre el canal de Top Picks y un análisis completo del mismo partido.
    resultado_motor = motor_svc.analizar_partido(d)
    estadistico = resultado_motor.get("modulos", {}).get("poisson", {})
    estadistico_form = resultado_motor.get("modulos", {}).get("forma", {})
    consenso_est = resultado_motor.get("consenso", {})

    # `score_calidad` (score de consenso: acuerdo entre módulos) decide la elegibilidad. El orden
    # del ranking usa primero la probabilidad ponderada del pick (la señal real del consenso) y
    # después el score como desempate (auditoría 2026-10-06: rankear solo por acuerdo premiaba
    # partidos donde varios módulos coinciden en una probabilidad baja).
    score_calidad = consenso_est.get("score_consenso", 0)
    prob_pick = _probabilidad_del_pick(consenso_est)

    return {
        **c, "h2h_resumen": h2h_resumen, "h2h_disponible": h2h_disponible,
        "odds_local": odds_local, "odds_empate": odds_empate, "odds_visit": odds_visit, "odds_disponibles": odds_disp,
        "stats_local_str": stats_local_str, "stats_visit_str": stats_visit_str,
        "resultado_motor": resultado_motor, "estadistico": estadistico, "estadistico_form": estadistico_form,
        "datos_motor": d,
        "score_calidad": score_calidad,
        "prob_pick": prob_pick,
        "calidad_datos": calidad_datos,
    }


def _clave_ranking(candidato: dict) -> tuple[float, int]:
    """Orden del Top: probabilidad ponderada del pick y, a igualdad, score de consenso."""
    return candidato["prob_pick"], candidato["score_calidad"]


def _probabilidad_del_pick(consenso: dict) -> float:
    """Probabilidad ponderada del resultado que el consenso eligió (0.0 si no hay estimación)."""
    clave = {"Local": "local", "Empate": "empate", "Visitante": "visitante"}.get(consenso.get("pick_final", ""))
    return float((consenso.get("prob_ponderada") or {}).get(clave, 0.0)) if clave else 0.0


def _consolidar_pick(resultado_motor: dict, ia: dict) -> dict:
    """Consolida el pick final del candidato con el MISMO consenso a 2 vías (estadístico
    completo vs IA) que usa `services/analisis_completo.py` — reusa
    `services/consenso_ia.py::combinar_con_claude()` sin duplicar su lógica de pesos/umbrales.

    `combinar_con_claude` espera el texto crudo de Claude (para extraer el pick con regex,
    caso de WF-B) — acá la IA del canal (`ai_prompt_canal.py`) ya devuelve el pick parseado en
    `ia['pick']` (nombre de equipo o None si no hubo IA disponible), así que se sintetiza una
    línea `PICK: <equipo>` mínima que matchea el patrón de `extraer_pick_claude` — evita
    reimplementar la normalización/mapeo de picks que ya vive en `consenso_ia.py`."""
    texto_ia_sintetico = f"PICK: {ia.get('pick') or 'Sin datos'}"
    return consenso_ia_svc.combinar_con_claude(resultado_motor, texto_ia_sintetico)


async def generar_top_picks_dia(db: Session, client: httpx.AsyncClient, ahora: datetime | None = None) -> dict:
    """Punto de entrada — genera (sin publicar todavía) el Top 3 Picks del día."""
    ahora_cl = (ahora or datetime.now(TZ_CHILE)).astimezone(TZ_CHILE)
    fecha_api = ahora_cl.strftime("%Y-%m-%d")
    fecha_db = ahora_cl.strftime("%Y%m%d")
    fecha_display = ahora_cl.strftime("%d/%m/%Y")

    fixtures = await _traer_y_guardar_fixtures_dia(db, client, fecha_api)
    candidatos = _filtrar_candidatos(fixtures, fecha_db, fecha_display)
    if not candidatos:
        return {"fecha_display": fecha_display, "sin_candidatos": True}

    scored = await _score_rapido(client, candidatos)
    analizados = [await _analizar_candidato(db, client, c, fecha_api) for c in scored]
    # Congela las variantes ya calculadas. No cambia el ranking ni el consenso publicado;
    # solo deja una muestra reproducible para evaluarla cuando llegue el resultado oficial.
    for item in analizados:
        motor = item["resultado_motor"]
        laboratorio_pronosticos.registrar_comparadores_del_motor(
            db, partido_id=str(item["fixture_id"]), fecha_partido=fecha_api,
            local=item["local"], visitante=item["visitante"], liga=item["liga"],
            hora_kickoff=item.get("kick_off_utc"), datos=item["datos_motor"],
            modulos=motor.get("modulos", {}), combinado=None,
        )
        if item.get("prediccion_externa"):
            laboratorio_pronosticos.registrar_referencia_api_football(
                db, partido_id=str(item["fixture_id"]), fecha_partido=fecha_api,
                local=item["local"], visitante=item["visitante"], liga=item["liga"],
                hora_kickoff=item.get("kick_off_utc"),
                respuesta=item["prediccion_externa"],
            )
    # Libera el lock de SQLite antes de que la telemetría de IA escriba desde su propia sesión.
    # Las referencias ya quedaron congeladas aunque la IA gratuita esté caída.
    db.commit()
    analizados.sort(key=_clave_ranking, reverse=True)
    # No se llama a IA para candidatos que el motor ya considera insuficientes: así se evitan
    # explicaciones atractivas sobre datos que no alcanzan el estándar de publicación.
    elegibles = [c for c in analizados if c["prob_pick"] >= UMBRAL_PROB_PUBLICAR and c["calidad_datos"]["eligible"]]
    # La IA simple es un comparador experimental, no una condición para publicar. Se limita a
    # una muestra diaria para respetar la cuota y deja proveedor/modelo/respuesta cruda trazables.
    if settings.LAB_IA_SIMPLE_ACTIVA:
        for candidato in elegibles[:settings.LAB_IA_SIMPLE_MAX_PARTIDOS]:
            try:
                hipotesis, crudo, proveedor, modelo = await ia_simple_laboratorio.generar_hipotesis(
                    candidato["local"], candidato["visitante"], candidato["liga"]
                )
                laboratorio_pronosticos.registrar_ia_simple(
                    db, partido_id=str(candidato["fixture_id"]), fecha_partido=fecha_api,
                    local=candidato["local"], visitante=candidato["visitante"], liga=candidato["liga"],
                    hora_kickoff=candidato.get("kick_off_utc"), proveedor=proveedor, modelo=modelo,
                    prompt_version=ia_simple_laboratorio.PROMPT_VERSION, respuesta=hipotesis,
                    respuesta_cruda=crudo,
                )
                # ai_metrics usa una sesión independiente para su telemetría. SQLite sólo
                # permite un escritor: confirmar esta observación antes de la próxima llamada
                # evita que la métrica del proveedor quede bloqueada por nuestra transacción.
                db.commit()
            except (AnalisisIAError, ValueError):
                db.rollback()
                log.warning("IA simple no produjo hipótesis válida para fixture=%s", candidato["fixture_id"], exc_info=True)
    top3 = elegibles[:3]
    sobrantes = analizados[3:CAP_ANALIZADOS + 2]

    if not top3:
        return {
            "fecha_display": fecha_display, "fecha_db": fecha_db, "sin_candidatos": False,
            "sin_picks_validos": True, "picks": [], "baja_confianza": False,
            "score_min": None, "sobrantes": [],
        }

    try:
        texto_ia = await generar_texto_ia(construir_prompt_canal(top3), rol="canal")
        bloques_ia = parsear_respuesta_canal(texto_ia)
    except AnalisisIAError:
        log.warning(
            "Ningún proveedor de IA disponible para Top Picks — se publica solo con el "
            "consenso estadístico completo (poisson+forma+h2h+odds+tabla)", exc_info=True,
        )
        bloques_ia = [{"pick": None, "razon": "IA no disponible", "confianza": None} for _ in top3]

    picks_validos = []
    score_min = 100
    for i, c in enumerate(top3):
        resultado_motor = c["resultado_motor"]
        consenso_est = resultado_motor.get("consenso", {})
        est, frm = c["estadistico"], c["estadistico_form"]
        ia = bloques_ia[i] if i < len(bloques_ia) else {"pick": None, "razon": "", "confianza": None}

        # Mismo consenso a 2 vías (estadístico completo — poisson+forma+h2h+odds+tabla — vs
        # IA) que arma `services/analisis_completo.py`, no un voto ad-hoc propio.
        combinado = _consolidar_pick(resultado_motor, ia)
        laboratorio_pronosticos.registrar_comparadores_del_motor(
            db, partido_id=str(c["fixture_id"]), fecha_partido=fecha_api,
            local=c["local"], visitante=c["visitante"], liga=c["liga"],
            hora_kickoff=c.get("kick_off_utc"), datos=c["datos_motor"],
            modulos=resultado_motor.get("modulos", {}),
            combinado={**combinado, "texto_claude": ia.get("razon", "")},
        )
        score_consolidado = combinado["score_consolidado"]
        pick_final = combinado["pick_unificado"]

        # La IA solo puede bajar la confianza: un pick que quedó en BAJA (probabilidad < 0,50, un único
        # módulo o divergencia con la IA) no se publica.
        if combinado["confianza_final"] == "BAJA":
            continue

        score_min = min(score_min, score_consolidado)

        picks_validos.append({
            "fixture_id": c["fixture_id"], "local": c["local"], "visitante": c["visitante"],
            "liga": c["liga"], "hora_chile": c["hora_chile"], "fecha_db": fecha_db,
            "pick_python": est.get("pick", ""), "pick_form": frm.get("pick", ""),
            "pick_claude": combinado["pick_claude"],
            "pick_externo": c.get("pick_externo"), "pick_final": pick_final,
            "prob_local_py": est.get("prob_local"), "prob_empate_py": est.get("prob_empate"), "prob_visit_py": est.get("prob_visitante"),
            "prob_consenso": consenso_svc.resumen_probabilidad_consenso(consenso_est),
            "score_py": est.get("confianza_score", 0) if est.get("ok") else 0,
            "score_form": frm.get("confianza_score", 0) if frm.get("ok") else 0,
            "score_ia": ia.get("confianza") or 0,
            "score_consolidado": score_consolidado, "nivel_ia": combinado["nivel_ia"],
            "confianza_final": combinado["confianza_final"],
            "modulos_consenso": consenso_est.get("detalle", ""),
            "razon_ia": ia.get("razon", ""), "odds_texto": (
                f"{c['local']} @{c['odds_local']} | Emp @{c['odds_empate']} | {c['visitante']} @{c['odds_visit']}"
                if c.get("odds_disponibles") else "Sin odds"
            ),
        })

    baja_confianza = bool(picks_validos) and score_min < UMBRAL_BAJA_CONFIANZA
    return {
        "fecha_display": fecha_display, "fecha_db": fecha_db, "sin_candidatos": False,
        "sin_picks_validos": not picks_validos, "picks": picks_validos,
        "baja_confianza": baja_confianza, "score_min": score_min if picks_validos else None,
        "sobrantes": [
            {"fixture_id": str(s["fixture_id"]), "local": s["local"], "visitante": s["visitante"],
             "liga": s["liga"], "hora_chile": s["hora_chile"]}
            for s in sobrantes
        ],
    }
