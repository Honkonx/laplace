"""test_motor.py — integración: motor completo (todos los módulos + consenso) sobre un
partido con datos completos vs uno con datos escasos (h2h/odds/tabla/bsd_ml se saltean).

`bsd_ml` se conectó recién en la auditoría 2026-09-09 (antes existía bsd_predictions.py
completo pero `ejecutar_modulos()` nunca poblaba `resultados["bsd_ml"]`, así que
`consenso.PESOS_BASE["bsd_ml"]=0.05` siempre caía en 0 real). El fetch HTTP real de BSD se
resuelve upstream en services/analisis_completo.py — acá se simula pasando
`d["bsd_prediccion"]` ya resuelto, exactamente como lo dejaría ese fetch."""
from __future__ import annotations

from backend.api.services.motor import analizar_partido


def _partido_datos_completos(**overrides):
    d = {
        "local": "River Plate", "visitante": "Boca Juniors", "liga": "Liga Profesional",
        "partido_id": "clasico1",
        "goles_local_avg": 1.6, "goles_visit_avg": 1.1,
        "goles_contra_local_avg": 0.8, "goles_contra_visit_avg": 1.3,
        "liga_goles_avg": 2.43,
        "pos_local": 3, "pos_visit": 9,
        "forma_local_wins": 4, "forma_visit_wins": 2,
        "forma_datos_reales": True,
        "h2h_local_wins": 5, "h2h_visit_wins": 3, "h2h_empates": 2, "h2h_total": 10,
        "h2h_disponible": True,
        "odds_local": 2.30, "odds_empate": 3.10, "odds_visit": 3.00,
        "odds_disponibles": True,
    }
    d.update(overrides)
    return d


def test_partido_con_datos_completos_sin_bsd_corren_4_modulos_y_bsd_se_saltea():
    """Sin `bsd_prediccion` en el payload (caso más común: BSD no tuvo el partido, o no hay
    API key), bsd_ml queda en modulos_skip — igual que h2h/odds/tabla cuando faltan sus datos."""
    resultado = analizar_partido(_partido_datos_completos())

    assert set(resultado["modulos"].keys()) == {"poisson", "forma", "h2h", "odds", "tabla"}
    # "historico" siempre se saltea acá: los tests no cargan artefactos de Dixon-Coles.
    assert set(resultado["modulos_skip"].keys()) == {"bsd_ml", "historico"}
    assert resultado["consenso"]["pick_final"] in ("Local", "Empate", "Visitante")
    # poisson y h2h corren pero tienen peso 0 en el consenso (evaluación 2026-10-07): votan forma, odds y tabla
    assert resultado["consenso"]["total_modulos"] == 3


def test_partido_con_bsd_prediccion_disponible_corren_los_6_modulos():
    """Con `bsd_prediccion` disponible (simula el fetch real ya resuelto por
    analisis_completo.py), bsd_ml corre y queda en `modulos`; desde 2026-10-07 su peso en el consenso es 0."""
    d = _partido_datos_completos(bsd_prediccion={
        "disponible": True, "pick": "Local", "pick_nombre": "River Plate",
        "confianza_pct": 72, "fuente": "bsd_ml",
    })
    resultado = analizar_partido(d)

    assert set(resultado["modulos"].keys()) == {"poisson", "forma", "h2h", "odds", "tabla", "bsd_ml"}
    assert set(resultado["modulos_skip"]) == {"historico"}  # sin artefactos en los tests
    assert resultado["modulos"]["bsd_ml"]["pick"] == "Local"
    # bsd_ml, poisson y h2h corren pero tienen peso 0: votan forma, odds y tabla
    assert resultado["consenso"]["total_modulos"] == 3
    # bsd_ml no vota (peso 0: no se pudo reconstruir históricamente), pero su resultado queda en `modulos`
    # y se registra en el laboratorio (`bsd_catboost`) para medirlo en vivo.
    assert resultado["consenso"]["bsd_ml_activo"] is False
    assert resultado["consenso"]["peso_efectivo"]["bsd_ml"] == 0.0


def test_partido_con_bsd_prediccion_no_disponible_saltea_bsd():
    d = _partido_datos_completos(bsd_prediccion={"disponible": False})
    resultado = analizar_partido(d)

    assert "bsd_ml" not in resultado["modulos"]
    assert "bsd_ml" in resultado["modulos_skip"]


def test_partido_con_datos_escasos_saltea_modulos():
    d = {
        "local": "Equipo Chico", "visitante": "Otro Chico", "liga": "Liga Desconocida",
        "partido_id": "partido2",
        "h2h_disponible": False,
        "odds_disponibles": False,
        "pos_local": 10, "pos_visit": 10,  # default -> tabla se saltea
    }
    resultado = analizar_partido(d)

    # Sin promedios de goles de los equipos el Poisson no estima nada: se omite con razón en vez
    # de emitir la media de la liga como si fuera una predicción (sesgo a Empate, 2026-10-06).
    assert resultado["modulos"] == {}
    assert set(resultado["modulos_skip"].keys()) == {"poisson", "forma", "h2h", "odds", "tabla", "bsd_ml", "historico"}
    assert "Sin promedios de goles" in resultado["modulos_skip"]["poisson"]
    assert resultado["consenso"]["nivel"] == "SIN_MODULOS"
    assert resultado["consenso"]["pick_final"] == "Sin pronóstico"


def test_promedios_de_relleno_de_top_picks_no_habilitan_poisson():
    """1.3/1.0/1.0/1.3 sin `fuente_goles` es el relleno que usaba top_picks cuando no había
    estadísticas reales: en la BD real produjo 6 picks Empate idénticos (2026-09-27)."""
    d = _partido_datos_completos(
        goles_local_avg=1.3, goles_visit_avg=1.0, goles_contra_local_avg=1.0, goles_contra_visit_avg=1.3,
    )
    resultado = analizar_partido(d)
    assert "poisson" not in resultado["modulos"]
    assert "relleno" in resultado["modulos_skip"]["poisson"]


def test_promedios_reales_distintos_de_relleno_si_habilitan_poisson():
    resultado = analizar_partido(_partido_datos_completos())
    assert "poisson" in resultado["modulos"]


def test_promedio_generico_de_liga_no_habilita_poisson():
    d = _partido_datos_completos(
        fuente_goles="liga_generico", forma_datos_reales=False,
        h2h_disponible=False, odds_disponibles=True,
        pos_local=10, pos_visit=10,
    )
    resultado = analizar_partido(d)
    assert "poisson" not in resultado["modulos"]
    assert "poisson" in resultado["modulos_skip"]
    assert resultado["consenso"]["pick_final"] == "Local"


def test_h2h_de_un_solo_partido_no_habilita_poisson():
    d = _partido_datos_completos(
        fuente_goles="h2h_real", h2h_total=1, h2h_disponible=False,
        forma_datos_reales=False, odds_disponibles=True, pos_local=10, pos_visit=10,
    )
    resultado = analizar_partido(d)
    assert "poisson" not in resultado["modulos"]
    assert "menos de 3" in resultado["modulos_skip"]["poisson"]
