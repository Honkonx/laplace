"""services/fechas_bd.py — Validación única de la clave de fecha de `partidos_dia` (YYYY-MM-DD).

Hallazgo real de la auditoría 2026-10-06: 631 de 5.447 filas de `partidos_dia` tenían claves
como `2026--0-9-`. Origen verificado en código: `gateway._yyyymmdd_to_bd` parte el texto en
[:4]/[4:6]/[6:8] sin validar; si un caller le pasa ya `2026-09-27` (p. ej. `GET
/api/v1/partidos?fecha=2026-09-27`, que no valida el formato) produce `2026--0-9-` y el repo lo
guardaba sin rechazar nada. La clave nunca vuelve a coincidir con una consulta real, así que
esas filas son basura invisible. Esta validación corta el problema en la capa de persistencia.
"""
from __future__ import annotations

import re
from datetime import date

_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_COMPACTA = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


class FechaBdInvalida(ValueError):
    """La fecha no es un día real en formato YYYY-MM-DD (o YYYYMMDD, que se convierte)."""


def normalizar_fecha_bd(fecha: object) -> str:
    """Devuelve `YYYY-MM-DD` si `fecha` es un día real de calendario en formato ISO o compacto
    (`YYYYMMDD`, el formato de la cascada de fixtures); si no, lanza `FechaBdInvalida` con un
    mensaje que dice qué llegó. Nunca devuelve un valor sin validar."""
    texto = str(fecha if fecha is not None else "").strip()
    coincidencia = _RE_ISO.match(texto) or _RE_COMPACTA.match(texto)
    if not coincidencia:
        raise FechaBdInvalida(f"fecha inválida {texto!r}: se esperaba YYYY-MM-DD (o YYYYMMDD)")
    anio, mes, dia = (int(g) for g in coincidencia.groups())
    try:
        return date(anio, mes, dia).isoformat()
    except ValueError as exc:
        raise FechaBdInvalida(f"fecha inválida {texto!r}: no existe en el calendario") from exc


def es_fecha_bd_valida(fecha: object) -> bool:
    try:
        normalizar_fecha_bd(fecha)
    except FechaBdInvalida:
        return False
    return True
