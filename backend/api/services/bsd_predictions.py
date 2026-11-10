"""services/bsd_predictions.py — Predicción externa BSD ML (CatBoost) para comparar contra
el consenso propio.

Port de wfb-031 (`Extraer Predicción Externa BSD`) de WF-B — consulta
`/predictions/?status=upcoming` de BSD (modelo CatBoost con 163 features, reentrenado
semanalmente según el comentario original) y matchea el partido por similitud de tokens
(≥4 caracteres, cobertura ≥50% de los tokens del nombre buscado).

Hasta 2026-09-09 este módulo existía completo (con su propio test) pero nunca se llamaba desde
ningún pipeline real: `services/motor.py::ejecutar_modulos()` nunca poblaba
`resultados["bsd_ml"]`, así que el peso `consenso.PESOS_BASE["bsd_ml"]=0.05` siempre caía en 0
real (auditoría de esta sesión). Ahora `validar_bsd`/`analizar` siguen el mismo patrón que
h2h.py/odds.py/tabla_pos.py (`validar_*(d)` decide si el módulo corre, `analizar(d)` lo
convierte al shape que espera `consenso.calcular_consenso`) — la llamada HTTP real
(`obtener_prediccion_externa_bsd`) se resuelve UPSTREAM, en `services/analisis_completo.py`,
en paralelo con standings/odds/H2H vía `asyncio.gather` (motor.py sigue siendo síncrono, sin
I/O propio, igual que los otros 3 módulos condicionales).
"""
from __future__ import annotations

import logging
import re
import unicodedata

import httpx

from backend.api.core.config import settings
from backend.api.services._http_retry import get_con_reintento_429
from backend.api.services._matematica import clamp as _clamp
from backend.api.services._matematica import safe_float as _safe_float
from backend.api.services.normalizacion import nombre_equipo_bsd

log = logging.getLogger("laplace.bsd_predictions")

BSD_BASE = "https://sports.bzzoiro.com/api/v2"


def _tokens(nombre: str) -> list[str]:
    nfkd = unicodedata.normalize("NFKD", nombre or "")
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]", " ", sin_acentos.lower())
    return [t for t in limpio.split() if len(t) >= 4]


def _score_tokens(a: str, b: str) -> float:
    """Cobertura de los tokens de `a` por los de `b`, con tokens EXACTOS.

    Antes `t in x or x in t` (substring) hacía casar «inter» con «internazionale» pero también
    nombres distintos que comparten un fragmento. Además, cuando ambos nombres tienen 2+ tokens y
    solo comparten uno («Manchester City» vs «Manchester United», «Real Sociedad» vs «Real
    Madrid») el parecido no identifica al club: se devuelve 0.0 en vez de aceptar una cobertura
    de 50%. Un pick de otro equipo contamina el módulo `bsd_ml` y la puerta de calidad."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    comunes = sum(1 for t in ta if t in tb)
    if comunes == 1 and len(ta) > 1 and len(tb) > 1:
        return 0.0
    return comunes / len(ta)


async def obtener_prediccion_externa_bsd(
    client: httpx.AsyncClient, local: str, visitante: str, fecha: str
) -> dict | None:
    """Devuelve {pick, pick_nombre, confianza_pct, fuente='bsd_ml'} o None si BSD no tiene
    el partido, no hay API key, o la fuente falla."""
    if not settings.BSD_API_KEY:
        return None
    f = (fecha or "").strip()
    fecha_iso = f"{f[:4]}-{f[4:6]}-{f[6:8]}" if (len(f) == 8 and f.isdigit()) else f
    try:
        r = await get_con_reintento_429(
            client, f"{BSD_BASE}/predictions/", log=log, fuente="bsd",
            params={
                "status": "upcoming", "date_from": fecha_iso, "date_to": fecha_iso,
                "recommended": "true", "limit": 50,
            },
            headers={"Authorization": f"Token {settings.BSD_API_KEY}"},
            timeout=12,
        )
        r.raise_for_status()
        predicciones = r.json().get("results", [])
    except Exception:
        log.warning("BSD predictions fallo local=%s visitante=%s", local, visitante, exc_info=True)
        return None

    mejor, mejor_score = None, 0.0
    for p in predicciones:
        evento = p.get("event") or p
        home = nombre_equipo_bsd(evento.get("home_team"))
        away = nombre_equipo_bsd(evento.get("away_team"))
        sl, sv = _score_tokens(local, home), _score_tokens(visitante, away)
        score = (sl + sv) / 2
        if score > mejor_score and sl >= 0.5 and sv >= 0.5:
            mejor_score, mejor = score, p

    if not mejor:
        return None

    outcome = mejor.get("outcome") or mejor.get("predicted_outcome") or ""
    confianza = float(mejor.get("confidence") or mejor.get("confidence_score") or 0)
    if outcome == "home":
        pick, pick_nombre = "Local", local
    elif outcome == "away":
        pick, pick_nombre = "Visitante", visitante
    else:
        pick, pick_nombre = "Empate", "Empate"

    return {
        "disponible": True,
        "pick": pick,
        "pick_nombre": pick_nombre,
        "confianza_pct": round(confianza * 100),
        "fuente": "bsd_ml",
    }


def validar_bsd(d: dict) -> tuple[bool, str]:
    """Chequea si `d` trae una predicción BSD ya resuelta — el fetch HTTP real ocurre upstream
    en `services/analisis_completo.py` (en paralelo con standings/odds/H2H), no acá. Mismo
    criterio de skip que h2h.validar_h2h/odds.validar_odds/tabla_pos.validar_tabla: el módulo
    corre solo si hay datos reales disponibles."""
    bsd = d.get("bsd_prediccion")
    if not bsd or not bsd.get("disponible"):
        return False, "BSD ML no disponible (sin match en BSD, sin API key, o la fuente falló)"
    if bsd.get("pick") not in ("Local", "Empate", "Visitante"):
        return False, f"BSD ML devolvió un pick inválido ({bsd.get('pick')!r})"
    return True, "ok"


def analizar(d: dict) -> dict:
    """Convierte la predicción externa de BSD (pick + confianza_pct del modelo CatBoost, sin
    desglose de probabilidad por resultado) al shape de módulo que espera `consenso.py`.

    Decisión de diseño (bsd_ml nunca estuvo conectado al consenso — no había un mapeo previo
    que preservar): `confianza_pct` se acota a [10,90] y se usa como probabilidad del pick
    elegido; el resto de la masa de probabilidad se reparte en partes iguales entre las otras
    dos opciones. Evita que un solo modelo externo sature el consenso con overconfidence —
    mismo espíritu que el cap [10,95] de `confianza_score` del resto de los módulos."""
    bsd = d["bsd_prediccion"]
    pick = bsd["pick"]
    confianza_score = int(_clamp(round(_safe_float(bsd.get("confianza_pct"), 50)), 10, 90))

    prob_pick = confianza_score / 100.0
    prob_resto = (1.0 - prob_pick) / 2.0
    probs = {"Local": prob_resto, "Empate": prob_resto, "Visitante": prob_resto}
    probs[pick] = prob_pick

    if confianza_score > 60:
        confianza = "ALTA"
    elif confianza_score >= 40:
        confianza = "MEDIA"
    else:
        confianza = "BAJA"

    return {
        "ok": True,
        "fuente": "bsd_ml",
        "pick": pick,
        "prob_local": round(probs["Local"], 4),
        "prob_empate": round(probs["Empate"], 4),
        "prob_visitante": round(probs["Visitante"], 4),
        "over25_prob": None,
        "btts_prob": None,
        "value_bet": False,
        "value_pct": 0.0,
        "confianza_score": confianza_score,
        "confianza": confianza,
        "marcador_probable": None,
        "penalizaciones": [],
        "bonificaciones": [],
        "score_para_claude": (
            f"BSD ML (CatBoost externo): pick {pick} ({confianza_score}% confianza) — "
            f"{bsd.get('pick_nombre', pick)}"
        ),
        "bsd_pick_nombre": bsd.get("pick_nombre"),
        "partido_id": str(d.get("partido_id", "")),
        "local": str(d.get("local", "")),
        "visitante": str(d.get("visitante", "")),
        "liga": str(d.get("liga", "")),
    }
