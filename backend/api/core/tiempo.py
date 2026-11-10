"""Reloj UTC del backend.

El `utcnow()` de datetime está deprecado desde Python 3.12. Todo el esquema guarda fechas UTC
ingenuas (sin tzinfo) como texto, así que el helper conserva exactamente ese valor.
"""
from datetime import datetime, timezone


def utc_ahora() -> datetime:
    """Ahora en UTC como datetime ingenuo (sin tzinfo), igual que el antiguo `utcnow()`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
