"""versiones.py — compara DOS versiones del modelo (dos conjuntos de hiperparámetros/variables) sobre los mismos partidos, con significancia (MM-00 + MM-10 del plan).

Entrena cada versión SOLO con lo anterior al corte, recorre la prueba avanzando el estado partido a partido (sin reentrenar pesos) y compara con `ml/comparacion.py`:
global, ligas que traen tiros y ligas que no. Una versión nueva entra a sombra solo si cumple la puerta: ≥ 0,001 de log loss, z ≥ 3 e IC95 sin cero (el plan de mejoras (repo de trabajo) §1).
"""
from __future__ import annotations

from backend.api.ml import comparacion
from backend.api.ml.laplace import entrenamiento as e


def comparar_versiones(por_liga: dict[str, list[dict]], corte: int, hiper_a: dict, hiper_b: dict, hasta: int | None = None, n_boot: int = 300) -> dict:
    """`a` = versión de referencia, `b` = candidata. Diferencias positivas = la candidata es mejor."""
    art_a = e.entrenar_jerarquico(por_liga, corte, hiper=hiper_a, con_goles=False)
    art_b = e.entrenar_jerarquico(por_liga, corte, hiper=hiper_b, con_goles=False)
    filas = []  # (semana, probs a, probs b, resultado, liga, ¿la liga trae tiros?)
    por_liga_n: dict[str, int] = {}
    for codigo in sorted(set(art_a["ligas"]) & set(art_b["ligas"])):
        info_a, info_b = art_a["ligas"][codigo], art_b["ligas"][codigo]
        est_a, est_b = e.EstadoLiga.de_dict(info_a["estado"]), e.EstadoLiga.de_dict(info_b["estado"])
        con_tiros = est_b.n_tiros > 0
        w_a, w_b = e.pesos_de(art_a, codigo), e.pesos_de(art_b, codigo)
        for p in sorted((q for q in por_liga[codigo] if corte <= q["dia"] < (hasta or 10**9)), key=lambda x: (x["dia"], x["local"])):
            filas.append((p["dia"] // 7, e.probs_lineal(w_a, est_a.features(p["local"], p["visitante"])), e.probs_lineal(w_b, est_b.features(p["local"], p["visitante"])),
                          p["resultado"], codigo, con_tiros))
            t = e.tiros_de(p)
            est_a.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], t)
            est_b.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], t)
            por_liga_n[codigo] = por_liga_n.get(codigo, 0) + 1

    def comparar(sel) -> dict | None:
        f = [x for x in filas if sel(x)]
        if len(f) < 30:
            return None
        return comparacion.comparar_predicciones([(x[1], x[3]) for x in f], [(x[2], x[3]) for x in f], bloques=[x[0] for x in f], n_boot=n_boot)

    por_liga_dif = {}
    for codigo, n in por_liga_n.items():
        if n >= 150:
            r = comparar(lambda x, c=codigo: x[4] == c)
            if r:
                por_liga_dif[codigo] = {"n": n, "diferencia_media": round(r["diferencia_media"], 5), "z": round(r["z"], 2)}
    return {"n": len(filas), "global": comparar(lambda x: True), "ligas_con_tiros": comparar(lambda x: x[5]), "ligas_sin_tiros": comparar(lambda x: not x[5]),
            "por_liga": por_liga_dif, "veredicto": {k: comparacion.veredicto(v) for k, v in (("global", comparar(lambda x: True)), ("ligas_con_tiros", comparar(lambda x: x[5]))) if v}}
