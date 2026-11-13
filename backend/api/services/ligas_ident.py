"""services/ligas_ident.py — identidad de una competición: nombre + país, no solo el nombre.

Hallazgo medido el 2026-11-12 sobre la base real: el `liga_slug` se armaba solo con el nombre de la competición, así que «premier-league» juntaba 280 equipos distintos (Inglaterra, Egipto, Israel,
Kazajistán, Kenia, Baréin…), «super-league» 101 y «ligue-1» 68 (Francia tiene 18); «serie-b» mezclaba Italia con Brasil y «league-stage» a la Champions con la Europa League. La fuente SÍ manda el país
(`Cnm` en LiveScore), pero se descartaba al guardar. Aquí está la regla única que usan el guardado, el menú de Telegram, la pasarela de la app y el catálogo de la web.

- `slug_competicion(nombre, pais)`: con país, `premier-league-england`; sin país, el slug de siempre (las filas viejas siguen leyéndose).
- `nombre_visible(nombre, pais)`: «Premier League (Inglaterra)» para que dos competiciones homónimas no se vean iguales (web y PWA muestran el nombre tal cual llega).
- El país se normaliza con los mismos sinónimos que el modelo histórico (`ligas_alias.json`): «Inglaterra» y «England» dan la misma clave.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

LARGO_BASE = 28
LARGO_PAIS = 14
LARGO_LEGADO = 40  # el slug sin país conserva su largo de siempre para no desalinearse con lo ya guardado


def _plano(texto: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", texto or "").lower().strip("-")


@lru_cache(maxsize=1)
def _sinonimos_pais() -> dict[str, str]:
    from backend.api.services import modelo_historico

    try:
        return dict(modelo_historico._tabla_ligas()["sinonimos_pais"])  # noqa: SLF001 — la misma tabla que usa el modelo histórico
    except Exception:  # noqa: BLE001 — sin la tabla, el país se usa tal cual
        return {}


def limpiar_cache() -> None:
    _sinonimos_pais.cache_clear()


def pais_clave(pais: str | None) -> str:
    """Clave estable del país en inglés y minúsculas («inglaterra» y «england» → «england»); cadena vacía si no hay país."""
    from backend.api.services.modelo_historico_ligas import _normalizar_liga  # noqa: SLF001

    crudo = _normalizar_liga(pais or "")
    return _sinonimos_pais().get(crudo, crudo).replace(" ", "-") if crudo else ""


def slug_competicion(nombre: str | None, pais: str | None = None) -> str:
    """Identificador de la competición. Con país queda `<nombre>-<país>` (≤ 43 caracteres: cabe en el `callback_data` de Telegram junto con la fecha)."""
    base = _plano(nombre or "Otras") or "otras"
    clave = pais_clave(pais)
    if not clave:
        return base[:LARGO_LEGADO]
    if len(base) > LARGO_BASE:
        # Un nombre largo se trunca, y «…: Group 1» / «…: Group 2» quedaban con el mismo identificador (4 colisiones medidas en la base real): se agrega un hash corto del nombre COMPLETO.
        base = f"{base[:LARGO_BASE - 5].strip('-')}-{hashlib.sha1(base.encode()).hexdigest()[:4]}"
    return f"{base}-{_plano(clave)[:LARGO_PAIS].strip('-')}"


def nombre_visible(nombre: str | None, pais: str | None = None) -> str:
    """«Premier League (Inglaterra)»; si el nombre ya trae el país («Primera División Argentina»), se deja como está."""
    nombre = (nombre or "").strip() or "Liga"
    pais = (pais or "").strip()
    if not pais or _plano(pais) in _plano(nombre):
        return nombre
    return f"{nombre} ({pais})"
