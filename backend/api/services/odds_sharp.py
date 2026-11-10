"""
services/odds_sharp.py — Odds de casas sharps (Pinnacle/SBOBet/Singbet) vía OddsPapi.

Port de odds_sharp.py. **Corrige la única violación real encontrada de la
regla "nunca import requests"** — el original usaba `import requests` (con instrucción de
`pip install requests` si faltaba, contradiciendo la regla del propio proyecto); acá usa
`httpx.AsyncClient`, consistente con el resto del backend FastAPI.

Mismo umbral de value (VALUE_UMBRAL=5.0pp), mismo orden de preferencia de bookmakers.
Solo se debería llamar para partidos candidatos (score >= 65) — ver
`.claude/rules/database-safety.md`/lógica de cuota en `services/motor.py` cuando se integre
(hoy no está conectado al motor todavía, ver nota al final).
"""
from __future__ import annotations

import logging

import httpx

from backend.api.core.config import settings
from backend.api.services.normalizacion import normalizar_nombre

log = logging.getLogger("laplace.odds_sharp")

BASE_URL = "https://api.oddspapi.io"
VALUE_UMBRAL = 5.0
SHARPS_PREFERENCIA = ["pinnacle", "singbet", "sbobet", "betfair_exchange"]


def _coincide(a: str, b: str) -> bool:
    na, nb = normalizar_nombre(a), normalizar_nombre(b)
    if na == nb:
        return True
    if len(na) >= 5 and len(nb) >= 5 and (na in nb or nb in na):
        return True
    wa = [w for w in na.split() if len(w) >= 4]
    wb = [w for w in nb.split() if len(w) >= 4]
    return bool(wa and wb and wa[0] == wb[0])


def _safe_float(val, default=None):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def calcular_prob_impl(odds_l: float, odds_e: float, odds_v: float) -> tuple[float, float, float, float]:
    p_l, p_e, p_v = 1.0 / odds_l, 1.0 / odds_e, 1.0 / odds_v
    overround = p_l + p_e + p_v
    return (round(p_l / overround, 4), round(p_e / overround, 4), round(p_v / overround, 4), round(overround, 4))


async def _buscar_partido(client: httpx.AsyncClient, local: str, visitante: str, fecha: str):
    headers = {"Authorization": f"Bearer {settings.oddspapi_sharp_key}", "Content-Type": "application/json"}

    for sharp in SHARPS_PREFERENCIA:
        params = {"bookmaker_slug": sharp, "market": "1x2", "date_from": fecha, "date_to": fecha, "limit": 100}
        try:
            r = await client.get(f"{BASE_URL}/v1/odds/", headers=headers, params=params, timeout=10)
        except Exception as exc:
            log.warning("odds_sharp: consulta a la casa sharp falló: %s", exc)
            continue
        if r.status_code == 401:
            return None, None, "API key inválida (401)"
        if r.status_code == 429:
            return None, None, "Límite de requests alcanzado (429)"
        if r.status_code != 200:
            continue

        data = r.json()
        items = data.get("results", data if isinstance(data, list) else [])
        for item in items:
            home = (item.get("home_team") or item.get("home") or (item.get("event") or {}).get("home_team") or "")
            away = (item.get("away_team") or item.get("away") or (item.get("event") or {}).get("away_team") or "")
            home = home.get("name", "") if isinstance(home, dict) else home
            away = away.get("name", "") if isinstance(away, dict) else away

            if not (_coincide(home, local) and _coincide(away, visitante)):
                continue

            odds_raw = item.get("odds") or item.get("values") or {}
            if isinstance(odds_raw, list):
                odds_map = {}
                for o in odds_raw:
                    name = str(o.get("outcome") or o.get("name") or "").lower()
                    val = _safe_float(o.get("decimal") or o.get("odd") or o.get("price"))
                    if "home" in name or "local" in name or name == "1":
                        odds_map["home"] = val
                    elif "draw" in name or "empate" in name or name == "x":
                        odds_map["draw"] = val
                    elif "away" in name or "visit" in name or name == "2":
                        odds_map["away"] = val
                odds_raw = odds_map

            oh = _safe_float(odds_raw.get("home") or odds_raw.get("1") or odds_raw.get("home_win"))
            od = _safe_float(odds_raw.get("draw") or odds_raw.get("x") or odds_raw.get("draw_win"))
            oa = _safe_float(odds_raw.get("away") or odds_raw.get("2") or odds_raw.get("away_win"))

            if oh and od and oa and oh > 1.0 and od > 1.0 and oa > 1.0:
                return sharp, {"home": oh, "draw": od, "away": oa}, None

    return None, None, "Partido no encontrado en OddsPapi"


def _calcular_divergencia(prob_impl_l, prob_impl_e, prob_impl_v, prob_p_l, prob_p_e, prob_p_v, pick_poisson):
    divs = {}
    if prob_p_l is not None:
        divs["Local"] = round((prob_p_l - prob_impl_l) * 100, 2)
    if prob_p_e is not None:
        divs["Empate"] = round((prob_p_e - prob_impl_e) * 100, 2)
    if prob_p_v is not None:
        divs["Visitante"] = round((prob_p_v - prob_impl_v) * 100, 2)

    if not divs:
        return None, 0.0, False

    value_pick = max(divs, key=divs.get)
    value_pct = divs[value_pick]
    value_signal = value_pct >= VALUE_UMBRAL and (pick_poisson is None or value_pick == pick_poisson)
    return value_pick, value_pct, value_signal


async def obtener_odds_sharp(
    client: httpx.AsyncClient,
    local: str,
    visitante: str,
    fecha: str,
    prob_poisson: dict | None = None,
    pick_poisson: str | None = None,
) -> dict:
    """Consulta OddsPapi para un partido puntual — llamar solo para candidatos de score
    alto (>=65), preserva el límite de 250 req/mes (ver docstring del módulo)."""
    if not settings.oddspapi_sharp_key:
        return {"ok": True, "found": False, "motivo": "ODDSPAPI_SHARP_KEY no configurada", "fuente": "oddspapi"}

    bookmaker, odds_dict, error = await _buscar_partido(client, local, visitante, fecha)
    if not odds_dict:
        return {"ok": True, "found": False, "motivo": error, "fuente": "oddspapi"}

    prob_l, prob_e, prob_v, overround = calcular_prob_impl(odds_dict["home"], odds_dict["draw"], odds_dict["away"])

    prob_poisson = prob_poisson or {}
    value_pick, value_pct, value_signal = _calcular_divergencia(
        prob_l, prob_e, prob_v,
        prob_poisson.get("local"), prob_poisson.get("empate"), prob_poisson.get("visitante"),
        pick_poisson,
    )

    return {
        "ok": True,
        "found": True,
        "bookmaker": bookmaker,
        "odds_local": odds_dict["home"],
        "odds_empate": odds_dict["draw"],
        "odds_visit": odds_dict["away"],
        "overround": overround,
        "prob_impl_local": prob_l,
        "prob_impl_empate": prob_e,
        "prob_impl_visit": prob_v,
        "value_pick": value_pick,
        "value_pct": value_pct,
        "value_signal": value_signal,
        "fuente": "oddspapi",
    }
