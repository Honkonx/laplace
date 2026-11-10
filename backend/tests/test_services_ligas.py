"""test_services_ligas.py — get_liga_avg/mapear_liga priorizan la clave más específica, y
LIGA_AVG/MAPA_LIGAS quedan unificados en un solo dict `LIGAS`.

Bug real encontrado 2026-09-08: el matching por substring devolvía la PRIMERA clave en orden de
inserción del dict, no la más específica — "serie a" (Italia) matcheaba antes que "serie a
brasil", así que un partido de la Serie A brasileña recibía el promedio de gol italiano. Ver
el registro de decisiones del proyecto 2026-09-08 y `PLAN_ESTRATEGICO_2026-09.md`.

Unificación 2026-09-08 (mismo día): `LIGA_AVG` (~50 ligas con promedio de gol) y `MAPA_LIGAS`
(~24 ligas con tabla/odds) vivían como dos dicts separados que podían desincronizarse — más de
la mitad de las ligas con promedio de gol no tenían tabla/odds mapeados, y eso quedaba invisible.
Ahora es un solo `LIGAS: dict[str, LigaInfo]` — los tests de acá abajo confirman que ninguna
liga que antes tenía tabla/odds los perdió en la unificación, y agregan cobertura de
`es_liga_conocida()` (la función nueva que usa el filtro de calidad de `top_picks.py`).
"""
from __future__ import annotations

from backend.api.services.ligas import (
    DEFAULT_LIGA_AVG,
    ID_A_CLAVE_LIGA,
    LIGAS,
    _clave_mas_especifica,
    es_liga_conocida,
    get_liga_avg,
    mapear_liga,
    resolver_liga_por_id,
)


def test_serie_a_brasil_no_usa_el_promedio_de_serie_a_italia():
    # Antes del fix esto devolvía 2.67 (Italia) en vez de 2.55 (Brasil real).
    assert get_liga_avg("Serie A Brasil", 2.5) == 2.55


def test_serie_a_italia_sigue_funcionando_normal():
    assert get_liga_avg("Serie A", 2.5) == 2.67


def test_campeonato_brasileiro_devuelve_promedio_correcto():
    assert get_liga_avg("Campeonato Brasileiro Série A", 2.5) == 2.55


def test_liga_desconocida_usa_input_si_es_razonable():
    assert get_liga_avg("Liga Inventada FC", 2.9) == 2.9


def test_liga_desconocida_sin_input_razonable_usa_default():
    assert get_liga_avg("Liga Inventada FC", 99.0) == DEFAULT_LIGA_AVG


def test_mapear_liga_prioriza_clave_mas_especifica():
    # "la liga" y "laliga" no compiten, pero confirma que sigue resolviendo bien lo básico.
    tabla, odds = mapear_liga("La Liga")
    assert tabla == "PD"
    assert odds == "soccer_spain_la_liga"


def test_mapear_liga_sin_match_devuelve_none_none():
    assert mapear_liga("Liga Que No Existe") == (None, None)


def test_mapear_liga_con_none_no_revienta():
    assert mapear_liga(None) == (None, None)


# ─── Unificación LIGA_AVG + MAPA_LIGAS (2026-09-08) ────────────────────────────────────────


def test_ninguna_liga_con_tabla_u_odds_previo_los_perdio():
    """Todas las ligas que antes tenían tabla/odds mapeados en `MAPA_LIGAS` siguen
    devolviéndolos igual desde la tabla unificada `LIGAS`."""
    esperado = {
        "premier league": ("PL", "soccer_epl"),
        "laliga": ("PD", "soccer_spain_la_liga"),
        "la liga": ("PD", "soccer_spain_la_liga"),
        "serie a": ("SA", "soccer_italy_serie_a"),
        "bundesliga": ("BL1", "soccer_germany_bundesliga"),
        "ligue 1": ("FL1", "soccer_france_ligue_one"),
        "eredivisie": ("DED", "soccer_netherlands_eredivisie"),
        "championship": ("ELC", "soccer_efl_champ"),
        "primeira liga": (None, "soccer_portugal_primeira_liga"),
        "scottish": (None, "soccer_spl"),  # la clave anterior no existe en The Odds API (404 verificado 2026-10-19)
        "super lig": (None, "soccer_turkey_super_league"),
        "saudi pro": (None, "soccer_saudi_arabia_pro_league"),  # idem: la anterior daba 404
        "j1 league": (None, "soccer_japan_j_league"),
        "champions league": ("CL", "soccer_uefa_champs_league"),
        "europa league": (None, "soccer_uefa_europa_league"),
        "conference league": (None, "soccer_uefa_europa_conference_league"),
        "mls": (None, "soccer_usa_mls"),
        "liga mx": (None, "soccer_mexico_ligamx"),
        "brasileirao": (None, "soccer_brazil_campeonato"),
        "serie b": (None, "soccer_brazil_serie_b"),
        "liga profesional": (None, "soccer_argentina_primera_division"),
        "apertura": (None, "soccer_argentina_primera_division"),
        "clausura": (None, "soccer_argentina_primera_division"),
        "copa libertadores": (None, "soccer_conmebol_copa_libertadores"),
        "copa sudamericana": (None, "soccer_conmebol_copa_sudamericana"),
    }
    for clave, (tabla, odds) in esperado.items():
        assert LIGAS[clave].tabla == tabla, f"tabla de '{clave}' cambió"
        assert LIGAS[clave].odds == odds, f"odds de '{clave}' cambió"


def test_ninguna_liga_con_avg_goles_previo_lo_perdio():
    """Spot-check de promedios de gol que antes vivían solo en `LIGA_AVG` (sin tabla/odds) —
    confirma que la unificación no perdió ningún valor de goles."""
    assert LIGAS["segunda division"].avg_goles == 2.45
    assert LIGAS["chinese super league"].avg_goles == 2.69
    assert LIGAS["tunisian"].avg_goles == 2.29
    assert LIGAS["serie a brasil"].avg_goles == 2.55
    assert LIGAS["campeonato brasileiro"].avg_goles == 2.55


def test_es_liga_conocida_true_para_liga_mapeada():
    # "Premier League" NO se usa acá a propósito — desde 2026-09-09 es una clave ambigua en el
    # origen de datos (ver test_premier_league_queda_como_ambigua_no_como_inglaterra abajo).
    assert es_liga_conocida("Bundesliga") is True
    assert es_liga_conocida("Chinese Super League") is True  # sin tabla/odds, pero SÍ conocida


def test_es_liga_conocida_false_para_liga_sin_ningun_dato():
    assert es_liga_conocida("Liga Completamente Inventada FC") is False
    assert es_liga_conocida(None) is False


def test_liga_con_tabla_o_odds_siempre_tiene_avg_goles_real():
    """Invariante de la unificación: ninguna `LigaInfo` con `tabla`/`odds` mapeados puede tener
    un `avg_goles` inventado — la estructura no lo permite (siempre es un campo obligatorio),
    pero este test deja explícito que se pobló con un valor real para cada una."""
    for clave, info in LIGAS.items():
        if info.tabla is not None or info.odds is not None:
            assert 1.8 <= info.avg_goles <= 4.2, f"avg_goles fuera de rango razonable para '{clave}'"


# ─── Claves ambiguas en el origen de datos (2026-09-09) ────────────────────────────────────
# Hallazgo real con datos del día real: LiveScore6 agrupa bajo el mismo Snm/liga_slug
# "premier league" partidos de Kazajistán, Bosnia, Egipto y Tanzania junto con la Premier
# League inglesa real — confirmar cada país por nombre de texto no es posible con este origen.


def test_premier_league_queda_como_ambigua_no_como_inglaterra():
    """Antes de este fix, "Premier League" (sin más contexto) devolvía silenciosamente el
    promedio de gol/tabla/odds de Inglaterra — pero con los datos reales del día, la MISMA
    etiqueta cubre partidos de Kazajistán, Bosnia, Egipto y Tanzania. Ahora cae a "desconocida"
    en vez de asumir Inglaterra."""
    assert es_liga_conocida("Premier League") is False
    assert mapear_liga("Premier League") == (None, None)
    assert get_liga_avg("Premier League", 2.9) == 2.9  # usa el input, no el 2.82 de Inglaterra


def test_kairat_almaty_no_recibe_datos_de_inglaterra():
    """Caso real encontrado 2026-09-09: Kairat Almaty vs Zhenis (Kazajistán) venía etiquetado
    "Premier League" y recibía el promedio de gol/tabla/odds de la Premier League inglesa."""
    assert get_liga_avg("Premier League", 99.0) == DEFAULT_LIGA_AVG  # sin input razonable → default genérico, no 2.82


def test_ligas_no_ambiguas_siguen_matcheando_normal():
    """El bloqueo es específico de "premier league" — no debe afectar otras claves reales."""
    assert es_liga_conocida("Bundesliga") is True
    assert mapear_liga("Bundesliga") == ("BL1", "soccer_germany_bundesliga")


def test_mls_next_pro_no_recibe_el_promedio_de_la_mls_titular():
    """Caso real 2026-09-09: Toronto FC II vs Columbus Crew II venía etiquetado "MLS Next Pro"
    (liga reserva/desarrollo) y matcheaba contra la clave "mls" (liga titular, 3.02) por
    substring — el calificador "next pro" ahora lo descarta."""
    assert es_liga_conocida("MLS Next Pro") is False
    assert get_liga_avg("MLS Next Pro", 2.5) == 2.5  # usa el input, no el 3.02 de la MLS titular
    assert es_liga_conocida("MLS") is True  # la liga titular real sigue matcheando normal
    assert get_liga_avg("MLS", 2.5) == 3.02


def test_champions_league_path_no_recibe_el_promedio_de_mayores():
    """Caso real 2026-09-09: Napoli U19 vs Arsenal U19 (fase clasificatoria UEFA Youth League)
    venía etiquetado "Champions League Path" y matcheaba contra "champions league" (mayores,
    2.98) por substring — el calificador " path" ahora lo descarta."""
    assert es_liga_conocida("Champions League Path") is False
    assert mapear_liga("Champions League Path") == (None, None)
    assert es_liga_conocida("Champions League") is True  # la competición de mayores real sigue matcheando


def test_championship_ingles_queda_ambiguo_por_colision_con_nombres_de_otras_competiciones():
    """Caso real 2026-09-09 (corrida de 10 partidos de verificar_datos_reales.py): "Caribbean
    Club Championship: Group A" y "Veikkausliiga: Championship" (playoffs de Finlandia)
    matcheaban contra el Championship inglés por contener la palabra "championship"."""
    assert es_liga_conocida("Championship") is False
    assert mapear_liga("Caribbean Club Championship: Group A") == (None, None)
    assert mapear_liga("Veikkausliiga: Championship") == (None, None)


def test_apertura_clausura_quedan_ambiguos_por_ser_comunes_a_varios_paises():
    """Caso real 2026-09-09: "Primera Division: Apertura" (Panamá) y "Primera B: Clausura"
    (formato de torneo también usado fuera de Argentina) matcheaban contra el promedio/odds de
    Argentina — "liga profesional" (clave real y específica) sigue funcionando normal."""
    assert es_liga_conocida("Apertura") is False
    assert es_liga_conocida("Clausura") is False
    assert mapear_liga("Primera Division: Apertura") == (None, None)
    assert mapear_liga("Primera B: Clausura") == (None, None)
    assert es_liga_conocida("Liga Profesional") is True
    assert mapear_liga("Liga Profesional") == (None, "soccer_argentina_primera_division")


def test_womens_liga_mx_no_recibe_el_promedio_de_la_liga_mx_masculina():
    """Caso real 2026-09-09: "Women's Liga MX: Apertura" matcheaba contra "liga mx" (masculina)
    — el fútbol femenino es una competición real y distinta, no una variante menor."""
    assert es_liga_conocida("Women's Liga MX: Apertura") is False
    assert get_liga_avg("Women's Liga MX: Apertura", 2.5) == 2.5  # usa el input, no el 2.71 masculino
    assert es_liga_conocida("Liga MX") is True  # la liga masculina real sigue matcheando normal


# ─── Resolución por league_id numérico (2026-09-09) ────────────────────────────────────────


def test_resolver_liga_por_id_premier_league_resuelve_inglaterra_pese_a_texto_ambiguo():
    """El fix de fondo: "Premier League" es intencionalmente inalcanzable por texto (ver
    CLAVES_AMBIGUAS_EN_ORIGEN), pero el league_id real de api-football (39 = Inglaterra) no es
    ambiguo — resolver por id da el dato real de Inglaterra sin depender del nombre de texto."""
    avg, tabla, odds = resolver_liga_por_id(39, "Premier League", 2.9)
    assert avg == 2.82
    assert tabla == "PL"
    assert odds == "soccer_epl"


def test_resolver_liga_por_id_sin_id_cae_a_matching_por_texto_de_siempre():
    avg, tabla, odds = resolver_liga_por_id(None, "Bundesliga", 2.6)
    assert (avg, tabla, odds) == (3.03, "BL1", "soccer_germany_bundesliga")


def test_resolver_liga_por_id_desconocido_cae_a_matching_por_texto_de_siempre():
    """Un league_id real que no está en `ID_A_CLAVE_LIGA` (ninguna liga inventada) no debe
    romper nada — mismo comportamiento que sin id."""
    avg, tabla, odds = resolver_liga_por_id(999999, "Bundesliga", 2.6)
    assert (avg, tabla, odds) == (3.03, "BL1", "soccer_germany_bundesliga")


def test_id_a_clave_liga_todas_las_claves_existen_en_ligas():
    """Invariante real: ningún id de `ID_A_CLAVE_LIGA` puede apuntar a una clave que no exista
    (o dejó de existir) en `LIGAS` — evita un `KeyError` real en producción si alguien edita
    `LIGAS` sin revisar este mapeo."""
    for league_id, clave in ID_A_CLAVE_LIGA.items():
        assert clave in LIGAS, f"league_id {league_id} apunta a clave inexistente '{clave}'"


def test_calificador_no_descarta_si_ya_forma_parte_de_la_clave_que_gano():
    """Si en el futuro se agrega una clave específica que YA incluye el calificador (ej. "mls
    next pro" como entrada propia con su propio avg_goles real), el calificador no debe
    descartarla — la exclusión es solo para cuando el calificador aparece pero NO forma parte
    de la clave que matcheó."""
    claves_de_prueba = {"mls next pro": object()}
    assert _clave_mas_especifica("mls next pro", claves_de_prueba) == "mls next pro"


def test_ligas_con_cuotas_agregadas_se_resuelven_solo_por_league_id():
    """2026-10-19: 23 ligas con cuotas activas en The Odds API (verificado con `GET /v4/sports`) no estaban mapeadas.
    Se resuelven por `league_id`; por texto no coinciden (los nombres son ambiguos: Serie B de Italia o de Brasil)."""
    from backend.api.services.ligas import mapear_liga, resolver_liga_por_id

    esperado = {103: "soccer_norway_eliteserien", 113: "soccer_sweden_allsvenskan", 265: "soccer_chile_campeonato",
                136: "soccer_italy_serie_b", 72: "soccer_brazil_serie_b", 106: "soccer_poland_ekstraklasa"}
    for liga_id, odds_key in esperado.items():
        assert resolver_liga_por_id(liga_id, "texto cualquiera", 2.6)[2] == odds_key
    assert mapear_liga("Veikkausliiga: Championship") == (None, None)
    assert mapear_liga("Eliteserien") == (None, None)  # sin league_id no se adivina la liga por el nombre
