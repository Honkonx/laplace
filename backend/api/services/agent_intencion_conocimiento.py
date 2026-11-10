"""Enrutamiento de intención del agente hacia las herramientas `knowledge.*`.

Recibe el mensaje ya sin tildes ni mayúsculas (`agent_runtime._texto_normalizado`) y decide si es una
consulta de glosario, de liga o de equipo. Es conservador: sin una pista clara («qué significa»,
«cómo viene», «tasas base») no enruta, para no secuestrar conversaciones que no son de este tipo.
Un equipo solo se enruta si existe en los perfiles (o es ambiguo y hay que preguntar).
"""
from __future__ import annotations

import re

from backend.api.services import conocimiento_equipos, conocimiento_referencia as ref

PUNTOS_FAQ_SIN_PISTA = 20.0
PUNTOS_CON_PISTA = 12.0
_DEFINICION = re.compile(
    r"\b(?:que (?:significa|significan|es|son|quiere decir|quieren decir)|significado de|define|definicion de|definime|"
    r"explica(?:me)?(?: que (?:es|son|significa))?|como (?:se )?(?:lee|leo|interpreto|interpreta|interpretar|funciona|calculan?)|para que sirve)\b")
_LIGA = re.compile(
    r"\b(?:tasas? base|goles por partido|promedio de goles|cuantos goles|estadisticas de la|perfil de la|como es la|como viene la|"
    r"datos de la|cuanto empata|tan goleadora|tan empatadora)\b")
_COBERTURA = re.compile(r"\b(?:cubres|cubren|cobertura|tienes datos|tienen datos|hay datos)\b")
_EQUIPO = re.compile(
    r"\b(?:como (?:viene|vienen|anda|andan|va|le va|juega|rinde|esta)|perfil (?:de|del)|forma (?:de|del|actual de)|racha (?:de|del)|"
    r"ultimos partidos (?:de|del)|estadisticas (?:de|del)|rendimiento (?:de|del)|datos (?:de|del)|info(?:rmacion)? (?:de|del|sobre)|"
    r"cuentame (?:de|sobre)|hablame (?:de|sobre))\b")
_COLA = re.compile(r"\b(?:hoy|ahora|actualmente|ultimamente|esta temporada|este ano|por favor|gracias)\b")
_ARTICULO = re.compile(r"^(?:el|la|los|las|equipo|club|del|de|al)\s+")


def _colas_equipo(texto: str) -> list[str]:
    """Nombres posibles que siguen a la pista: «perfil de la U» -> «la u» (apodo) y «u» (sin artículo)."""
    coincidencia = _EQUIPO.search(texto)
    if coincidencia is None:
        return []
    nombre = _COLA.sub(" ", texto[coincidencia.end():]).strip(" ?!.,")
    sin_articulo = nombre
    while (recortado := _ARTICULO.sub("", sin_articulo)) != sin_articulo:
        sin_articulo = recortado
    return [n for n in dict.fromkeys((nombre.strip(), sin_articulo.strip())) if n]


def consulta_conocimiento(texto: str, *, hay_partido: bool = False) -> tuple[str, dict] | None:
    """(herramienta, argumentos) si el mensaje pide glosario, liga o equipo; None si no."""
    if not texto.strip():
        return None
    mejor = ref.fragmentos_referencia(texto, 1)
    puntos = mejor[0]["puntos"] if mejor else 0.0
    if _DEFINICION.search(texto) and puntos >= PUNTOS_CON_PISTA:
        return "knowledge.glossary", {"term": texto}
    if _LIGA.search(texto) and ref.detectar_ligas(texto).codigos:
        return "knowledge.league_profile", {"league": texto}
    if _COBERTURA.search(texto) and re.search(r"\bliga (?:de|del) \w+", texto):
        return "knowledge.league_profile", {"league": texto}
    for nombre in [] if hay_partido else _colas_equipo(texto):
        if conocimiento_equipos.resolver_equipo(nombre)["estado"] != "no_encontrado":
            return "knowledge.team_profile", {"team": nombre}
    if puntos >= PUNTOS_FAQ_SIN_PISTA and not hay_partido:
        return "knowledge.glossary", {"term": texto}
    return None
