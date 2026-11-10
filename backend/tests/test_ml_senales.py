"""test_ml_senales.py — `ml/senales.py`: sin fuga del futuro y fidelidad con los módulos de producción.

Datos sintéticos pequeños, Python puro (no necesita numpy). Los tests de fidelidad comparan contra
`services/motor.py` y `services/h2h_fetch.py` reales para que el arnés histórico no se desvíe en silencio.
"""
from __future__ import annotations

import copy
import math
from datetime import date

import pytest

from backend.api.ml import senales


def _partido(dia: int, local: str, visitante: str, gl: int, gv: int, liga: str = "E0", temporada: str = "2425") -> dict:
    return {
        "liga": liga, "liga_nombre": "Premier League", "temporada": temporada, "dia": dia, "fecha": date.fromordinal(dia),
        "local": local, "visitante": visitante, "gl": gl, "gv": gv,
        "resultado": "H" if gl > gv else "A" if gv > gl else "D",
    }


def _calendario() -> list[dict]:
    base = date(2024, 8, 1).toordinal()
    equipos = ["A", "B", "C", "D"]
    partidos, dia = [], base
    for ronda in range(8):
        for i in range(0, 4, 2):
            h, a = equipos[(i + ronda) % 4], equipos[(i + 1 + ronda * 3) % 4]
            if h != a:
                partidos.append(_partido(dia, h, a, (ronda + i) % 4, (ronda * 2 + i) % 3))
        dia += 7
    return partidos


def _senales_secuenciales(partidos: list[dict]) -> list[dict]:
    c = senales.ConstructorSenales()
    salida = []
    for _, bloque in senales.agrupar_por_dia(partidos):
        salida += [c.construir(p) for p in bloque]
        for p in bloque:
            c.registrar(p)
    return salida


def test_la_senal_de_un_partido_no_cambia_si_se_alteran_los_posteriores():
    partidos = _calendario()
    corte = len(partidos) // 2
    original = _senales_secuenciales(partidos)
    alterados = copy.deepcopy(partidos)
    for p in alterados[corte:]:
        p["gl"], p["gv"] = 9, 0
        p["resultado"] = "H"
    nuevos = _senales_secuenciales(alterados)
    assert original[:corte + 1] == nuevos[:corte + 1]  # el primer partido alterado tampoco ve su propio resultado


def test_la_senal_no_cambia_si_se_eliminan_los_partidos_posteriores():
    partidos = _calendario()
    corte = len(partidos) // 2
    assert _senales_secuenciales(partidos)[:corte + 1] == _senales_secuenciales(partidos[:corte + 1])


def test_partidos_del_mismo_dia_no_se_ven_entre_si():
    d0 = date(2024, 8, 1).toordinal()
    previos = [_partido(d0, "A", "B", 3, 0), _partido(d0, "C", "D", 0, 2)]
    p1 = _partido(d0 + 7, "A", "C", 1, 1)
    p2 = _partido(d0 + 7, "B", "D", 2, 0)
    solo_p1 = _senales_secuenciales(previos + [p1])[-1]
    con_p2 = _senales_secuenciales(previos + [p1, p2])[-2]
    assert solo_p1 == con_p2


def test_forma_tabla_y_goles_de_temporada_se_calculan_con_lo_anterior():
    d0 = date(2024, 8, 1).toordinal()
    c = senales.ConstructorSenales()
    historial = [_partido(d0 + 7 * i, "A", "B", 2, 0) for i in range(3)] + [
        _partido(d0 + 30 + 7 * i, "A", "C", 1, 0) for i in range(2)]
    historial += [_partido(d0 + 60 + 7 * i, "C", "B", 0, 0) for i in range(2)]
    for p in historial:
        c.registrar(p)
    d = c.construir(_partido(d0 + 100, "A", "B", 0, 0))
    assert d["forma_datos_reales"] is True
    assert d["forma_local_wins"] == 5 and d["forma_visit_wins"] == 0
    assert d["pos_local"] == 1 and d["pos_visit"] == 3
    # Cascada de h2h_fetch: hay 3 H2H previos -> fuente h2h_real, no promedios de temporada.
    assert d["fuente_goles"] == "h2h_real" and d["h2h_total"] == 3 and d["h2h_local_wins"] == 3


def test_sin_historial_cae_a_liga_generico_y_sin_datos_reales():
    d = senales.ConstructorSenales().construir(_partido(1, "A", "B", 0, 0))
    assert d["fuente_goles"] == "liga_generico" and d["forma_datos_reales"] is False
    assert d["pos_local"] == d["pos_visit"] == 10 and d["h2h_total"] == 0


def test_stats_de_equipo_cuando_no_hay_h2h():
    d0 = date(2024, 8, 1).toordinal()
    c = senales.ConstructorSenales()
    for p in (_partido(d0, "A", "X", 3, 1), _partido(d0 + 7, "B", "Y", 0, 2)):
        c.registrar(p)
    d = c.construir(_partido(d0 + 14, "A", "B", 0, 0))
    assert d["fuente_goles"] == "stats_equipo_real"
    assert (d["goles_local_avg"], d["goles_contra_local_avg"]) == (3.0, 1.0)
    assert (d["goles_visit_avg"], d["goles_contra_visit_avg"]) == (0.0, 2.0)


def test_orientacion_produccion_vs_corregida_del_h2h():
    d0 = date(2024, 8, 1).toordinal()
    # B (hoy visitante) ganó 3-0 jugando de local contra A en cada cruce previo.
    previos = [_partido(d0 + 7 * i, "B", "A", 3, 0) for i in range(3)]
    actual = _partido(d0 + 40, "A", "B", 0, 0)
    prod, corr = senales.ConstructorSenales("produccion"), senales.ConstructorSenales("corregida")
    for p in previos:
        prod.registrar(p)
        corr.registrar(p)
    dp, dc = prod.construir(actual), corr.construir(actual)
    assert (dp["h2h_local_wins"], dp["h2h_visit_wins"]) == (3, 0)  # cuenta del local del partido histórico
    assert (dc["h2h_local_wins"], dc["h2h_visit_wins"]) == (0, 3)  # del local actual (A) perdió 3
    assert dc["goles_local_avg"] == 0.0 and dc["goles_visit_avg"] == 3.0


def test_orientacion_invalida():
    with pytest.raises(ValueError):
        senales.ConstructorSenales("otra")


def test_media_vida_coincide_con_h2h_fetch():
    h2h_fetch = pytest.importorskip("backend.api.services.h2h_fetch")
    assert senales.MEDIA_VIDA_H2H_DIAS == h2h_fetch.MEDIA_VIDA_DIAS


def test_bloque_h2h_coincide_con_h2h_fetch_ponderar_y_resumir(monkeypatch):
    h2h_fetch = pytest.importorskip("backend.api.services.h2h_fetch")
    d0 = date(2024, 8, 1).toordinal()
    previos = [_partido(d0, "A", "B", 2, 1), _partido(d0 + 90, "B", "A", 0, 0), _partido(d0 + 200, "A", "B", 1, 3)]
    actual = _partido(d0 + 400, "A", "B", 0, 0)
    c = senales.ConstructorSenales("produccion")
    for p in previos:
        c.registrar(p)
    mio = c.construir(actual)
    monkeypatch.setattr(h2h_fetch, "_dias_desde", lambda fecha_iso: float(actual["dia"] - date.fromisoformat(fecha_iso).toordinal()))
    crudo = [{"fecha_iso": p["fecha"].isoformat(), "local": p["local"], "visitante": p["visitante"],
              "goles_local": p["gl"], "goles_visitante": p["gv"]} for p in reversed(previos)]
    real = h2h_fetch._ponderar_y_resumir(crudo)
    for clave in ("h2h_local_wins", "h2h_visit_wins", "h2h_empates", "h2h_total", "goles_local_avg", "goles_visit_avg"):
        assert mio[clave] == pytest.approx(real[clave]), clave


def _d_completo(**extra) -> dict:
    d = {"partido_id": "x", "local": "A", "visitante": "B", "liga": "Premier League", "liga_goles_avg": 2.6,
         "pos_local": 3, "pos_visit": 12, "forma_local_wins": 4, "forma_visit_wins": 1, "forma_datos_reales": True,
         "h2h_disponible": True, "h2h_local_wins": 4, "h2h_visit_wins": 2, "h2h_empates": 2, "h2h_total": 8,
         "goles_local_avg": 1.8, "goles_visit_avg": 1.1, "goles_contra_local_avg": 1.1, "goles_contra_visit_avg": 1.8,
         "fuente_goles": "h2h_real", "odds_disponibles": True, "odds_local": 1.8, "odds_empate": 3.6, "odds_visit": 4.5}
    d.update(extra)
    return d


@pytest.mark.parametrize("variante", [
    {}, {"odds_disponibles": False}, {"fuente_goles": "liga_generico"},
    {"h2h_total": 2, "h2h_local_wins": 1, "h2h_visit_wins": 1, "h2h_empates": 0},
    {"forma_datos_reales": False}, {"pos_local": 10, "pos_visit": 10},
])
def test_compuerta_de_modulos_coincide_con_el_motor_real(monkeypatch, variante):
    motor = pytest.importorskip("backend.api.services.motor")

    class _SinHistorico:
        @staticmethod
        def validar_historico(_d):
            return False, "stub"

    class _SinBsd:
        @staticmethod
        def validar_bsd(_d):
            return False, "stub"

    monkeypatch.setattr(motor, "modelo_historico_svc", _SinHistorico)
    monkeypatch.setattr(motor, "bsd_predictions_svc", _SinBsd)
    d = _d_completo(**variante)
    reales, _ = motor.ejecutar_modulos(d)
    mios = senales.ejecutar_modulos(d)
    assert set(mios) == set(reales)
    for modulo in reales:
        assert mios[modulo]["pick"] == reales[modulo]["pick"]
        assert mios[modulo]["confianza_score"] == reales[modulo]["confianza_score"]
        assert mios[modulo]["prob_local"] == pytest.approx(reales[modulo]["prob_local"])


def test_resultado_historico_usa_la_misma_formula_que_el_servicio(monkeypatch):
    from backend.api.ml import dixon_coles
    from backend.api.services import modelo_historico

    modelo = dixon_coles.ModeloLiga(mu=0.2, gamma=0.25, ataque={"A": 0.3, "B": -0.2}, defensa={"A": -0.1, "B": 0.2}, rho=-0.05)
    monkeypatch.setattr(modelo_historico, "_resolver", lambda d: ("E0", modelo, "A", "B"))
    original = modelo_historico._artefactos
    sin_artefactos = lambda: None  # noqa: E731
    sin_artefactos.cache_clear = original.cache_clear  # el conftest limpia esta caché al terminar
    monkeypatch.setattr(modelo_historico, "_artefactos", sin_artefactos)
    real = modelo_historico.analizar({})
    lam_h, lam_a, _ = dixon_coles.lambdas(modelo, "A", "B")
    mio = senales.resultado_historico(dixon_coles.probabilidades_desde_lambdas(lam_h, lam_a, modelo.rho))
    assert mio["pick"] == real["pick"] and mio["confianza_score"] == real["confianza_score"]
    assert math.isclose(mio["prob_local"], real["prob_local"], abs_tol=1e-4)


def test_ejecutar_modulos_agrega_historico_solo_si_se_entrega():
    assert "historico" not in senales.ejecutar_modulos(_d_completo())
    assert senales.ejecutar_modulos(_d_completo(), (0.5, 0.3, 0.2))["historico"]["pick"] == "Local"
