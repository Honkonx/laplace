"""ml/laplace/explicacion.py — el «por qué» de un pronóstico 1x2, exacto para una regresión logística (MB-41).

El modelo es lineal en los logits: `z_clase = Σ peso_clase,k · x_k`. Por eso la contribución de cada variable al logit de «local frente a visitante» es exactamente
`(peso_local,k − peso_visitante,k) · x_k`, sin aproximaciones (no hace falta SHAP). Las contribuciones más el sesgo suman el logit total, y ese logit es `ln(p_local / p_visitante)`:
la prueba lo comprueba. Lo mismo para el empate frente al promedio de los dos extremos. Es descriptivo: no cambia ninguna cifra.
"""
from __future__ import annotations

import math

from backend.api.ml.laplace import entrenamiento as e
from backend.api.ml.laplace import variables


_NOMBRES_DE_EXTRA = {"localia": ["localia_local", "localia_visitante"], "tiros": ["tiros_local", "tiros_visitante", "tiros_arco_local", "tiros_arco_visitante"]}


def nombres_de_variables(extras) -> list[str]:
    """Un nombre por cada columna del vector de características, en el mismo orden (hay extras que ocupan varias columnas)."""
    nombres = list(variables.BASE)
    for extra in extras:
        nombres += _NOMBRES_DE_EXTRA.get(extra, [extra])
    return nombres


def contribuciones(pesos: list[list[float]], x: list[float], nombres: list[str]) -> dict:
    """pesos = [local, empate, visitante] × variables; x = valores de las variables. Devuelve las contribuciones al logit local-vs-visitante y empate-vs-extremos."""
    local, empate, visita = pesos[0], pesos[1], pesos[2]
    filas = []
    for k, (nombre, valor) in enumerate(zip(nombres, x)):
        filas.append({"variable": nombre, "valor": round(valor, 4), "local_vs_visitante": round((local[k] - visita[k]) * valor, 4),
                      "empate_vs_extremos": round((empate[k] - (local[k] + visita[k]) / 2) * valor, 4)})
    sesgo = next((f for f in filas if f["variable"] == "sesgo"), None)
    resto = [f for f in filas if f["variable"] != "sesgo"]
    resto.sort(key=lambda f: -abs(f["local_vs_visitante"]))
    total_lv = sum((local[k] - visita[k]) * v for k, v in enumerate(x))
    total_ev = sum((empate[k] - (local[k] + visita[k]) / 2) * v for k, v in enumerate(x))
    return {"variables": resto, "sesgo": sesgo, "logit_local_vs_visitante": round(total_lv, 4), "logit_empate_vs_extremos": round(total_ev, 4)}


def explicar_liga(artefacto: dict, liga: str, local: str, visitante: str) -> dict | None:
    """El «por qué» del pronóstico de un partido con el modelo jerárquico; None si la liga no está en el modelo."""
    info = artefacto["ligas"].get(liga)
    if info is None:
        return None
    estado = e.EstadoLiga.de_dict(info["estado"])
    x = estado.features(local, visitante)
    pesos = e.pesos_de(artefacto, liga)
    nombres = nombres_de_variables((artefacto.get("hiper") or {}).get("extras", estado.extras))
    p = e.probs_lineal(pesos, x)
    salida = contribuciones(pesos, x, nombres)
    salida["p1x2"] = {"local": p[0], "empate": p[1], "visitante": p[2]}
    salida["comprobacion_logit"] = round(math.log(p[0] / p[2]), 4)
    return salida
