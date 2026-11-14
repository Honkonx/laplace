"""horario.py — horas del partido: instante UTC, hora local de Chile y la hora que entrega LiveScore.

Dos defectos reales que corrige (medidos el 2026-11-14 sobre la base):
- `services/gateway_fuentes.UTC_OFFSET = -4` fijo todo el año: Chile cambia de hora (en noviembre es UTC−3).
- LiveScore6 entrega `Esd` (AAAAMMDDHHMMSS) en **UTC+7**, no en hora de Chile: los horarios de la Serie A de la base (00:30, 02:45 y 21:00)
  son 17:30, 19:45 y 14:00 UTC. El colector guardaba esa hora como «hora Chile» y dejaba `kick_off_utc` vacío en el 100 % de las filas desde el 2026-11-08.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ_CHILE = ZoneInfo("America/Santiago")
LIVESCORE_UTC_OFFSET_HORAS = 7
FORMATO_UTC = "%Y-%m-%dT%H:%M:%S"
DURACION_PARTIDO_MIN = 140  # 90 de juego + descanso + descuento + margen; la verificación empieza aquí


def a_utc(texto: str | None) -> datetime | None:
    """Lee un instante ISO ('2026-11-14T18:00:00', con o sin 'Z', con o sin espacio) como UTC naive. Devuelve None si no se puede."""
    if not texto:
        return None
    limpio = str(texto).strip().replace(" ", "T").rstrip("Z")[:19]
    try:
        return datetime.strptime(limpio, FORMATO_UTC)
    except ValueError:
        return None


def a_texto_utc(valor: datetime) -> str:
    return valor.strftime(FORMATO_UTC)


def esd_livescore_a_utc(esd: str | None) -> datetime | None:
    """`Esd` de LiveScore6 (AAAAMMDDHHMM[SS], UTC+7) → UTC. None si falta la hora (los 0000 al final de un día sin hora conocida también)."""
    texto = str(esd or "").strip()
    if len(texto) < 12 or not texto[:12].isdigit():
        return None
    try:
        local = datetime.strptime(texto[:12], "%Y%m%d%H%M")
    except ValueError:
        return None
    return local - timedelta(hours=LIVESCORE_UTC_OFFSET_HORAS)


def utc_a_chile(valor: datetime) -> datetime:
    """UTC naive → hora de pared de Chile (con el horario de verano que corresponda a esa fecha)."""
    return valor.replace(tzinfo=timezone.utc).astimezone(TZ_CHILE).replace(tzinfo=None)


def hora_chile(inicio_utc: str | None) -> str:
    """'HH:MM' de Chile para un instante UTC ISO; '' si no hay."""
    valor = a_utc(inicio_utc)
    return utc_a_chile(valor).strftime("%H:%M") if valor else ""


def fecha_chile(inicio_utc: str | None) -> str:
    """'YYYY-MM-DD' de Chile para un instante UTC ISO; '' si no hay."""
    valor = a_utc(inicio_utc)
    return utc_a_chile(valor).strftime("%Y-%m-%d") if valor else ""


def inicio_y_hora_chile(esd: str | None, inicio_utc: str | None = None) -> tuple[str, str]:
    """(inicio UTC ISO, 'HH:MM' de Chile) de un evento: usa el instante UTC si la fuente lo trae y, si no, lo deduce del `Esd` de LiveScore."""
    instante = a_utc(inicio_utc) or esd_livescore_a_utc(esd)
    if instante is None:
        return "", ""
    return a_texto_utc(instante), utc_a_chile(instante).strftime("%H:%M")


def esd_chile_de_timestamp(ts: int) -> str:
    """AAAAMMDDHHMM en hora de Chile para un timestamp (sustituye al desfase fijo de −4)."""
    local = utc_a_chile(datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None))
    return local.strftime("%Y%m%d%H%M")
