"""services/modelo_historico.py — módulo `historico` del motor: Dixon-Coles entrenado con histórico.

Usa los artefactos que genera `backend/scripts/evaluar_modelo_historico.py`
(`ml/artefactos/dixon_coles_ligas.json`, opcionalmente `apilador_dc_mercado.json`). Es Python
puro: no necesita numpy/scipy en el servidor. Si los artefactos no existen, o la liga/equipos
no están cubiertos, el módulo simplemente no participa (`validar_historico` devuelve False con
la razón) — nunca inventa una probabilidad.

Por qué existe: en la evaluación walk-forward con 55.557 partidos reales (ver
`EVALUACION_MODELO_HISTORICO_2026-09-29.md`) el Poisson de `pronostico.py` (promedios
de la temporada en curso + ventaja de local fija) quedó claramente por detrás de este modelo
(RPS y log-loss menores en el periodo de prueba) y ambos por detrás del mercado. Con cuotas
disponibles, el apilador combina modelo y mercado.

Cobertura: solo las ligas con histórico descargado (football-data.co.uk: 18 divisiones europeas y 16
países más; NO incluye Chile, Colombia, Arabia Saudita ni Corea — ver `RESUMEN.md`).
La liga se resuelve por nombre; los nombres ambiguos (ej. "Serie B" italiana vs brasileña) se
desambiguan comprobando que AMBOS equipos existan en el modelo de esa liga.
"""
from __future__ import annotations

import difflib
from datetime import date
import json
import logging
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from backend.api.ml import dixon_coles, mercado
from backend.api.services._matematica import safe_float

log = logging.getLogger("laplace.modelo_historico")

DIR_ARTEFACTOS = Path(__file__).resolve().parents[1] / "ml" / "artefactos"
RUTA_TASAS = Path(__file__).resolve().parents[3] / "backend" / "knowledge" / "sports" / "ligas-estadisticas.json"
DIR_ALIAS = Path(__file__).resolve().parents[1] / "ml" / "alias"
RUTA_ALIAS_LIGAS = DIR_ALIAS / "ligas_alias.json"
RUTA_ALIAS_EQUIPOS_VIVO = DIR_ALIAS / "equipos_alias_vivo.json"
RUTA_ALIAS = Path(__file__).resolve().parents[3] / "backend" / "data" / "datos" / "football-data" / "equipos_alias.json"

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
_UMBRAL_DIFFLIB = 0.95
_LARGO_MIN_DIFFLIB = 10
_MAX_CACHE_EQUIPOS = 20000
_MAX_CACHE_LIGAS = 5000
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


def _firma_archivos_modelo() -> tuple[tuple[str, int, int], ...]:
    """Firma de artefactos y aliases para detectar regeneraciones sin reiniciar FastAPI."""
    rutas = (
        DIR_ARTEFACTOS / "dixon_coles_ligas.json",
        DIR_ARTEFACTOS / "apilador_dc_mercado.json",
        RUTA_ALIAS,
        RUTA_ALIAS_LIGAS,
        RUTA_ALIAS_EQUIPOS_VIVO,
    )
    firma = []
    for ruta in rutas:
        try:
            stat = ruta.stat()
            firma.append((str(ruta), stat.st_mtime_ns, stat.st_size))
        except OSError:
            firma.append((str(ruta), -1, -1))
    return tuple(firma)


def _artefactos() -> dict | None:
    # La caché se indexa por firma: una reconstrucción de modelos o aliases en disco pasa a
    # estar disponible en el proceso activo en la siguiente consulta, sin reiniciar el backend.
    return _cargar_artefactos(_firma_archivos_modelo())


@lru_cache(maxsize=2)
def _cargar_artefactos(_firma: tuple[tuple[str, int, int], ...]) -> dict | None:
    ruta = DIR_ARTEFACTOS / "dixon_coles_ligas.json"
    if not ruta.exists():
        return None
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        ligas = {c: dixon_coles.ModeloLiga.de_dict(m) for c, m in crudo["ligas"].items()}
    except (OSError, ValueError, KeyError):
        log.warning("Artefacto de Dixon-Coles ilegible: %s", ruta, exc_info=True)
        return None
    indices = {c: {_normalizar(e): e for e in m.ataque} for c, m in ligas.items()}
    apilador = None
    ruta_ap = DIR_ARTEFACTOS / "apilador_dc_mercado.json"
    if ruta_ap.exists():
        try:
            apilador = json.loads(ruta_ap.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Artefacto del apilador ilegible: %s", ruta_ap, exc_info=True)
    return {"version": crudo.get("version"), "ligas": ligas, "indices": indices, "apilador": apilador,
            "estructura": {c: [(e, _analizar_nombre(e)) for e in m.ataque] for c, m in ligas.items()},
            "alias": _alias_por_liga(), "tabla_ligas": _tabla_ligas(),
            "cache_equipos": {}, "cache_ligas": {}}


# Compatibilidad con el mecanismo de aislamiento de tests y herramientas de diagnóstico.
_artefactos.cache_clear = _cargar_artefactos.cache_clear  # type: ignore[attr-defined]


def _leer_json(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _alias_por_liga() -> dict[str, dict[str, str]]:
    """{liga: {nombre_normalizado_alternativo: nombre_canonico}} desde `equipos_alias.json` (histórico) y
    `ml/alias/equipos_alias_vivo.json` (nombres como los escriben las fuentes en vivo). La clave "*" del
    segundo vale para cualquier liga; el canónico se valida contra el modelo de la liga al resolver."""
    unido: dict[str, dict[str, str]] = {}
    for crudo in (_leer_json(RUTA_ALIAS).get("mapeo", {}), _leer_json(RUTA_ALIAS_EQUIPOS_VIVO).get("mapeo", {})):
        for liga, pares in crudo.items():
            destino = unido.setdefault(liga, {})
            for orig, canon in pares.items():
                destino[_normalizar(orig)] = canon
    return unido


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


def _tabla_ligas() -> dict:
    """Tabla declarativa de ligas (`ml/alias/ligas_alias.json`) + `LIGAS_POR_NOMBRE` como respaldo."""
    crudo = _leer_json(RUTA_ALIAS_LIGAS)
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


def ligas_candidatas(d: dict) -> list[str]:
    """Códigos de liga del histórico (presentes en el artefacto) que podrían corresponder al partido,
    solo por liga/país/id: aún falta validar los equipos (`validar_historico`)."""
    art = _artefactos()
    if art is None:
        return []
    clave = (_acotar(d.get("liga", "")), _acotar(d.get("pais")), _acotar(d.get("liga_id")))
    if clave not in art["cache_ligas"]:
        if len(art["cache_ligas"]) >= _MAX_CACHE_LIGAS:
            art["cache_ligas"].clear()
        art["cache_ligas"][clave] = _calcular_ligas_candidatas(art, d)
    return art["cache_ligas"][clave]


def _resolver(d: dict) -> tuple[str, dixon_coles.ModeloLiga, str, str] | tuple[None, str]:
    art = _artefactos()
    if art is None:
        return None, "Sin artefactos del modelo histórico (correr evaluar_modelo_historico.py)"
    for codigo in ligas_candidatas(d):
        local = _resolver_equipo(art, codigo, _acotar(d.get("local", "")))
        visitante = _resolver_equipo(art, codigo, _acotar(d.get("visitante", ""))) if local else None
        if local and visitante and local != visitante:
            return codigo, art["ligas"][codigo], local, visitante
    return None, "Liga o equipos fuera de la cobertura del histórico"


# Prior de un equipo ausente del ajuste (ascendido o recién llegado), medido por
# `backend/scripts/evaluar_equipo_nuevo.py` con el periodo de desarrollo (< 2023-07-01) y evaluado en el de
# prueba: con UN equipo desconocido (877 partidos) RPS 0,2198 vs 0,2293 de la tasa base; con AMBOS desconocidos
# (98 partidos) no mejora a la tasa base (0,2196 vs 0,2184) y por eso no se usa. El mercado sigue ganando
# (0,2035 vs 0,2162 en los 326 con cuotas): con cuotas reales se usa solo el mercado y este camino no corre.
PRIOR_EQUIPO_NUEVO_ATAQUE = -0.0725
PRIOR_EQUIPO_NUEVO_DEFENSA = -0.0465
_NOMBRE_EQUIPO_NUEVO = "(equipo sin historial)"


def _hay_candidato_ambiguo(art: dict, codigo: str, nombre: str) -> bool:
    """Un nombre que encaja con algún equipo del modelo pero no se pudo resolver es AMBIGUO (o una errata
    cercana), no un equipo nuevo: tratarlo como promedio sería inventar que no conocemos a un equipo conocido."""
    consulta = _analizar_nombre(nombre)
    if not consulta.norm:
        return True
    if any(_compatibles(consulta, n) for _, n in art["estructura"][codigo]):
        return True
    return len(consulta.norm) < 4


def _resolver_equipo_nuevo(d: dict) -> tuple[str, dixon_coles.ModeloLiga, str | None, str | None] | None:
    """Liga resuelta, exactamente UN equipo resuelto y el otro sin historial claro (ni ambiguo). None si no aplica
    o si hay cuotas reales (con ellas, el mercado solo es lo medido como mejor)."""
    art = _artefactos()
    if art is None or _cuotas(d) is not None:
        return None
    for codigo in ligas_candidatas(d):
        nombres = (_acotar(d.get("local", "")), _acotar(d.get("visitante", "")))
        resueltos = [_resolver_equipo(art, codigo, n) for n in nombres]
        if sum(r is not None for r in resueltos) != 1:
            continue
        faltante = nombres[resueltos.index(None)]
        if _hay_candidato_ambiguo(art, codigo, faltante):
            continue
        return codigo, art["ligas"][codigo], resueltos[0], resueltos[1]
    return None


def validar_historico(d: dict) -> tuple[bool, str]:
    r = _resolver(d)
    if r[0]:
        return True, "ok"
    return (True, "equipo_sin_historial") if _resolver_equipo_nuevo(d) else (False, r[1])


def _cuotas(d: dict) -> tuple[float, float, float] | None:
    h, e, a = (safe_float(d.get(k), 0.0, finito=True) for k in ("odds_local", "odds_empate", "odds_visit"))
    return (h, e, a) if d.get("odds_disponibles") and mercado.cuotas_validas(h, e, a) else None


def _apilar(apilador: dict, pd_: tuple[float, float, float], pm: tuple[float, float, float]) -> tuple[float, float, float]:
    x = [math.log(pd_[0] / pd_[1]), math.log(pd_[2] / pd_[1]), math.log(pm[0] / pm[1]), math.log(pm[2] / pm[1])]
    z = [b + sum(c * v for c, v in zip(fila, x)) for fila, b in zip(apilador["coef"], apilador["intercepto"])]
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return e[0] / s, e[1] / s, e[2] / s


def analizar(d: dict) -> dict:
    """Mismo contrato que los demás módulos: `ok`, `pick`, `prob_*`, `confianza_score`. Con cuotas
    reales del partido combina modelo y mercado (apilador); sin ellas usa solo Dixon-Coles."""
    r = _resolver(d)
    equipo_nuevo = False
    if not r[0]:
        nuevo = _resolver_equipo_nuevo(d)
        if not nuevo:
            return {"ok": False, "razon": r[1]}
        r, equipo_nuevo = nuevo, True
    codigo, modelo, local, visitante = r  # type: ignore[misc]
    lam_h, lam_a, _ = dixon_coles.lambdas(modelo, local or _NOMBRE_EQUIPO_NUEVO, visitante or _NOMBRE_EQUIPO_NUEVO)
    if equipo_nuevo:
        if local is None:
            lam_h, lam_a = lam_h * math.exp(PRIOR_EQUIPO_NUEVO_ATAQUE), lam_a * math.exp(-PRIOR_EQUIPO_NUEVO_DEFENSA)
        else:
            lam_a, lam_h = lam_a * math.exp(PRIOR_EQUIPO_NUEVO_ATAQUE), lam_h * math.exp(-PRIOR_EQUIPO_NUEVO_DEFENSA)
    probs = dixon_coles.probabilidades_desde_lambdas(lam_h, lam_a, modelo.rho)
    metodo = "dixon_coles_equipo_nuevo" if equipo_nuevo else "dixon_coles"

    art = _artefactos()
    cuotas = _cuotas(d)
    if cuotas and art and art.get("apilador"):
        probs = _apilar(art["apilador"], probs, mercado.quitar_margen_shin(*cuotas))
        metodo = "dc_mas_mercado"

    etiquetas = ("Local", "Empate", "Visitante")
    mejor = max(range(3), key=lambda i: probs[i])
    confianza_score = int(max(25, min(80, 40 + 100 * (probs[mejor] - 1 / 3))))
    # Antigüedad de los ratings (2026-10-07). Medido con datos reales (14 ligas, cortes 2019/2021/2022):
    # sin reajustar, Dixon-Coles sigue superando a la tasa base incluso a 3 años (RPS 0,2141 vs 0,2263),
    # pero pierde ~0,005 de RPS frente a reajustarlo. Sirve, pero la confianza baja y se avisa.
    edad_dias = (date.today().toordinal() - modelo.fecha_corte) if modelo.fecha_corte else None
    if edad_dias is not None and edad_dias > 730:
        confianza_score = max(25, confianza_score - 10)
    elif edad_dias is not None and edad_dias > 365:
        confianza_score = max(25, confianza_score - 5)
    if equipo_nuevo:
        # Un solo equipo conocido: la fuerza del otro es un promedio de equipos nuevos, no un dato suyo.
        confianza_score = min(confianza_score, 35)
    return {
        "ok": True, "modulo": "historico", "metodo": metodo, "liga_codigo": codigo, "equipo_sin_historial": equipo_nuevo,
        "edad_modelo_dias": edad_dias, "modelo_desactualizado": bool(edad_dias is not None and edad_dias > 365),
        "pick": etiquetas[mejor],
        "prob_local": round(probs[0], 4), "prob_empate": round(probs[1], 4), "prob_visitante": round(probs[2], 4),
        "lambda_local": round(lam_h, 3), "lambda_visit": round(lam_a, 3),
        "muestra_ajuste": modelo.n_partidos,
        "confianza_score": confianza_score,
        "confianza": "ALTA" if confianza_score >= 65 else "MEDIA" if confianza_score >= 45 else "BAJA",
    }


@lru_cache(maxsize=1)
def _tasas_por_liga() -> dict[str, dict]:
    """{codigo_liga: metadata} de `knowledge/sports/ligas-estadisticas.json` (lo genera
    `backend/scripts/generar_conocimiento_ligas.py` con datos reales medidos)."""
    try:
        entradas = json.loads(RUTA_TASAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {e["metadata"]["liga_codigo"]: e["metadata"] for e in entradas if "liga_codigo" in e.get("metadata", {})}


def tasas_base_liga(d: dict) -> dict | None:
    """Tasas históricas reales de la liga del partido, o None si la liga no está cubierta.

    Solo se devuelven cuando AMBOS equipos se reconocen en esa liga (`_resolver`), así una
    "Serie B" brasileña nunca recibe las tasas de la italiana solo por compartir nombre."""
    r = _resolver(d)
    return _tasas_por_liga().get(r[0]) if r[0] else None


def resumen_tasa_base(d: dict) -> dict | None:
    """Tasas históricas reales de la liga del partido en forma lista para mostrar al usuario (web, app,
    Telegram), o None si la liga no está cubierta o los equipos no se reconocen. Nunca inventa."""
    meta = tasas_base_liga(d)
    if not meta:
        return None
    return {
        "liga_codigo": meta.get("liga_codigo"), "partidos": meta.get("partidos"), "temporadas": meta.get("temporadas"),
        "pct_local": meta.get("pct_local"), "pct_empate": meta.get("pct_empate"), "pct_visitante": meta.get("pct_visitante"),
        "goles_por_partido": meta.get("goles_por_partido"), "fuente": "football-data.co.uk (histórico medido)",
    }


# Promedio mundial medido de resultados de fútbol (documentado en `form_recent.py`): último recurso cuando ni
# siquiera la liga se reconoce. Se rotula como "general", nunca como dato de esa liga.
_TASA_GENERAL_RESPALDO = {"pct_local": 44.1, "pct_empate": 26.3, "pct_visitante": 29.6}


def _tasa_general() -> dict:
    """Promedio ponderado por partidos de todas las ligas con conocimiento medido; el respaldo fijo si no hay."""
    tasas = _tasas_por_liga().values()
    total = sum(t.get("partidos") or 0 for t in tasas)
    if not total:
        return {**_TASA_GENERAL_RESPALDO, "partidos": None}
    return {
        **{k: round(sum((t.get(k) or 0) * (t.get("partidos") or 0) for t in tasas) / total, 1) for k in _TASA_GENERAL_RESPALDO},
        "partidos": total,
    }


def referencia_sin_pronostico(d: dict) -> dict:
    """Contexto honesto cuando no hay pronóstico propio: frecuencias históricas de la liga del partido (basta con
    reconocer la liga, no hace falta conocer a los equipos) o, si ni la liga se reconoce, el promedio general.
    Es una REFERENCIA, no un pronóstico: no distingue a los dos equipos. Siempre devuelve algo."""
    candidatas = ligas_candidatas(d)
    meta = _tasas_por_liga().get(candidatas[0]) if len(candidatas) == 1 else None
    if meta:
        return {
            "nivel": "liga", "liga_codigo": meta.get("liga_codigo"), "partidos": meta.get("partidos"),
            "pct_local": meta.get("pct_local"), "pct_empate": meta.get("pct_empate"),
            "pct_visitante": meta.get("pct_visitante"), "datos_hasta": meta.get("datos_hasta"),
            "fuente": "football-data.co.uk (histórico medido)",
        }
    return {"nivel": "general", "liga_codigo": None, **_tasa_general(), "datos_hasta": None,
            "fuente": "promedio de las ligas con histórico medido"}


def motivos_sin_historico(d: dict) -> list[str]:
    """Por qué `historico` no pudo responder, en lenguaje llano y sin inventar: sirve para explicar el 'sin pronóstico'."""
    if validar_historico(d)[0]:
        return []
    if _artefactos() is None:
        return ["el modelo histórico no está disponible"]
    if not ligas_candidatas(d):
        return ["la liga no está en el histórico del bot"]
    return ["algún equipo no figura en el histórico de su liga (o son dos equipos nuevos a la vez)"]

