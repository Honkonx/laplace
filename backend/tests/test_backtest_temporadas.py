"""El backtest de temporadas (MM-22/23) sobre una liga sintética completa: forma del informe y rechazo de calendarios incompletos."""
from backend.scripts import backtest_temporadas as bt


def _temporada_completa(n=10):
    equipos = [f"T{i}" for i in range(n)]
    ps, dia = [], 730000
    for a in equipos:
        for b in equipos:
            if a != b:
                dia += 1
                gl, gv = (dia % 4), (dia % 3)
                ps.append({"liga": "S", "temporada": "2024/2025", "dia": dia, "local": a, "visitante": b, "gl": gl, "gv": gv, "resultado": "H" if gl > gv else "D" if gl == gv else "A",
                           "tl": None, "tv": None, "al": None, "av": None})
    return ps


def test_una_temporada_completa_devuelve_metricas_en_rango():
    r = bt.una_temporada([], _temporada_completa(), 0.6, 300, 0.1)
    assert r and 0 <= r["cobertura"] <= 1 and r["mae_modelo"] >= 0 and r["mae_extrapolacion"] >= 0 and r["equipos"] == 10


def test_un_calendario_incompleto_o_chico_se_descarta():
    assert bt.una_temporada([], _temporada_completa()[:50], 0.6, 100) is None
    assert bt.una_temporada([], _temporada_completa(6), 0.6, 100) is None


def test_correr_sin_temporadas_no_declara_validado():
    assert bt.correr({"S": []}, ["S"], 0.6, 100) == {"n_temporadas": 0, "validado": False}
