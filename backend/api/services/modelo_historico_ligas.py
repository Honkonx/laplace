"""services/modelo_historico_ligas.py — resolución de la liga de un partido a códigos del histórico.

Sin acceso a archivos: la tabla declarativa llega ya leída (`construir_tabla_ligas`) y los artefactos como
diccionario. Lo reexporta `modelo_historico`, que es quien lee los archivos.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from backend.api.services.modelo_historico_nombres import _acotar

log = logging.getLogger("laplace.modelo_historico")

# Nombre de liga (minúsculas, sin acentos) → códigos candidatos del histórico, en orden de prioridad.
LIGAS_POR_NOMBRE: dict[str, tuple[str, ...]] = {
    # Europa (football-data.co.uk, /mmz4281/)
    "premier league": ("E0",), "championship": ("E1",), "league one": ("E2",), "league two": ("E3",),
    "laliga": ("SP1",), "la liga": ("SP1",), "primera division": ("SP1", "ARG"),
    "laliga 2": ("SP2",), "la liga 2": ("SP2",), "segunda division": ("SP2",), "laliga hypermotion": ("SP2",),
    "serie a": ("I1", "BRA"), "serie b": ("I2",),
    "bundesliga": ("D1", "AUT"), "2. bundesliga": ("D2",), "bundesliga 2": ("D2",),
    "ligue 1": ("F1",), "ligue 2": ("F2",),
    "eredivisie": ("N1",), "pro league": ("B1",), "jupiler": ("B1",),
    "primeira liga": ("P1",), "super lig": ("T1",), "super league": ("G1", "SWZ", "CHN"),
    "premiership": ("SC0",), "scottish premiership": ("SC0",),
    # Resto del mundo (football-data.co.uk, /new/) — los nombres ambiguos se desambiguan por equipos
    "liga profesional": ("ARG",), "brasileirao": ("BRA",), "campeonato brasileiro": ("BRA",),
    "mls": ("USA",), "major league soccer": ("USA",), "liga mx": ("MEX",),
    "j1 league": ("JPN",), "j league": ("JPN",), "chinese super league": ("CHN",),
    "allsvenskan": ("SWE",), "eliteserien": ("NOR",), "superliga": ("DNK",), "superligaen": ("DNK",),
    "veikkausliiga": ("FIN",), "ekstraklasa": ("POL",), "liga i": ("ROU",), "superliga romania": ("ROU",),
    "premier league russia": ("RUS",), "russian premier league": ("RUS",),
    "premier division": ("IRL",), "league of ireland": ("IRL",), "austrian bundesliga": ("AUT",),
}
_MAX_CACHE_LIGAS = 5000


# --- Resolución de liga -------------------------------------------------------------------------

_FASES = re.compile(
    r"\b(apertura|clausura|group|grupo|round|ronda|regular season|temporada regular|playoffs?|play offs?|"
    r"promotion|relegation|final stage|qualification|qualifying|stage|phase|fase|championship round|"
    r"championship group|league phase|20\d\d)\b.*$")
# Competiciones que nunca deben resolver a una liga masculina absoluta del histórico.
_EXCLUIR_LIGA = re.compile(
    r"\b(women|womens|femenin\w*|femenil|feminin\w*|frauen|femminile|ladies|girls|u1[5-9]|u2[0-3]|youth|juvenil\w*|"
    r"reserves?|primavera|amateur|next pro|friendlies|cup|copa|trophy|pokal)\b")
_PAREN = re.compile(r"\(([^)]*)\)")


def _normalizar_liga(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9. ]", " ", plano)).strip()


def _variantes_liga(nombre: str) -> tuple[list[str], str]:
    """Formas de buscar el nombre de una liga (completo, sin fase, sin país entre paréntesis) y el
    país entre paréntesis si lo hay: 'Serie A (Brazil)' -> (['serie a'], 'brazil')."""
    pais = " ".join(_normalizar_liga(m) for m in _PAREN.findall(nombre or ""))
    sin_paren = _PAREN.sub(" ", nombre or "")
    base = re.split(r":| - ", sin_paren)[0]
    variantes: list[str] = []
    for texto in (sin_paren, base):
        completo = _normalizar_liga(texto)
        for v in (completo, _FASES.sub("", completo)):
            v = re.sub(r"\s+", " ", v).strip(" .")
            if v and v not in variantes:
                variantes.append(v)
    return variantes, pais


def construir_tabla_ligas(crudo: dict) -> dict:
    """Tabla declarativa de ligas (contenido de `ml/alias/ligas_alias.json`) + `LIGAS_POR_NOMBRE` como respaldo."""
    por_nombre: dict[str, list[str]] = {}
    patrones: list[tuple[re.Pattern, str]] = []
    por_id: dict[int, str] = {}
    paises: dict[str, str] = {}
    for entrada in crudo.get("ligas", []):
        codigo = entrada.get("codigo")
        if not codigo:
            continue
        paises[codigo] = _normalizar_liga(entrada.get("pais", ""))
        for nombre in entrada.get("nombres", []):
            lista = por_nombre.setdefault(_normalizar_liga(nombre).strip(" ."), [])
            if codigo not in lista:
                lista.append(codigo)
        for patron in entrada.get("patrones", []):
            try:
                patrones.append((re.compile(patron), codigo))
            except re.error:
                log.warning("Patrón de liga inválido ignorado: %s", patron)
        for liga_id in entrada.get("api_football_id", []):
            por_id[int(liga_id)] = codigo
    for nombre, codigos in LIGAS_POR_NOMBRE.items():
        lista = por_nombre.setdefault(_normalizar_liga(nombre).strip(" ."), [])
        lista.extend(c for c in codigos if c not in lista)
    sinonimos = {_normalizar_liga(k): _normalizar_liga(v) for k, v in crudo.get("sinonimos_pais", {}).items()}
    return {"por_nombre": por_nombre, "patrones": patrones, "por_id": por_id, "paises": paises,
            "sinonimos_pais": sinonimos}


_COMPETICIONES_COMO_PAIS = frozenset({"champions league", "europa league"})


def _entero(valor: object) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _calcular_ligas_candidatas(art: dict, d: dict) -> list[str]:
    tabla = art["tabla_ligas"]
    disponibles = art["ligas"]
    liga_id = _entero(d.get("liga_id"))
    if liga_id in tabla["por_id"]:
        codigo = tabla["por_id"][liga_id]
        return [codigo] if codigo in disponibles else []
    variantes, pais_paren = _variantes_liga(_acotar(d.get("liga", "")))
    if not variantes or _EXCLUIR_LIGA.search(variantes[0]):
        return []
    pais = _normalizar_liga(_acotar(d.get("pais"))) or pais_paren
    pais = tabla["sinonimos_pais"].get(pais, pais)
    if pais in _COMPETICIONES_COMO_PAIS:
        # LiveScore6 manda la competición continental en el campo país y solo la fase en el nombre
        # ("Champions League" / "League Stage"): se invierte para resolverla por su nombre real.
        variantes, pais = [pais], ""
    codigos: list[str] = []
    for v in variantes:
        codigos.extend(tabla["por_nombre"].get(v, ()))
        codigos.extend(c for patron, c in tabla["patrones"] if patron.match(v))
    if pais:
        # Un país conocido que no es el de la liga descarta la coincidencia por nombre: "Championship" o "League One" de
        # Irlanda del Norte, Escocia o China no son los de Inglaterra (medido 2026-10-19 sobre 2.237 partidos programados).
        codigos = [c for c in codigos if tabla["paises"].get(c) in ("", pais, None)]
    return [c for c in dict.fromkeys(codigos) if c in disponibles]
