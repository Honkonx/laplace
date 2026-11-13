"""Mide, fuera de muestra, si la predicción conforme (`ml/laplace/conformal.py`) cumple su cobertura con los datos y el modelo REALES de Laplace.

Para cada liga se reconstruye el estado partido a partido (sin ver el futuro: `entrenamiento.recorrer`), se calcula la probabilidad 1X2 con los pesos universales del modelo vigente y se separa el tiempo:
CALIBRACIÓN = los 12 meses anteriores a los 12 de PRUEBA (que terminan en la fecha de corte del modelo). El umbral se calibra solo con la ventana de calibración y se evalúa en la de prueba.
Compara umbral global (todas las ligas juntas) con umbral por liga, e informa cobertura, tamaño medio del conjunto y la cobertura por liga (mínima y dispersión).

Uso: python backend/scripts/evaluar_conformal.py   (escribe backend/data/resultados/evaluacion_conformal.json)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import conformal, entrenamiento as ent, registro  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "evaluacion_conformal.json"
ALFAS = (0.20, 0.10)
VENTANA_DIAS = 365
MIN_CALIBRACION_LIGA = 150


def predicciones_por_liga() -> tuple[dict[str, list[tuple[int, tuple[float, float, float], str]]], int]:
    """{liga: [(día, p1x2, resultado)]} sin ver el futuro, y el día de corte del modelo vigente."""
    _, art = registro.cargar_vigente_archivo()
    if not art:
        raise SystemExit("no hay modelo vigente")
    hiper, pesos, corte = art.get("hiper") or {}, art["universal"], art["fecha_corte"]
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    salida = {}
    for codigo, ps in por_liga.items():
        if codigo not in art["ligas"]:
            continue
        ordenados = sorted(ps, key=lambda x: (x["dia"], x["local"]))  # el mismo orden que `recorrer`
        filas, _ = ent.recorrer(ordenados, hiper)
        salida[codigo] = [(p["dia"], ent.probs_lineal(pesos, x), r) for p, (x, r) in zip(ordenados, filas, strict=True) if p["dia"] < corte]
    return salida, corte


def evaluar() -> dict:
    por_liga, corte = predicciones_por_liga()
    inicio_prueba, inicio_calibracion = corte - VENTANA_DIAS, corte - 2 * VENTANA_DIAS
    calib = {l: [(p, r) for d, p, r in v if inicio_calibracion <= d < inicio_prueba] for l, v in por_liga.items()}
    prueba = {l: [(p, r) for d, p, r in v if d >= inicio_prueba] for l, v in por_liga.items()}
    ligas = [l for l in prueba if len(calib[l]) >= MIN_CALIBRACION_LIGA and prueba[l]]
    informe: dict = {"nota": "calibración = 12 meses previos a la prueba; prueba = 12 meses hasta el corte del modelo; pesos universales del modelo vigente", "ligas_evaluadas": len(ligas),
                     "partidos_calibracion": sum(len(calib[l]) for l in ligas), "partidos_prueba": sum(len(prueba[l]) for l in ligas), "por_alfa": {}}
    todos_calib = [conformal.puntuacion(p, r) for l in ligas for p, r in calib[l]]
    for alfa in ALFAS:
        q_global = conformal.umbral(todos_calib, alfa)
        cob_global, tam_global, cob_por_liga, cob_liga_propia, tam_liga_propia = 0.0, 0.0, [], 0.0, 0.0
        total = sum(len(prueba[l]) for l in ligas)
        for l in ligas:
            c, t = conformal.cobertura_y_tamano(prueba[l], q_global)
            cob_global += c * len(prueba[l]) / total
            tam_global += t * len(prueba[l]) / total
            cob_por_liga.append((c, l, len(prueba[l])))
            q_l = conformal.umbral([conformal.puntuacion(p, r) for p, r in calib[l]], alfa)
            c2, t2 = conformal.cobertura_y_tamano(prueba[l], q_l)
            cob_liga_propia += c2 * len(prueba[l]) / total
            tam_liga_propia += t2 * len(prueba[l]) / total
        grandes = [(c, l) for c, l, n in cob_por_liga if n >= 150]
        informe["por_alfa"][str(alfa)] = {
            "cobertura_nominal": round(1 - alfa, 2), "umbral_global": round(q_global, 4) if q_global is not None else None,
            "global": {"cobertura": round(cob_global, 4), "tamano_medio": round(tam_global, 3)},
            "por_liga_propia": {"cobertura": round(cob_liga_propia, 4), "tamano_medio": round(tam_liga_propia, 3)},
            "peor_liga_con_150_o_mas_partidos_de_prueba": {"cobertura": round(min(grandes)[0], 4), "liga": min(grandes)[1]} if grandes else None,
            "ligas_por_debajo_de_la_nominal_menos_5_puntos": sum(1 for c, _l in grandes if c < 1 - alfa - 0.05),
            "ligas_grandes": len(grandes),
        }
    return informe


if __name__ == "__main__":
    r = evaluar()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(r, indent=2, ensure_ascii=False))
