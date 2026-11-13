"""Mide si encoger el Elo hacia la media al cambiar de temporada (la «regresión a la media» del Elo de NHL y NFL) mejora el pronóstico 1X2 de Laplace.

Se reconstruye el estado partido a partido por liga SIN ver el futuro (misma recurrencia que `entrenamiento.recorrer`); al cambiar la temporada, el Elo de cada equipo se encoge: `1500 + (1 − r)·(elo − 1500)`. Para cada `r` se evalúa en el periodo de prueba (desde 2023-07-01, que ningún ajuste ve):
- A) con los pesos del modelo vigente (entrenados con r = 0: conservador, favorece al valor actual);
- B) con pesos REENTRENADOS para cada `r` solo con el periodo de desarrollo (más justo: la logística se adapta a la nueva escala del Elo).
Informa log loss y RPS agrupados, la diferencia pareada frente a r = 0 con su z, y en cuántas ligas mejora.

Uso: python backend/scripts/evaluar_regresion_temporada.py   (escribe backend/data/resultados/evaluacion_regresion_temporada.json)
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, registro  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "evaluacion_regresion_temporada.json"
CLASES = ("H", "D", "A")
VALORES_R = (0.0, 0.10, 0.20, 0.30)
CORTE_PRUEBA = date(2023, 7, 1).toordinal()
MUESTRA_ENTRENAMIENTO = 30_000
EPOCAS = 150


def rps(p: tuple[float, float, float], r: str) -> float:
    o = [1.0 if r == c else 0.0 for c in CLASES]
    return sum((sum(p[: i + 1]) - sum(o[: i + 1])) ** 2 for i in range(2)) / 2


def logloss(p: tuple[float, float, float], r: str) -> float:
    return -math.log(max(p[CLASES.index(r)], 1e-9))


def filas_con_regresion(por_liga: dict, ligas: list[str], hiper: dict, r: float) -> list[tuple[str, int, list[float], str]]:
    """[(liga, día, variables ANTES del partido, resultado)] con el Elo encogido en cada cambio de temporada."""
    salida = []
    for codigo in ligas:
        estado = ent.EstadoLiga(k_elo=hiper.get("k_elo", ent.K_ELO), alfa=hiper.get("alfa", ent.ALFA_GOLES), extras=tuple(hiper.get("extras", ())))
        temporada = None
        for p in sorted(por_liga[codigo], key=lambda x: (x["dia"], x["local"])):
            if temporada is not None and p["temporada"] != temporada and r > 0:
                for k in list(estado.elo):
                    estado.elo[k] = 1500.0 + (1.0 - r) * (estado.elo[k] - 1500.0)
            temporada = p["temporada"]
            salida.append((codigo, p["dia"], estado.features(p["local"], p["visitante"]), p["resultado"]))
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    return salida


def evaluar() -> dict:
    _, art = registro.cargar_vigente_archivo()
    if not art:
        raise SystemExit("no hay modelo vigente")
    hiper, pesos_vigentes = art.get("hiper") or {}, art["universal"]
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    ligas = [c for c in art["ligas"] if c in por_liga]
    azar = random.Random(11)
    resultados: dict[float, dict] = {}
    base_a: list[tuple[float, float]] | None = None
    base_b: list[tuple[float, float]] | None = None
    for r in VALORES_R:
        filas = filas_con_regresion(por_liga, ligas, hiper, r)
        prueba = [f for f in filas if f[1] >= CORTE_PRUEBA and f[1] < art["fecha_corte"]]
        desarrollo = [f for f in filas if f[1] < CORTE_PRUEBA]
        muestra = azar.sample(desarrollo, min(MUESTRA_ENTRENAMIENTO, len(desarrollo)))
        pesos_b = ent.ajustar_logistica([f[2] for f in muestra], [f[3] for f in muestra], EPOCAS)
        a = [(logloss(p := ent.probs_lineal(pesos_vigentes, f[2]), f[3]), rps(p, f[3])) for f in prueba]
        b = [(logloss(p := ent.probs_lineal(pesos_b, f[2]), f[3]), rps(p, f[3])) for f in prueba]
        if r == 0.0:
            base_a, base_b = a, b
        resumen = {"partidos_prueba": len(prueba)}
        for nombre, valores, base in (("pesos_vigentes", a, base_a), ("pesos_reentrenados", b, base_b)):
            d_ll = [x[0] - y[0] for x, y in zip(valores, base, strict=True)]
            d_rps = [x[1] - y[1] for x, y in zip(valores, base, strict=True)]
            media = lambda v: sum(v) / len(v)  # noqa: E731
            ee = lambda v: (sum((x - media(v)) ** 2 for x in v) / max(len(v) - 1, 1)) ** 0.5 / math.sqrt(len(v))  # noqa: E731
            resumen[nombre] = {"log_loss": round(media([x[0] for x in valores]), 5), "rps": round(media([x[1] for x in valores]), 5),
                               "dif_log_loss_frente_a_r0": round(media(d_ll), 5), "z_log_loss": round(media(d_ll) / ee(d_ll), 2) if r > 0 and ee(d_ll) else None,
                               "dif_rps_frente_a_r0": round(media(d_rps), 5), "z_rps": round(media(d_rps) / ee(d_rps), 2) if r > 0 and ee(d_rps) else None}
            if r > 0:  # en cuántas ligas mejora el log loss
                por = {}
                for f, x, y in zip(prueba, valores, base, strict=True):
                    por.setdefault(f[0], []).append(x[0] - y[0])
                resumen[nombre]["ligas_que_mejoran"] = f"{sum(1 for v in por.values() if sum(v) < 0)} de {len(por)}"
        resultados[r] = resumen
    return {"nota": "periodo de prueba 2023-07-01 hasta el corte del modelo; dif negativa = mejor que r = 0", "r": {str(k): v for k, v in resultados.items()}}


if __name__ == "__main__":
    informe = evaluar()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(informe, indent=2, ensure_ascii=False))
