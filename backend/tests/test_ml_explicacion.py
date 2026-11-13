"""MB-41: el «por qué» es exacto: las contribuciones suman el logit y el logit es ln(p_local/p_visitante)."""
import math

from backend.api.ml.laplace import entrenamiento as e
from backend.api.ml.laplace import explicacion

NOMBRES = ["sesgo", "dif_elo", "log_lambda_local", "log_lambda_visitante", "dif_experiencia"]
PESOS = [[0.20, 1.10, 0.40, -0.30, 0.05], [-0.10, -0.20, 0.10, 0.10, 0.00], [-0.10, -0.90, -0.50, 0.20, -0.05]]
X = [1.0, 0.35, 0.30, -0.10, 0.15]


def test_las_contribuciones_suman_el_logit_y_este_es_el_log_cociente_de_probabilidades():
    r = explicacion.contribuciones(PESOS, X, NOMBRES)
    suma = r["sesgo"]["local_vs_visitante"] + sum(f["local_vs_visitante"] for f in r["variables"])
    assert abs(suma - r["logit_local_vs_visitante"]) < 1e-3
    p = e.probs_lineal(PESOS, X)
    assert abs(r["logit_local_vs_visitante"] - math.log(p[0] / p[2])) < 1e-3
    suma_e = r["sesgo"]["empate_vs_extremos"] + sum(f["empate_vs_extremos"] for f in r["variables"])
    assert abs(suma_e - r["logit_empate_vs_extremos"]) < 1e-3


def test_las_variables_vienen_ordenadas_por_importancia_y_sin_el_sesgo():
    r = explicacion.contribuciones(PESOS, X, NOMBRES)
    magnitudes = [abs(f["local_vs_visitante"]) for f in r["variables"]]
    assert magnitudes == sorted(magnitudes, reverse=True) and all(f["variable"] != "sesgo" for f in r["variables"]) and r["variables"][0]["variable"] == "dif_elo"


def test_explicar_liga_devuelve_none_si_la_liga_no_esta_y_coincide_con_la_prediccion():
    estado = e.EstadoLiga()
    for i in range(30):
        estado.actualizar("A", "B", 2, 1) if i % 2 == 0 else estado.actualizar("B", "A", 0, 1)
    art = {"familia": e.FAMILIA_JERARQUICA, "universal": PESOS, "hiper": {"extras": []}, "ligas": {"X": {"estado": estado.a_dict()}}}
    assert explicacion.explicar_liga(art, "Y", "A", "B") is None
    r = explicacion.explicar_liga(art, "X", "A", "B")
    p = e.predecir_liga(art, "X", "A", "B")["p1x2"]
    assert abs(r["p1x2"]["local"] - p[0]) < 1e-9 and abs(r["comprobacion_logit"] - r["logit_local_vs_visitante"]) < 1e-3


def test_los_nombres_coinciden_con_las_columnas_aunque_un_extra_ocupe_varias():
    for extras in ([], ["abs_elo", "forma"], ["abs_elo", "forma", "tiros"], ["abs_elo", "forma", "localia"]):
        estado = e.EstadoLiga(extras=tuple(extras))
        assert len(explicacion.nombres_de_variables(extras)) == len(estado.features("A", "B")), extras


def test_la_localia_por_equipo_se_actualiza_y_sobrevive_a_la_serializacion():
    est = e.EstadoLiga(extras=("localia",))
    for _ in range(20):
        est.actualizar("Casero", "Otro", 3, 0)  # gana en casa por mucho más que la liga
    assert est.dev_h["Casero"] > 0.5 and est.dev_a["Otro"] < -0.5
    copia = e.EstadoLiga.de_dict(est.a_dict())
    assert copia.dev_h == est.dev_h and copia.features("Casero", "Otro") == est.features("Casero", "Otro")
    sin = e.EstadoLiga()
    sin.actualizar("Casero", "Otro", 3, 0)
    assert sin.dev_h == {}  # sin el extra no se acumula nada
