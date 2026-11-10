"""
services/ligas.py — Tabla unificada de datos por liga (LIGAS) — FUENTE ÚNICA.

Antes vivía duplicada en dos lugares que podían desincronizarse:
  1. pronostico.py (Python, fuente original)
  2. el workflow WF-B v11.8 de n8n (archivado), nodos wfb-014/wfb-015 (JS, "espejo" comentado a mano)

Con la migración a FastAPI, el motor estadístico deja de correr en n8n — este es el único
lugar donde vive la tabla. Valores idénticos a los de pronostico.py (promedios históricos
2022-2025, sin cambios de calibración en el port).

Hasta 2026-09-08 esto eran DOS diccionarios separados (`LIGA_AVG`, ~50 ligas con promedio de
gol; `MAPA_LIGAS`, ~24 ligas con tabla de posiciones + odds key) que había que mantener
sincronizados a mano — ya estaban desincronizados: más de la mitad de las ligas con promedio de
gol no tenían tabla/odds mapeados, y `mapear_liga()` devolvía `(None, None)` en silencio para
esas sin que `get_liga_avg()` (que sí conocía la liga) diera ninguna pista de que el mapeo
estaba incompleto. Unificados acá en una sola estructura por liga (`LIGAS: dict[str, LigaInfo]`)
— `tabla`/`odds` quedan `None` explícito y documentado cuando no hay cobertura real (ninguna
liga pierde el promedio de gol que ya tenía), en vez de una ausencia silenciosa en un dict
aparte.
"""
from __future__ import annotations

from typing import NamedTuple

HOME_ADVANTAGE = 0.35  # goles extra promedio jugando en casa (global)


class LigaInfo(NamedTuple):
    """Datos conocidos de una liga. `avg_goles` siempre tiene un valor real (es la razón de
    ser de la tabla). `tabla` (código de standings de football-data.org) y `odds` (odds_key de
    The Odds API) son `None` explícito cuando esa fuente no cubre la competición — el caller
    (`standings_fetch.py`/`odds_fetch.py`) debe tratar `None` como "no disponible para esta
    liga", no como un bug de mapeo."""

    avg_goles: float
    tabla: str | None = None
    odds: str | None = None


# ─── LIGAS — nombre de liga (clave de matching, lowercase) → LigaInfo ─────────────────────────
# El matching es por substring de la clave más específica (ver `_clave_mas_especifica`), igual
# que el nodo `Mapear Liga` (wfb-007) de WF-B original, salvo que ahora prioriza la clave más
# larga en vez de la primera en orden de inserción (ver docstring de `_clave_mas_especifica`).
# Claves como "la liga" / "laliga" o "saudi pro" / "saudi pro league" conviven a propósito: son
# variantes reales de cómo las distintas fuentes (LiveScore6, BSD, api-football) nombran la
# misma competición, y no son substring una de la otra.
LIGAS: dict[str, LigaInfo] = {
    # Europa top
    # Inalcanzable por diseño — ver CLAVES_AMBIGUAS_EN_ORIGEN más abajo. Se conserva el valor
    # real de Inglaterra documentado, para cuando exista un matching real por league_id.
    "premier league": LigaInfo(2.82, tabla="PL", odds="soccer_epl"),
    "laliga": LigaInfo(2.52, tabla="PD", odds="soccer_spain_la_liga"),
    "la liga": LigaInfo(2.52, tabla="PD", odds="soccer_spain_la_liga"),
    "bundesliga": LigaInfo(3.03, tabla="BL1", odds="soccer_germany_bundesliga"),
    "serie a": LigaInfo(2.67, tabla="SA", odds="soccer_italy_serie_a"),
    "ligue 1": LigaInfo(2.57, tabla="FL1", odds="soccer_france_ligue_one"),
    "eredivisie": LigaInfo(3.07, tabla="DED", odds="soccer_netherlands_eredivisie"),
    "primeira liga": LigaInfo(2.58, tabla=None, odds="soccer_portugal_primeira_liga"),
    "primeira liga portugal": LigaInfo(2.58, tabla=None, odds="soccer_portugal_primeira_liga"),
    "süper lig": LigaInfo(2.74, tabla=None, odds="soccer_turkey_super_league"),
    "super lig": LigaInfo(2.74, tabla=None, odds="soccer_turkey_super_league"),
    # Europa secundaria
    # Inalcanzable por diseño — ver CLAVES_AMBIGUAS_EN_ORIGEN más abajo (hallazgo real
    # 2026-09-09: "Caribbean Club Championship" y "Veikkausliiga: Championship" — la ronda de
    # playoffs finlandesa — matcheaban por substring contra esta clave y recibían el promedio/
    # tabla/odds del Championship inglés real).
    "championship": LigaInfo(2.65, tabla="ELC", odds="soccer_efl_champ"),
    "serie b": LigaInfo(2.47, tabla=None, odds="soccer_brazil_serie_b"),
    "segunda division": LigaInfo(2.45),
    "segunda división": LigaInfo(2.45),
    "ligue 2": LigaInfo(2.41),
    "bundesliga 2": LigaInfo(2.89),
    "2. bundesliga": LigaInfo(2.89),
    "pro league": LigaInfo(2.89),
    "jupiler": LigaInfo(2.89),
    "primeira liga bra": LigaInfo(2.55),
    # Américas
    "mls": LigaInfo(3.02, tabla=None, odds="soccer_usa_mls"),
    "liga mx": LigaInfo(2.71, tabla=None, odds="soccer_mexico_ligamx"),
    "brasileirao": LigaInfo(2.55, tabla=None, odds="soccer_brazil_campeonato"),
    "serie a brasil": LigaInfo(2.55),
    "liga profesional": LigaInfo(2.43, tabla=None, odds="soccer_argentina_primera_division"),
    "liga pro": LigaInfo(2.43),
    "primera division argentina": LigaInfo(2.43),
    "primera división argentina": LigaInfo(2.43),
    # Inalcanzables por diseño — ver CLAVES_AMBIGUAS_EN_ORIGEN más abajo (hallazgo real
    # 2026-09-09: "Primera Division: Apertura" de Panamá y "Women's Liga MX: Apertura" de México
    # matcheaban por substring contra estas claves y recibían el promedio/odds de Argentina —
    # el formato de torneo "Apertura"/"Clausura" es común a varios países latinoamericanos, no
    # exclusivo de Argentina). La clave "liga profesional" (sin este problema) sigue siendo el
    # matching real para Argentina.
    "apertura": LigaInfo(2.43, tabla=None, odds="soccer_argentina_primera_division"),
    "clausura": LigaInfo(2.43, tabla=None, odds="soccer_argentina_primera_division"),
    "campeonato brasileiro": LigaInfo(2.55),
    # Asia / África / MENA
    "saudi pro league": LigaInfo(2.61, tabla=None, odds="soccer_saudi_arabia_pro_league"),
    "saudi pro": LigaInfo(2.61, tabla=None, odds="soccer_saudi_arabia_pro_league"),
    "saudi": LigaInfo(2.61),
    "uae pro league": LigaInfo(2.48),
    "j1 league": LigaInfo(2.61, tabla=None, odds="soccer_japan_j_league"),
    "j-league": LigaInfo(2.61),
    "k league": LigaInfo(2.55),
    "chinese super league": LigaInfo(2.69),
    "csl": LigaInfo(2.69),
    "egypt premier": LigaInfo(2.38),
    "egyptian premier": LigaInfo(2.38),
    "libya premier": LigaInfo(2.31),
    "tunisian": LigaInfo(2.29),
    "moroccan": LigaInfo(2.35),
    "botola": LigaInfo(2.35),
    "algerian": LigaInfo(2.27),
    "nigerian": LigaInfo(2.41),
    # Europa del Este
    "premier liga ukraine": LigaInfo(2.42),
    "ukrainian": LigaInfo(2.42),
    "ekstraklasa": LigaInfo(2.51),
    "czech": LigaInfo(2.63),
    "romanian": LigaInfo(2.48),
    "greek super": LigaInfo(2.45),
    "super league greece": LigaInfo(2.45),
    "scottish": LigaInfo(2.69, tabla=None, odds="soccer_spl"),
    # Competiciones continentales
    "champions league": LigaInfo(2.98, tabla="CL", odds="soccer_uefa_champs_league"),
    "europa league": LigaInfo(2.76, tabla=None, odds="soccer_uefa_europa_league"),
    "conference league": LigaInfo(2.71, tabla=None, odds="soccer_uefa_europa_conference_league"),
    "copa libertadores": LigaInfo(2.57, tabla=None, odds="soccer_conmebol_copa_libertadores"),
    "copa sudamericana": LigaInfo(2.48, tabla=None, odds="soccer_conmebol_copa_sudamericana"),
    # Ligas con cuotas en el plan gratis de The Odds API que antes no estaban mapeadas (verificado en vivo el 2026-10-19
    # contra `GET /v4/sports`, que no cuesta créditos). Solo se resuelven por `league_id` (ID_A_CLAVE_LIGA; la '@' evita que coincidan por texto): su nombre
    # de texto es ambiguo entre países (Serie B, Segunda División, Premier League…).
    "@eliteserien": LigaInfo(3.04, tabla=None, odds="soccer_norway_eliteserien"),
    "@allsvenskan": LigaInfo(2.82, tabla=None, odds="soccer_sweden_allsvenskan"),
    "@superettan": LigaInfo(2.82, tabla=None, odds="soccer_sweden_superettan"),
    "@ekstraklasa": LigaInfo(2.73, tabla=None, odds="soccer_poland_ekstraklasa"),
    "@superliga dinamarca": LigaInfo(3.02, tabla=None, odds="soccer_denmark_superliga"),
    "@bundesliga austria": LigaInfo(2.67, tabla=None, odds="soccer_austria_bundesliga"),
    "@super league suiza": LigaInfo(3.03, tabla=None, odds="soccer_switzerland_superleague"),
    "@super league grecia": LigaInfo(2.66, tabla=None, odds="soccer_greece_super_league"),
    "@jupiler pro league": LigaInfo(2.75, tabla=None, odds="soccer_belgium_first_div"),
    "@veikkausliiga": LigaInfo(2.93, tabla=None, odds="soccer_finland_veikkausliiga"),
    "@primera division chile": LigaInfo(2.69, tabla=None, odds="soccer_chile_campeonato"),
    "@k league 1": LigaInfo(2.57, tabla=None, odds="soccer_korea_kleague1"),
    "@ligue 2 francia": LigaInfo(2.52, tabla=None, odds="soccer_france_ligue_two"),
    "@bundesliga 2 alemania": LigaInfo(3.02, tabla=None, odds="soccer_germany_bundesliga2"),
    "@serie b italia": LigaInfo(2.52, tabla=None, odds="soccer_italy_serie_b"),
    "@segunda division espana": LigaInfo(2.47, tabla=None, odds="soccer_spain_segunda_division"),
    "@league one inglaterra": LigaInfo(2.6, tabla=None, odds="soccer_england_league1"),
    "@league two inglaterra": LigaInfo(2.68, tabla=None, odds="soccer_england_league2"),
    "@premier division irlanda": LigaInfo(2.44, tabla=None, odds="soccer_league_of_ireland"),
    "@premier league rusia": LigaInfo(2.63, tabla=None, odds="soccer_russia_premier_league"),
    "@super liga china": LigaInfo(3.04, tabla=None, odds="soccer_china_superleague"),
    "@premiership escocia": LigaInfo(2.83, tabla=None, odds="soccer_spl"),
    "@3 liga alemania": LigaInfo(2.6, tabla=None, odds="soccer_germany_liga3"),
}

DEFAULT_LIGA_AVG = 2.60

# ─── Nombres genuinamente ambiguos en el origen de datos — no "arreglables" con más substring
# matching ────────────────────────────────────────────────────────────────────────────────────
# Hallazgo real 2026-09-09, verificado con datos reales del día (backend/scripts/
# verificar_datos_reales.py): LiveScore6 devuelve el MISMO `Snm` ("Premier League") Y el MISMO
# `liga_slug` ("premier-league") para al menos 4 competiciones reales distintas en un solo día:
# Kazajistán (Kairat Almaty vs Zhenis), Bosnia (Zeljeznicar vs FK Sarajevo), Egipto (El Zamalek,
# Pyramids FC, Smouha SC...) y Tanzania (Simba SC, Azam FC). No es un bug de nuestro matching —
# ni siquiera el `liga_slug` (más específico que el nombre libre) distingue estos casos, porque
# la fuente los agrupa igual. Confiar en "premier league" para el promedio de gol/tabla/odds de
# la Premier League inglesa real es, en la práctica, apostar 1 en 4 (o peor) a que sea la liga
# correcta. Se excluye a propósito de la tabla `LIGAS` — el partido cae a DEFAULT_LIGA_AVG en vez
# de un promedio real pero potencialmente equivocado. El fix real (no aplicado esta ronda, ver
# flujo-backend.html) es resolver el `league_id` numérico de
# api-football POR PARTIDO (ya se hace para tabla/odds vía gateway.buscar_fixture_id) antes de
# decidir el promedio de gol, en vez de matchear el nombre de texto libre.
#
# Extendido 2026-09-09 (misma corrida del script, muestra de 10 partidos reales distintos):
# - "championship": "Caribbean Club Championship: Group A" y "Veikkausliiga: Championship"
#   (ronda de playoffs de Finlandia) matcheaban contra el Championship inglés — cualquier
#   competición del mundo que use la palabra "Championship" en su nombre colisiona igual.
# - "apertura" / "clausura": "Primera Division: Apertura" (Panamá) y "Women's Liga MX: Apertura"
#   (México) matcheaban contra el promedio/odds de Argentina — el formato de torneo partido en
#   Apertura/Clausura es común a varios países de Latinoamérica, no exclusivo de Argentina.
#   "liga profesional" (clave real y específica de Argentina) no tiene este problema y se
#   mantiene como matching válido.
CLAVES_AMBIGUAS_EN_ORIGEN = frozenset({"premier league", "championship", "apertura", "clausura"})

# ─── Calificadores que indican "NO es la competición principal" — segundo hallazgo real
# 2026-09-09 ──────────────────────────────────────────────────────────────────────────────────
# Distinto del caso de arriba: acá la fuente SÍ da suficiente información para distinguir (el
# nombre completo es más largo/específico que la clave que matchea), el problema es que
# `_clave_mas_especifica` solo mira si la clave conocida es substring — nunca mira si el resto
# del nombre real dice "esto es otra cosa". Casos reales encontrados: "MLS Next Pro" (liga
# reserva/desarrollo de la MLS, equipos "II" — Toronto FC II, Columbus Crew II) matcheaba contra
# la clave "mls" y recibía el promedio de gol de la MLS titular; "Champions League Path" (fase
# clasificatoria de la UEFA Youth League, equipos U19) matcheaba contra "champions league" y
# recibía el promedio de la Champions League de mayores. Tercer caso real 2026-09-09: "Women's
# Liga MX: Apertura" matcheaba contra la clave "liga mx" (masculina) — el fútbol femenino es una
# competición real y estadísticamente distinta (otro promedio de gol), no una variante menor de
# la masculina. Si CUALQUIERA de estos calificadores aparece en el nombre real, se descarta el
# match salvo que la propia clave que ganó YA incluya ese calificador (para no romper una futura
# entrada específica tipo "mls next pro" si se agrega).
CALIFICADORES_DE_OTRA_COMPETICION = (
    "next pro", "reserves", "reserve", "youth", "academy", " path", "women",
    " ii", " u19", " u20", " u21", " u23", " sub-19", " sub-20", " sub-21", " sub-23",
)


def _clave_mas_especifica(liga_lower: str, claves: "dict[str, object]") -> str | None:
    """Entre todas las claves de `claves` que son substring de `liga_lower` (excluyendo
    `CLAVES_AMBIGUAS_EN_ORIGEN` y descartando matches contra `CALIFICADORES_DE_OTRA_COMPETICION`
    no cubiertos por la clave), devuelve la más larga (más específica). Antes se devolvía la
    PRIMERA en orden de inserción del dict — bug real encontrado 2026-09-08: "serie a" (Italia)
    está insertado antes que "serie a brasil" en `LIGA_AVG`, así que un partido de la Serie A
    brasileña matcheaba contra "serie a" primero y usaba el promedio de gol italiano. Con la
    clave más larga, "serie a brasil" (más específica) gana sobre "serie a" cuando ambas hacen
    match. Ver el registro de decisiones del proyecto 2026-09-08."""
    mejor: str | None = None
    for key in claves:
        if key in CLAVES_AMBIGUAS_EN_ORIGEN:
            continue
        if key not in liga_lower:
            continue
        if any(cal in liga_lower and cal not in key for cal in CALIFICADORES_DE_OTRA_COMPETICION):
            continue
        if mejor is None or len(key) > len(mejor):
            mejor = key
    return mejor


def mapear_liga(liga_nombre: str | None) -> tuple[str | None, str | None]:
    """Devuelve (league_code_standings, odds_key) para el nombre de liga dado, o
    (None, None) si no hay mapeo — mismo criterio que el nodo `Mapear Liga` de WF-B, salvo que
    ahora prioriza la clave más específica en vez de la primera en orden de inserción."""
    liga_lower = (liga_nombre or "").lower()
    key = _clave_mas_especifica(liga_lower, LIGAS)
    if key is None:
        return None, None
    info = LIGAS[key]
    return info.tabla, info.odds


def get_liga_avg(liga_nombre: str | None, liga_avg_input: float) -> float:
    """Resuelve el promedio real de la liga. Prioridad: tabla interna (clave más específica) >
    input si parece razonable > DEFAULT."""
    liga_lower = (liga_nombre or "").lower()
    key = _clave_mas_especifica(liga_lower, LIGAS)
    if key is not None:
        return LIGAS[key].avg_goles
    if 1.8 <= liga_avg_input <= 4.2:
        return liga_avg_input
    return DEFAULT_LIGA_AVG


def es_liga_conocida(liga_nombre: str | None) -> bool:
    """True si `liga_nombre` matchea alguna clave de `LIGAS` (mismo criterio de substring más
    específico que usan `mapear_liga()`/`get_liga_avg()`). Con la tabla unificada, esta única
    consulta ya cubre a la vez "¿hay tabla/odds mapeados?" y "¿el promedio de gol es un dato
    real o un fallback?" — antes había que revisar dos dicts por separado y podían dar
    respuestas inconsistentes.

    Usado por el filtro de calidad de partido de `services/top_picks.py` (`_filtrar_candidatos`)
    para decidir, de forma objetiva y conservadora, si vale la pena gastar cálculo/IA en un
    partido: `not es_liga_conocida(liga)` es exactamente "esta liga no tiene NINGÚN dato de
    referencia real en el sistema" — no un juicio subjetivo de calidad."""
    liga_lower = (liga_nombre or "").lower()
    return _clave_mas_especifica(liga_lower, LIGAS) is not None


# ─── Resolución por league_id numérico (api-football) — el fix de fondo a la ambigüedad de
# texto, 2026-09-09 ─────────────────────────────────────────────────────────────────────────
# Todo el matching de arriba es por nombre de texto libre — inherentemente ambiguo en el origen
# (ver CLAVES_AMBIGUAS_EN_ORIGEN: "Premier League" agrupa Inglaterra/Kazajistán/Bosnia/Egipto/
# Tanzania bajo el mismo texto). El `league_id` NUMÉRICO de api-football, en cambio, ya se
# resuelve por partido (una sola vez, cacheado) vía `gateway.buscar_fixture_id` para tabla/odds
# — este mismo id, cuando se conoce, identifica la competición sin ambigüedad y puede resolver
# también el promedio de gol, evitando el problema de raíz en vez de seguir agregando
# excepciones de texto una por una.
#
# Cobertura deliberadamente conservadora: solo los ids que se pudieron verificar con confianza
# real (mismos ids reales de api-football ya curados a mano en `top_picks.py::LIGA_SLUG_POR_ID`/
# `LIGAS_PREMIUM`/`LIGAS_STANDARD` para la selección de Top Picks, cruzados contra una clave real
# y verificada de `LIGAS`). Un `league_id` real que no está en esta tabla simplemente cae al
# matching por texto de siempre (comportamiento sin cambios) — nunca se inventa un id.
ID_A_CLAVE_LIGA: dict[int, str] = {
    39: "premier league", 140: "laliga", 135: "serie a", 78: "bundesliga",
    61: "ligue 1", 88: "eredivisie", 94: "primeira liga", 203: "super lig",
    307: "saudi pro league", 253: "mls", 262: "liga mx", 71: "brasileirao",
    72: "serie b", 128: "liga profesional", 98: "j1 league", 40: "championship",
    2: "champions league", 3: "europa league", 848: "conference league",
    13: "copa libertadores", 11: "copa sudamericana",
    103: "@eliteserien", 113: "@allsvenskan", 114: "@superettan", 106: "@ekstraklasa", 119: "@superliga dinamarca", 218: "@bundesliga austria", 207: "@super league suiza", 197: "@super league grecia", 144: "@jupiler pro league", 244: "@veikkausliiga", 265: "@primera division chile", 292: "@k league 1", 62: "@ligue 2 francia", 79: "@bundesliga 2 alemania", 136: "@serie b italia", 141: "@segunda division espana", 41: "@league one inglaterra", 42: "@league two inglaterra", 357: "@premier division irlanda", 235: "@premier league rusia", 169: "@super liga china", 179: "@premiership escocia", 80: "@3 liga alemania",
}


def resolver_liga_por_id(
    league_id: int | None, liga_texto: str | None, liga_avg_input: float
) -> tuple[float, str | None, str | None]:
    """Devuelve `(avg_goles, tabla, odds)` priorizando `league_id` (inequívoco) sobre el nombre
    de texto (potencialmente ambiguo). Si `league_id` es `None` o no está en `ID_A_CLAVE_LIGA`,
    cae a `get_liga_avg()`/`mapear_liga()` de siempre — mismo comportamiento que antes de esto
    para cualquier liga sin id verificado."""
    if league_id is not None:
        clave = ID_A_CLAVE_LIGA.get(int(league_id))
        if clave is not None:
            info = LIGAS[clave]
            return info.avg_goles, info.tabla, info.odds
    tabla, odds = mapear_liga(liga_texto)
    return get_liga_avg(liga_texto, liga_avg_input), tabla, odds
