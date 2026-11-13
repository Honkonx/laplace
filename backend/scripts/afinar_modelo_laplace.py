"""afinar_modelo_laplace.py — elige hiperparámetros y características del modelo Laplace SIN mirar el periodo de prueba.

  python backend/scripts/afinar_modelo_laplace.py                # rejilla completa, informe en pantalla y JSON
  python backend/scripts/afinar_modelo_laplace.py --confirmar    # además mide al ganador en el periodo de prueba (UNA sola vez)

Protocolo (`evidencia-historica-antes-de-promover.md`): entrenamiento < 2021-07-01, VALIDACIÓN [2021-07-01, 2023-07-01), PRUEBA >= 2023-07-01. La rejilla se compara solo en validación;
el ganador debe vencer a la configuración actual por un margen mínimo (evita premiar el ruido) y solo entonces se mide en prueba, una vez, contra la configuración actual.
Escribe `backend/data/datos/resultados/afinacion_modelo_laplace.json` (datos locales, no se publican).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento  # noqa: E402

CORTE_VALIDACION = date(2021, 7, 1).toordinal()
CORTE_PRUEBA = date(2023, 7, 1).toordinal()
SALIDA = RAIZ / "backend" / "data" / "datos" / "resultados" / "afinacion_modelo_laplace.json"
ACTUAL = {"k_elo": entrenamiento.K_ELO, "alfa": entrenamiento.ALFA_GOLES, "extras": []}
MARGEN_MINIMO = 0.0005  # log loss: por debajo de esto la diferencia es ruido
REJILLA = {"k_elo": [16.0, 24.0, 32.0], "alfa": [0.08, 0.12, 0.18], "extras": [[], ["abs_elo"], ["forma"], ["abs_elo", "forma"]]}
# Segunda ronda (2026-11-10): el ganador de la primera quedó en el borde de la rejilla (k=16, alfa=0,08); se explora hacia abajo, siempre solo en validación.
REJILLA_AMPLIADA = {"k_elo": [8.0, 12.0, 16.0], "alfa": [0.04, 0.06, 0.08], "extras": [["abs_elo", "forma"]]}


def medir(por_liga: dict, desde: int, hasta: int | None, hiper: dict) -> dict:
    inf = entrenamiento.evaluar_jerarquico(por_liga, desde, con_dixon_coles=False, hiper=hiper, hasta=hasta, especializar=False)["informe"]
    return {"n": inf["n_prueba"], **inf["resumen"]["universal"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--ampliar", action="store_true", help="segunda ronda hacia valores más bajos (el ganador anterior estaba en el borde)")
    args = ap.parse_args()
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    resultados = []
    rejilla = REJILLA_AMPLIADA if args.ampliar else REJILLA
    for k, a, ex in itertools.product(rejilla["k_elo"], rejilla["alfa"], rejilla["extras"]):
        hiper = {"k_elo": k, "alfa": a, "extras": ex}
        m = medir(por_liga, CORTE_VALIDACION, CORTE_PRUEBA, hiper)
        resultados.append({"hiper": hiper, "validacion": m})
        print(f"k={k} alfa={a} extras={ex}: n={m['n']} log_loss={m['log_loss']} rps={m['rps']}", flush=True)
    resultados.sort(key=lambda r: r["validacion"]["log_loss"])
    actual = next((r for r in resultados if r["hiper"] == ACTUAL), None) or {"hiper": ACTUAL, "validacion": medir(por_liga, CORTE_VALIDACION, CORTE_PRUEBA, ACTUAL)}
    ganador = resultados[0]
    mejora = actual["validacion"]["log_loss"] - ganador["validacion"]["log_loss"]
    informe = {"validacion": {"actual": actual, "ganador": ganador, "mejora_log_loss": round(mejora, 5), "supera_margen": mejora >= MARGEN_MINIMO}, "rejilla": resultados}
    if args.confirmar and mejora >= MARGEN_MINIMO:
        informe["prueba"] = {"actual": medir(por_liga, CORTE_PRUEBA, None, ACTUAL), "ganador": medir(por_liga, CORTE_PRUEBA, None, ganador["hiper"])}
        informe["prueba"]["mejora_log_loss"] = round(informe["prueba"]["actual"]["log_loss"] - informe["prueba"]["ganador"]["log_loss"], 5)
    print(json.dumps({k: v for k, v in informe.items() if k != "rejilla"}, indent=1, ensure_ascii=False))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
