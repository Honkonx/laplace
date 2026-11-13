"""MB-23: aporte de la IA medido con pares del laboratorio y veredicto honesto."""
from backend.api.models.predicciones import PronosticoExperimental as O
from backend.api.services import aporte_ia as a


def test_sin_pares_o_con_pocos_es_informativo():
    assert a.medir([])["veredicto"] == "sin evidencia"
    r = a.medir([(1.0, 0.9, 0.2, 0.19)] * 10)
    assert r["veredicto"] == "sin evidencia" and "informativo" in r["motivo"] and r["mejora_log_loss"] == 0.1


def test_con_muestra_grande_y_diferencia_clara_hay_veredicto():
    mejora = [(1.0 + (i % 7) * 0.01, 0.95 + (i % 7) * 0.01, 0.2, 0.19) for i in range(300)]
    peor = [(0.95 + (i % 7) * 0.01, 1.0 + (i % 7) * 0.01, 0.19, 0.2) for i in range(300)]
    assert a.medir(mejora)["veredicto"] == "la IA mejora el pronóstico" and "empeora" in a.medir(peor)["veredicto"]
    sin = [(1.0 + (i % 5) * 0.02, 1.0 + ((i + 1) % 5) * 0.02, 0.2, 0.2) for i in range(300)]
    assert a.medir(sin)["veredicto"] == "sin evidencia"


def test_lee_solo_partidos_con_las_dos_variantes(db_session):
    def f(i, variante, ll, rps):
        return O(partido_id=f"p{i}", experimento_codigo=variante, fecha_partido="2026-11-01", local="A", visitante="B", fuente="laplace", variante=variante, corte_datos_en="x", creado_en="x", log_loss=ll, rps=rps)

    db_session.add_all([f(1, a.BASE, 1.0, 0.2), f(1, a.CON_IA, 0.9, 0.19), f(2, a.BASE, 1.1, 0.21), f(3, a.CON_IA, 0.8, 0.1)])
    db_session.commit()
    r = a.desde_base(db_session)
    assert r["n"] == 1 and r["mejora_log_loss"] == 0.1
