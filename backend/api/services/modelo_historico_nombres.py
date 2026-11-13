"""services/modelo_historico_nombres.py — normalización y comparación de nombres de equipo del módulo `historico`.

Solo texto: no lee archivos ni conoce los artefactos. Lo reexporta `modelo_historico`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

_RUIDO = re.compile(
    r"\b(fc|cf|ac|as|sc|ssc|afc|cd|ud|sd|real|club|de|del|da|do|dos|y|la|el|the|"
    r"ad|ca|rc|rcd|cs|ss|us|bc|ec|calcio|ssd|sv|vfb|vfl|tsv|fsv|fk|sk|bk|if|ifk|ff|1)\b")


# Variantes de escritura que distintas fuentes usan para lo mismo; se aplican a AMBOS lados
# (nombre del artefacto y nombre consultado), así que no hace falta que coincidan con una forma "oficial".
_SINONIMOS = tuple(
    (re.compile("(?<![a-z0-9])" + patron + "(?![a-z0-9])"), reemplazo)
    for patron, reemplazo in (
        ("los angeles", "la"), ("utd", "united"), ("jrs", "juniors"), ("st", "saint"),
        ("atl", "atletico"), ("dep", "deportivo"), ("ind", "independiente"), ("weds", "wednesday"),
        ("rvs", "rovers"), ("intl", "international"), ("sp", "sporting"), ("man", "manchester"),
        ("cba", "cordoba"), ("nottm", "nottingham"),
    )
)

# Palabras finales que algunas fuentes añaden o quitan ("Cardiff City" = "Cardiff"). Solo se toleran
# de forma unilateral: "Manchester United" y "Manchester City" siguen siendo distintos.
_GENERICOS_FINALES = frozenset({"city", "town", "united", "rovers", "athletic", "albion", "county", "saint", "wanderers"})
# Marcas que distinguen equipos del mismo club (filiales, juveniles, femenino): deben coincidir exactas.
_MARCADORES = frozenset({"b", "ii", "iii", "w", "women", "u17", "u18", "u19", "u20", "u21", "u23", "reserves", "res", "youth"})
# Medido con partidos reales (ver docs): a 0,86 enlazaba clubes distintos (Reggiana/Reggina, Waterford/Watford,
# Atletico GO/Atletico-MG) y no aportaba ningún partido cubierto más que los alias; solo se aceptan erratas
# de una letra en nombres largos.

# Los nombres de liga/equipo pueden venir del cliente (origen "app"). Se acotan antes de normalizar, comparar
# con difflib y usarlos de clave de caché: sin tope, un nombre de megabytes o millones de nombres distintos
# agotaban CPU y memoria del proceso (revisión de seguridad 2026-10-07). Ningún nombre real pasa de ~60.
_MAX_LONGITUD_NOMBRE = 100


def _acotar(valor: object) -> str:
    return str(valor if valor is not None else "")[:_MAX_LONGITUD_NOMBRE]


def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", (texto or "").replace("'", "").replace("’", "")).encode("ascii", "ignore").decode().lower()
    plano = re.sub(r"[^a-z0-9 ]", " ", plano)
    for patron, reemplazo in _SINONIMOS:
        plano = patron.sub(reemplazo, plano)
    limpio = re.sub(r"\s+", " ", _RUIDO.sub(" ", plano)).strip()
    # Un nombre hecho solo de palabras de ruido ("Los Angeles FC" -> "la fc") no debe quedar vacío:
    # un índice con clave "" haría coincidir cualquier consulta vacía con ese equipo.
    return limpio or re.sub(r"\s+", " ", plano).strip()


class _Nombre(NamedTuple):
    core: frozenset[str]
    sufijo: str
    marcas: frozenset[str]
    norm: str


def _fusionar_iniciales(tokens: list[str]) -> list[str]:
    """['estudiantes', 'l', 'p'] -> ['estudiantes', 'lp'] (iniciales sueltas de "L.P.", "G.E.")."""
    salida: list[str] = []
    racha: list[str] = []
    for t in [*tokens, ""]:
        if len(t) == 1 and t.isalpha():
            racha.append(t)
            continue
        salida.extend(["".join(racha)] if len(racha) > 1 else racha)
        racha = []
        if t:
            salida.append(t)
    return salida


def _analizar_nombre(texto: str) -> _Nombre:
    norm = _normalizar(texto)
    tokens = _fusionar_iniciales(norm.split())
    marcas = frozenset(t for t in tokens if t in _MARCADORES)
    tokens = [t for t in tokens if t not in _MARCADORES]
    sufijo = tokens.pop() if len(tokens) > 1 and tokens[-1] in _GENERICOS_FINALES else ""
    return _Nombre(frozenset(tokens), sufijo, marcas, norm)


def _compatibles(a: _Nombre, b: _Nombre) -> bool:
    """Mismo club: núcleo y marcas idénticos y sufijo genérico igual o ausente en alguno de los dos."""
    return a.marcas == b.marcas and a.core == b.core and (a.sufijo == b.sufijo or not a.sufijo or not b.sufijo)
