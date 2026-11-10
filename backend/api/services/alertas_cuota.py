"""services/alertas_cuota.py — decide si avisar que quedan pocos créditos de The Odds API."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.api.db.cache import guardar_stats_cache, leer_stats_cache

UMBRAL_CREDITOS_ODDS = 60
_TZ_CHILE = ZoneInfo("America/Santiago")


def debe_alertar_creditos(db: Session, restante: int | float | str | None) -> bool:
    """True una sola vez por día (Chile) cuando `restante` es un número menor al umbral. Marca el día como
    avisado al devolver True; el job corre a diario y sin esto repetiría la alerta en cada corrida."""
    try:
        creditos = float(restante)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if creditos >= UMBRAL_CREDITOS_ODDS:
        return False
    clave = f"alerta_odds_creditos_{datetime.now(_TZ_CHILE).strftime('%Y-%m-%d')}"
    if leer_stats_cache(db, clave) is not None:
        return False
    guardar_stats_cache(db, clave, "alerta_odds_creditos", {"restante": creditos}, ttl_horas_override=24)
    return True
