"""test_deriva.py — detector de deriva entre corridas (`laplace_agents/deriva.py`, roadmap
2026-09-10 del README). Caso real que motiva esto: 2026-09-09 el motor saltó a 92.6% "Empate"
en un día real (ver `test_consistencia.py`/`README.md`) — esto detecta ese tipo de salto
CUANDO se compara una corrida contra la anterior, no solo el nivel absoluto dentro de una
corrida (eso ya lo cubre `consistencia.py`)."""
from __future__ import annotations

from laplace_agents import deriva


def test_sin_corrida_anterior_nunca_alerta():
    resultado = deriva.detectar_deriva({"Local": 5, "Empate": 3}, None)

    assert resultado["hay_corrida_anterior"] is False
    assert resultado["alerta_deriva"] is False
    assert resultado["deltas"] == {}


def test_con_muestra_chica_en_la_corrida_actual_no_alerta_aunque_el_delta_sea_grande():
    """3 partidos hoy (100% Empate) vs 20 ayer (20% Empate) — delta real enorme, pero la
    corrida actual no tiene muestra suficiente para que el delta signifique algo."""
    actual = {"Empate": 3}
    anterior = {"Local": 16, "Empate": 4}

    resultado = deriva.detectar_deriva(actual, anterior)

    assert resultado["alerta_deriva"] is False


def test_con_muestra_chica_en_la_corrida_anterior_no_alerta():
    actual = {"Local": 10, "Empate": 10}
    anterior = {"Empate": 3}  # menos de MUESTRA_MINIMA_PARA_COMPARAR

    resultado = deriva.detectar_deriva(actual, anterior)

    assert resultado["alerta_deriva"] is False


def test_salto_real_de_proporcion_dispara_alerta():
    """Replica el hallazgo real: de una distribución pareja a una dominada por 'Empate'."""
    anterior = {"Local": 10, "Empate": 10, "Visitante": 10}  # 33.3% cada uno
    actual = {"Local": 2, "Empate": 26, "Visitante": 2}  # 86.7% Empate

    resultado = deriva.detectar_deriva(actual, anterior)

    assert resultado["alerta_deriva"] is True
    assert resultado["pick_con_mayor_delta"] == "Empate"
    assert resultado["deltas"]["Empate"] > deriva.UMBRAL_DELTA_ALERTA


def test_distribucion_parecida_entre_corridas_no_alerta():
    anterior = {"Local": 10, "Empate": 8, "Visitante": 12}
    actual = {"Local": 11, "Empate": 9, "Visitante": 10}

    resultado = deriva.detectar_deriva(actual, anterior)

    assert resultado["alerta_deriva"] is False


def test_totales_explicitos_evitan_recalcular_sumando_el_dict():
    """Cuando el caller pasa `total_actual`/`total_anterior` (como hace `core.py`, reusando
    `total_analizados_con_pick` ya calculado), se respetan en vez de sumar los dicts —
    relevante si algún día la distribución no incluye TODOS los partidos analizados."""
    resultado = deriva.detectar_deriva(
        {"Empate": 2}, {"Local": 2}, total_actual=2, total_anterior=2,
    )
    # Ambos totales explícitos siguen por debajo de MUESTRA_MINIMA_PARA_COMPARAR (5) — no alerta.
    assert resultado["alerta_deriva"] is False
