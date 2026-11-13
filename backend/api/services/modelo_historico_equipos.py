"""services/modelo_historico_equipos.py — resolución de un nombre de equipo contra el modelo de una liga.

Recibe el diccionario de artefactos ya cargado (`art`); la carga y los archivos viven en `modelo_historico`.
"""
from __future__ import annotations

import difflib

from backend.api.services.modelo_historico_nombres import _Nombre, _acotar, _analizar_nombre, _compatibles, _normalizar

# Medido con partidos reales (ver docs): a 0,86 enlazaba clubes distintos (Reggiana/Reggina, Waterford/Watford,
# Atletico GO/Atletico-MG) y no aportaba ningún partido cubierto más que los alias; solo se aceptan erratas
# de una letra en nombres largos.
_UMBRAL_DIFFLIB = 0.95
_LARGO_MIN_DIFFLIB = 10
_MAX_CACHE_EQUIPOS = 20000


def _resolver_equipo(art: dict, codigo: str, nombre: str) -> str | None:
    """Nombre del equipo en el modelo de `codigo`, o None. Nunca adivina: un empate entre candidatos es None."""
    cache = art["cache_equipos"]
    nombre = _acotar(nombre)
    clave = (codigo, nombre)
    if clave not in cache:
        if len(cache) >= _MAX_CACHE_EQUIPOS:
            cache.clear()
        cache[clave] = _buscar_equipo(art, codigo, nombre)
    return cache[clave]


def _buscar_equipo(art: dict, codigo: str, nombre: str) -> str | None:
    indice = art["indices"][codigo]
    consulta = _analizar_nombre(nombre)
    if not consulta.norm:
        return None
    if consulta.norm in indice:
        return indice[consulta.norm]
    for tabla in (art["alias"].get(codigo, {}), art["alias"].get("*", {})):
        canonico = tabla.get(consulta.norm)
        if canonico and _normalizar(canonico) in indice:
            return indice[_normalizar(canonico)]
    candidatos = art["estructura"][codigo]
    mismos = [e for e, n in candidatos if _compatibles(consulta, n)]
    if mismos:
        # "Sheffield" a secas no es "Sheffield United" si el modelo también tiene "Sheffield Weds".
        ambiguo = any(consulta.core < n.core for _, n in candidatos)
        return mismos[0] if len(mismos) == 1 and not ambiguo else None
    return _parecido_unico(art["estructura"][codigo], consulta) if len(consulta.norm) >= _LARGO_MIN_DIFFLIB else None


def _parecido_unico(candidatos: list[tuple[str, _Nombre]], consulta: _Nombre) -> str | None:
    """Último recurso (erratas): similitud de texto ≥ umbral (nombres de 10+ letras), mismas marcas y sufijo no contradictorio,
    y un único ganador claro (el segundo debe quedar al menos 0,03 por debajo)."""
    comparador = difflib.SequenceMatcher(None)
    comparador.set_seq2(consulta.norm)  # difflib cachea la secuencia 2: se reutiliza con todos los candidatos
    puntuados = []
    for equipo, n in candidatos:
        if n.marcas != consulta.marcas or not (n.sufijo == consulta.sufijo or not n.sufijo or not consulta.sufijo):
            continue
        comparador.set_seq1(n.norm)
        if comparador.real_quick_ratio() >= _UMBRAL_DIFFLIB - 0.03 and comparador.quick_ratio() >= _UMBRAL_DIFFLIB - 0.03:
            puntuados.append((comparador.ratio(), equipo))
    puntuados.sort(reverse=True)
    if not puntuados or puntuados[0][0] < _UMBRAL_DIFFLIB:
        return None
    if len(puntuados) > 1 and puntuados[0][0] - puntuados[1][0] < 0.03:
        return None
    return puntuados[0][1]


def _hay_candidato_ambiguo(art: dict, codigo: str, nombre: str) -> bool:
    """Un nombre que encaja con algún equipo del modelo pero no se pudo resolver es AMBIGUO (o una errata
    cercana), no un equipo nuevo: tratarlo como promedio sería inventar que no conocemos a un equipo conocido."""
    consulta = _analizar_nombre(nombre)
    if not consulta.norm:
        return True
    if any(_compatibles(consulta, n) for _, n in art["estructura"][codigo]):
        return True
    return len(consulta.norm) < 4


def unir_alias(crudos: tuple[dict, ...]) -> dict[str, dict[str, str]]:
    """{liga: {nombre_normalizado_alternativo: nombre_canonico}} a partir de los `mapeo` de cada archivo de alias."""
    unido: dict[str, dict[str, str]] = {}
    for crudo in crudos:
        for liga, pares in crudo.items():
            destino = unido.setdefault(liga, {})
            for orig, canon in pares.items():
                destino[_normalizar(orig)] = canon
    return unido
