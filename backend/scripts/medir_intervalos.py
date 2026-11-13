"""Estudio de intervalos de credibilidad de las probabilidades (MP-16): ¿un posterior bayesiano completo (pymc/MCMC) aportaría algo sobre los intervalos que el modelo ya da (`incertidumbre.intervalo`, aproximación de
Laplace por el método delta, MM-14)?

Con una regresión logística sobre miles de partidos el posterior es casi gaussiano (Bernstein–von Mises) y la aproximación de Laplace coincide con el MCMC; esto lo comprueba con la referencia que SÍ discrimina y no
necesita instalar nada: un bootstrap no paramétrico de las filas de entrenamiento (B remuestreos, reajustando la regresión cada vez). En 3 ligas, sobre partidos fuera de muestra: ancho de los intervalos del 80 % de
P(local) por ambos métodos, su razón, la correlación de rangos (Spearman) entre los anchos partido a partido, cuántas veces el intervalo delta contiene la mediana del bootstrap, y el costo de cada uno.
Veredicto: si los dos métodos coinciden (correlación ≥ 0,9 y razón de anchos entre 0,8 y 1,25), un posterior MCMC no aporta y se descarta con esta medición.
Uso: python backend/scripts/medir_intervalos.py   (escribe backend/data/resultados/medicion_intervalos.json)
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from scipy.stats import spearmanr  # noqa: E402

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, incertidumbre  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_intervalos.json"
LIGAS = ("E0", "SP1", "I1")
CORTE = date(2022, 7, 1).toordinal()
B = 100
PARTIDOS_POR_LIGA = 500


def _p_local(pesos: list[list[float]], x: list[float]) -> float:
    return ent.probs_lineal(pesos, x)[0]


def medir() -> dict:
    partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = {c: ps for c, ps in datos.agrupar_por_liga(partidos).items() if c in LIGAS}
    filas, estados = [], {}
    for codigo, ps in por_liga.items():
        previos = [p for p in ps if p["dia"] < CORTE]
        f, estados[codigo] = ent._filas_entrenables(previos, ent.HIPER_DEFECTO)  # noqa: SLF001
        filas += f
    X, y = [x for x, _ in filas], [r for _, r in filas]
    pesos = ent.ajustar_logistica(X, y)
    cov = incertidumbre.covarianza_pesos(X, pesos, ent.L2)
    puntos = []
    for codigo, ps in por_liga.items():
        estado = estados[codigo]
        for p in sorted((p for p in ps if p["dia"] >= CORTE), key=lambda q: (q["dia"], q["local"]))[:PARTIDOS_POR_LIGA]:
            puntos.append(estado.features(p["local"], p["visitante"]))
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    t0 = time.perf_counter()
    delta = [incertidumbre.intervalo(cov, pesos, x)["p1x2_ic80"]["local"] for x in puntos]
    t_delta = time.perf_counter() - t0
    rng = random.Random(11)
    t0 = time.perf_counter()
    reajustes = []
    for _ in range(B):
        idx = [rng.randrange(len(X)) for _ in range(len(X))]
        reajustes.append(ent.ajustar_logistica([X[i] for i in idx], [y[i] for i in idx]))
    p_boot = [sorted(_p_local(w, x) for w in reajustes) for x in puntos]
    t_boot = time.perf_counter() - t0
    ancho_d = [d["alto"] - d["bajo"] for d in delta]
    ancho_b = [pb[int(0.9 * (B - 1))] - pb[int(0.1 * (B - 1))] for pb in p_boot]
    razones = [a / b for a, b in zip(ancho_d, ancho_b, strict=True) if b > 1e-9]
    contiene = sum(1 for d, pb in zip(delta, p_boot, strict=True) if d["bajo"] <= pb[B // 2] <= d["alto"]) / len(puntos)
    rho = float(spearmanr(ancho_d, ancho_b).statistic)
    razon = sum(razones) / len(razones)
    equivalentes = rho >= 0.9 and 0.8 <= razon <= 1.25
    return {"ligas": list(LIGAS), "entrenamiento_filas": len(X), "partidos_de_prueba": len(puntos), "remuestreos_bootstrap": B,
            "ancho_medio_ic80_delta": round(sum(ancho_d) / len(ancho_d), 4), "ancho_medio_ic80_bootstrap": round(sum(ancho_b) / len(ancho_b), 4),
            "razon_media_de_anchos_delta_sobre_bootstrap": round(razon, 3), "correlacion_de_rangos_de_los_anchos": round(rho, 3), "el_intervalo_delta_contiene_la_mediana_del_bootstrap": round(contiene, 4),
            "segundos_delta": round(t_delta, 3), "segundos_bootstrap": round(t_boot, 1),
            "veredicto": "equivalentes: un posterior MCMC (pymc) no aportaría sobre los intervalos delta; descartado" if equivalentes else "los métodos difieren: revisar antes de descartar el posterior bayesiano"}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False))
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
