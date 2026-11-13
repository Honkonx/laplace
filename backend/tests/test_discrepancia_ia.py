"""MB-15: tabla 2×2 de «la IA diverge» frente al acierto del consenso, con veredicto honesto."""
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services import discrepancia_ia as d


def _filas(c_ok, c_mal, d_ok, d_mal):
    return [("COINCIDEN", 1)] * c_ok + [("COINCIDEN", 0)] * c_mal + [("DIVERGEN", 1)] * d_ok + [("DIVERGEN", 0)] * d_mal + [("SOLO_ESTADISTICO", 1), ("COINCIDEN", None)]


def test_con_pocos_casos_es_informativo_y_no_cambia_nada():
    r = d.medir(_filas(6, 3, 1, 2))
    assert r["coinciden"]["n"] == 9 and r["divergen"]["n"] == 3 and r["veredicto"] == "sin evidencia" and "informativo" in r["motivo"]
    assert abs(r["diferencia"] - (6 / 9 - 1 / 3)) < 1e-3


def test_sin_un_grupo_no_hay_comparacion():
    r = d.medir(_filas(5, 5, 0, 0))
    assert r["diferencia"] is None and r["veredicto"] == "sin evidencia" and "falta algún grupo" in r["motivo"]


def test_con_muestra_grande_y_diferencia_clara_el_veredicto_es_que_discrepar_predice_error():
    r = d.medir(_filas(420, 180, 150, 150))  # 70 % frente a 50 %
    assert r["veredicto"] == "discrepar predice error" and r["z"] >= 3


def test_con_muestra_grande_y_sin_diferencia_no_hay_veredicto():
    r = d.medir(_filas(300, 300, 150, 150))
    assert r["veredicto"] == "sin evidencia" and "sin significancia" in r["motivo"]


def test_el_intervalo_de_wilson_contiene_la_tasa_y_esta_en_0_1():
    lo, hi = d._wilson(6, 9)
    assert 0 <= lo < 6 / 9 < hi <= 1 and d._wilson(0, 0) is None


def test_lee_de_la_base_solo_los_dos_niveles(db_session):
    for i, (c, k) in enumerate([("COINCIDEN", 1), ("DIVERGEN", 0), ("SOLO_ESTADISTICO", 1), (None, 1)]):
        db_session.add(AnalisisComparativo(partido_id=f"p{i}", fecha="2026-11-01", consenso=c, pick_correcto=k, creado_en="2026-11-01"))
    db_session.commit()
    r = d.desde_base(db_session)
    assert r["coinciden"]["n"] == 1 and r["divergen"]["n"] == 1
