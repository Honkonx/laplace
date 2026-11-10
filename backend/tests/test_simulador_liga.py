"""test_simulador_liga.py — Monte Carlo puro (`simular_temporada`), sin red ni BD. Confirma
que el simulador realmente pondera por probabilidad (no solo que no tira excepción) usando
probabilidades fijas conocidas: un equipo con prob_local=0.9 en TODOS sus partidos como local
debería terminar campeón en la enorme mayoría de las simulaciones."""
from __future__ import annotations

from backend.api.services import simulador_liga


def _liga_4_equipos_favorito_claro() -> list[dict]:
    """4 equipos, cada uno juega contra los otros 3 (todos de local una vez). 'Dominante'
    tiene prob_local=0.9 en sus 3 partidos de local; el resto de los partidos (entre los otros
    3 equipos) son equilibrados (1/3 cada resultado) — sin señal extra a favor de nadie más."""
    equilibrado = (1 / 3, 1 / 3, 1 / 3)
    return [
        {"local": "Dominante", "visitante": "B", "prob_local": 0.90, "prob_empate": 0.06, "prob_visitante": 0.04},
        {"local": "Dominante", "visitante": "C", "prob_local": 0.90, "prob_empate": 0.06, "prob_visitante": 0.04},
        {"local": "Dominante", "visitante": "D", "prob_local": 0.90, "prob_empate": 0.06, "prob_visitante": 0.04},
        {"local": "B", "visitante": "C", "prob_local": equilibrado[0], "prob_empate": equilibrado[1], "prob_visitante": equilibrado[2]},
        {"local": "B", "visitante": "D", "prob_local": equilibrado[0], "prob_empate": equilibrado[1], "prob_visitante": equilibrado[2]},
        {"local": "C", "visitante": "D", "prob_local": equilibrado[0], "prob_empate": equilibrado[1], "prob_visitante": equilibrado[2]},
    ]


def test_simular_temporada_favorito_claro_gana_campeonato_casi_siempre():
    partidos = _liga_4_equipos_favorito_claro()
    tabla_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}

    resultado = simulador_liga.simular_temporada(
        partidos, tabla_actual, n_simulaciones=5000, posiciones_copa=2, posiciones_descenso=1, seed=42
    )

    assert set(resultado.keys()) == {"Dominante", "B", "C", "D"}
    # Con 3 partidos ganados casi siempre (0.9^3 ≈ 73% de ganarlos los 3), "Dominante" debería
    # ser campeón en la gran mayoría de las simulaciones — muy por encima del 25% que le tocaría
    # a un equipo cualquiera en una liga de 4 sin ninguna ventaja.
    assert resultado["Dominante"]["prob_campeon"] > 0.60
    assert resultado["Dominante"]["prob_copa"] > 0.85
    assert resultado["Dominante"]["prob_descenso"] < 0.02
    assert resultado["Dominante"]["posicion_promedio"] < resultado["B"]["posicion_promedio"]
    assert resultado["Dominante"]["posicion_promedio"] < resultado["C"]["posicion_promedio"]
    assert resultado["Dominante"]["posicion_promedio"] < resultado["D"]["posicion_promedio"]

    # Las probabilidades de campeón de TODOS los equipos deben sumar ~1.0 (exactamente 1 campeón
    # por simulación).
    suma_prob_campeon = sum(e["prob_campeon"] for e in resultado.values())
    assert abs(suma_prob_campeon - 1.0) < 0.01


def test_simular_temporada_es_determinístico_con_mismo_seed():
    partidos = _liga_4_equipos_favorito_claro()
    tabla_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}

    r1 = simulador_liga.simular_temporada(partidos, tabla_actual, n_simulaciones=500, seed=7)
    r2 = simulador_liga.simular_temporada(partidos, tabla_actual, n_simulaciones=500, seed=7)

    assert r1 == r2


def test_simular_temporada_respeta_tabla_actual_como_punto_de_partida():
    """Si un equipo ya arrancaba con una ventaja de puntos enorme respecto al resto, y quedan
    pocos partidos por jugar, esa ventaja debe dominar el resultado incluso sin favoritismo en
    las probabilidades de los partidos restantes."""
    partidos = [
        {"local": "Puntero", "visitante": "Perseguidor", "prob_local": 1 / 3, "prob_empate": 1 / 3, "prob_visitante": 1 / 3},
    ]
    tabla_actual = {"Puntero": 50, "Perseguidor": 10}

    resultado = simulador_liga.simular_temporada(partidos, tabla_actual, n_simulaciones=1000, seed=1)

    assert resultado["Puntero"]["prob_campeon"] == 1.0
    assert resultado["Perseguidor"]["prob_campeon"] == 0.0


def test_simular_temporada_sin_partidos_ni_equipos_devuelve_vacio():
    assert simulador_liga.simular_temporada([], {}, n_simulaciones=100) == {}


def test_simular_temporada_posiciones_copa_y_descenso_parametrizables():
    partidos = _liga_4_equipos_favorito_claro()
    tabla_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}

    resultado = simulador_liga.simular_temporada(
        partidos, tabla_actual, n_simulaciones=500, posiciones_copa=1, posiciones_descenso=2, seed=3
    )

    # top1 == campeón cuando posiciones_copa=1
    assert resultado["Dominante"]["prob_copa"] == resultado["Dominante"]["prob_campeon"]
    # con posiciones_descenso=2 sobre 4 equipos, las probs de descenso de los 4 deben sumar 2.0
    suma_prob_descenso = sum(e["prob_descenso"] for e in resultado.values())
    assert abs(suma_prob_descenso - 2.0) < 0.05


def test_league_id_por_slug_es_reverso_consistente_de_top_picks():
    from backend.api.services.top_picks import LIGA_SLUG_POR_ID

    for league_id, slug in LIGA_SLUG_POR_ID.items():
        assert simulador_liga.LEAGUE_ID_POR_SLUG[slug] == league_id


def test_liga_argentina_local_no_depende_de_top_picks():
    """`LIGA_ARGENTINA_LEAGUE_ID` (128, id real de api-football confirmado empiricamente
    2026-09-08) es local a este archivo porque top_picks.LIGA_SLUG_POR_ID no tiene entrada para
    la Liga Profesional Argentina hoy."""
    from backend.api.services.top_picks import LIGA_SLUG_POR_ID

    assert simulador_liga.LIGA_ARGENTINA_SLUG not in simulador_liga.LEAGUE_ID_POR_SLUG
    if simulador_liga.LIGA_ARGENTINA_LEAGUE_ID in LIGA_SLUG_POR_ID:
        assert LIGA_SLUG_POR_ID[simulador_liga.LIGA_ARGENTINA_LEAGUE_ID] == simulador_liga.LIGA_ARGENTINA_SLUG


def test_simular_temporada_sin_historial_no_agrega_campo_nuevo():
    partidos = _liga_4_equipos_favorito_claro()
    tabla_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}

    resultado = simulador_liga.simular_temporada(partidos, tabla_actual, n_simulaciones=200, seed=1)

    for datos_equipo in resultado.values():
        assert "prob_descenso_por_promedio" not in datos_equipo


def test_simular_temporada_con_historial_agrega_prob_descenso_por_promedio():
    partidos = _liga_4_equipos_favorito_claro()
    tabla_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}
    historial = {
        "Dominante": {"puntos": 60, "partidos": 30},
        "B": {"puntos": 40, "partidos": 30},
        "C": {"puntos": 35, "partidos": 30},
        "D": {"puntos": 30, "partidos": 30},
    }
    partidos_jugados_actual = {"Dominante": 0, "B": 0, "C": 0, "D": 0}

    resultado = simulador_liga.simular_temporada(
        partidos, tabla_actual, n_simulaciones=2000, posiciones_descenso=1, seed=5,
        historial_multi_temporada=historial, partidos_jugados_actual=partidos_jugados_actual,
    )

    for datos_equipo in resultado.values():
        assert "prob_descenso_por_promedio" in datos_equipo

    suma = sum(e["prob_descenso_por_promedio"] for e in resultado.values())
    assert abs(suma - 1.0) < 0.05


def test_descenso_por_promedio_difiere_de_descenso_por_tabla_actual():
    """Caso central de la regla AFA: 'Bueno' viene MAL esta temporada (último en la tabla actual
    -> prob_descenso=1.0) pero arrastra un historial multi-temporada muy fuerte; 'MalHistorial'
    lidera la tabla actual (prob_descenso=0.0) pero arrastra un historial pésimo. Los números
    están elegidos para que el resultado sea el mismo sin importar qué pase en el único partido
    pendiente (ver cálculo exacto en el docstring de este archivo si se cambian los valores):
    con esta combinación, 'Bueno' desciende SIEMPRE por tabla actual y 'MalHistorial' desciende
    SIEMPRE por promedio multi-temporada — son criterios distintos, esa es la razón de ser de la
    capa adicional."""
    partidos = [
        {"local": "MalHistorial", "visitante": "Bueno", "prob_local": 1 / 3, "prob_empate": 1 / 3, "prob_visitante": 1 / 3},
    ]
    tabla_actual = {"MalHistorial": 35, "Bueno": 20}
    historial = {
        "MalHistorial": {"puntos": 20, "partidos": 60},
        "Bueno": {"puntos": 100, "partidos": 60},
    }
    partidos_jugados_actual = {"MalHistorial": 25, "Bueno": 25}

    resultado = simulador_liga.simular_temporada(
        partidos, tabla_actual, n_simulaciones=500, posiciones_descenso=1, seed=9,
        historial_multi_temporada=historial, partidos_jugados_actual=partidos_jugados_actual,
    )

    assert resultado["Bueno"]["prob_descenso"] == 1.0
    assert resultado["MalHistorial"]["prob_descenso"] == 0.0
    assert resultado["MalHistorial"]["prob_descenso_por_promedio"] == 1.0
    assert resultado["Bueno"]["prob_descenso_por_promedio"] == 0.0


def test_equipos_en_zona_descenso_por_promedio_equipo_sin_historial_usa_solo_temporada_actual():
    zona = simulador_liga._equipos_en_zona_descenso_por_promedio(
        puntos_temporada_actual={"A": 10, "B": 10},
        historial_multi_temporada={"A": {"puntos": 100, "partidos": 30}},
        partidos_totales_temporada_actual={"A": 10, "B": 10},
        posiciones_descenso_promedio=1,
    )
    assert zona == {"B"}


def test_partidos_pendientes_por_equipo():
    partidos = _liga_4_equipos_favorito_claro()
    conteo = simulador_liga._partidos_pendientes_por_equipo(partidos)
    assert conteo == {"Dominante": 3, "B": 3, "C": 3, "D": 3}
