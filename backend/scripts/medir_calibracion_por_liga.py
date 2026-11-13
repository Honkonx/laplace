"""Mide si calibrar por liga (temperatura propia de cada liga) mejora al modelo, fuera de muestra (MD-6).

Protocolo: el modelo se entrena con lo anterior a 2022-07-01; los 12 meses siguientes son la ventana de CALIBRACIÓN (donde se ajusta la temperatura: p' ∝ p^(1/T)) y todo lo posterior a 2023-07-01 es la PRUEBA
que ese ajuste no vio. Se compara, sobre los mismos partidos y de forma pareada (puerta común: ≥ 0,001 de log loss, z ≥ 3, IC95 sin cero): sin calibrar, temperatura global y temperatura por liga (con la global
en las ligas con menos de `MIN_CAL` partidos de calibración). También el error de calibración (ECE) y cuántas ligas mejoran o empeoran.
Uso: python backend/scripts/medir_calibracion_por_liga.py   (escribe backend/data/resultados/medicion_calibracion_por_liga.json)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, metricas  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent  # noqa: E402
from backend.scripts.medir_modelo_segmentos_y_cierre import filas_de_prueba  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_calibracion_por_liga.json"
CORTE_MODELO, CORTE_CAL_FIN = date(2022, 7, 1).toordinal(), date(2023, 7, 1).toordinal()
MIN_CAL = 150
MIN_PRUEBA_LIGA = 300
N_BOOT = 200


def aplicar_temperatura(p: tuple[float, float, float], t: float) -> tuple[float, float, float]:
    z = [max(x, 1e-12) ** (1.0 / t) for x in p]
    s = sum(z)
    return z[0] / s, z[1] / s, z[2] / s


def ajustar_temperatura(filas: list[tuple[tuple[float, float, float], str]]) -> float:
    """T que minimiza el log loss en `filas` (búsqueda por sección áurea en [0,5; 2,5]); 1,0 = sin cambio."""
    def perdida(t: float) -> float:
        return sum(metricas.log_loss(aplicar_temperatura(p, t), r) for p, r in filas) / len(filas)

    a, b, fi = 0.5, 2.5, (math.sqrt(5) - 1) / 2
    c, d = b - fi * (b - a), a + fi * (b - a)
    for _ in range(40):
        if perdida(c) < perdida(d):
            b = d
        else:
            a = c
        c, d = b - fi * (b - a), a + fi * (b - a)
    return round((a + b) / 2, 4)


def _comparar(filas: list[dict], clave_ref: str, clave_cand: str) -> dict | None:
    if len(filas) < 30:
        return None
    r = comparacion.comparar_predicciones([(f[clave_ref], f["r"]) for f in filas], [(f[clave_cand], f["r"]) for f in filas], bloques=[f["dia"] // 7 for f in filas], n_boot=N_BOOT)
    return {"n": r["n"], "mejora_log_loss": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1), "cumple_la_puerta": bool(r["acepta"])}


def medir() -> dict:
    filas = filas_de_prueba(CORTE_MODELO)  # recorrido sin ver el futuro desde el corte del modelo
    cal = [f for f in filas if f["dia"] < CORTE_CAL_FIN]
    prueba = [f for f in filas if f["dia"] >= CORTE_CAL_FIN]
    t_global = ajustar_temperatura([(f["p"], f["r"]) for f in cal])
    t_liga: dict[str, float] = {}
    for liga in {f["liga"] for f in cal}:
        propias = [(f["p"], f["r"]) for f in cal if f["liga"] == liga]
        if len(propias) >= MIN_CAL:
            t_liga[liga] = ajustar_temperatura(propias)
    for f in prueba:
        f["glob"] = aplicar_temperatura(f["p"], t_global)
        f["liga_cal"] = aplicar_temperatura(f["p"], t_liga.get(f["liga"], t_global))
    por_liga = []
    for liga in sorted({f["liga"] for f in prueba}):
        g = [f for f in prueba if f["liga"] == liga]
        if len(g) >= MIN_PRUEBA_LIGA:
            por_liga.append({"liga": liga, "n_prueba": len(g), "temperatura": t_liga.get(liga, t_global), "propia": liga in t_liga, "vs_sin_calibrar": _comparar(g, "p", "liga_cal")})
    mejoran = sum(1 for x in por_liga if x["vs_sin_calibrar"] and x["vs_sin_calibrar"]["mejora_log_loss"] > 0)
    ece = {nombre: round(ent.ece([(f[clave], f["r"]) for f in prueba]) or 0.0, 5) for nombre, clave in (("sin_calibrar", "p"), ("temperatura_global", "glob"), ("temperatura_por_liga", "liga_cal"))}
    return {"corte_del_modelo": "2022-07-01", "calibracion": "2022-07-01 a 2023-07-01", "prueba_desde": "2023-07-01", "partidos_calibracion": len(cal), "partidos_prueba": len(prueba),
            "temperatura_global": t_global, "ligas_con_temperatura_propia": len(t_liga),
            "global_vs_sin_calibrar": _comparar(prueba, "p", "glob"), "por_liga_vs_sin_calibrar": _comparar(prueba, "p", "liga_cal"), "por_liga_vs_global": _comparar(prueba, "glob", "liga_cal"),
            "ece_en_prueba": ece, "ligas_evaluadas": len(por_liga), "ligas_que_mejoran": mejoran, "por_liga": por_liga}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"temperatura global {informe['temperatura_global']} · ligas con T propia {informe['ligas_con_temperatura_propia']} · prueba {informe['partidos_prueba']}")
    for k in ("global_vs_sin_calibrar", "por_liga_vs_sin_calibrar", "por_liga_vs_global"):
        print(k, informe[k])
    print("ECE", informe["ece_en_prueba"], "· ligas que mejoran", informe["ligas_que_mejoran"], "de", informe["ligas_evaluadas"])
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
