"""evaluar_modelo_laplace.py — mide el modelo propio de Laplace con PARTIDOS REALES, walk-forward, contra tasa base, Dixon-Coles y mercado.

  python backend/scripts/evaluar_modelo_laplace.py                 # las 6 ligas con más partidos
  python backend/scripts/evaluar_modelo_laplace.py --ligas E0 SP1  # ligas concretas
  python backend/scripts/evaluar_modelo_laplace.py --max-ligas 14  # todas las que se puedan

Desarrollo < 2023-07-01 (se entrena); prueba >= 2023-07-01 (nunca vista al entrenar). Escribe `backend/data/datos/resultados/evaluacion_modelo_laplace.json`
(datos locales, no se publican). Solo lectura de los CSV históricos; no toca la base de datos.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento  # noqa: E402

CORTE = date(2023, 7, 1).toordinal()
SALIDA = RAIZ / "backend" / "data" / "datos" / "resultados" / "evaluacion_modelo_laplace.json"
MIN_PRUEBA = 150


def evaluar_liga(partidos: list[dict]) -> dict | None:
    if sum(1 for p in partidos if p["dia"] >= CORTE) < MIN_PRUEBA or sum(1 for p in partidos if p["dia"] < CORTE) < 300:
        return None
    return entrenamiento.evaluar_comparando(partidos, CORTE)["informe"]


def agregar(informes: dict[str, dict]) -> dict:
    """Promedia ponderado por partidos de prueba (cada liga pesa lo que tiene)."""
    total = sum(i["n_prueba"] for i in informes.values())
    out = {"n_prueba": total, "ligas": len(informes), "propio": {}, "referencias": {}}
    for clave in ("log_loss", "rps", "brier", "ece"):
        out["propio"][clave] = round(sum(i["propio"][clave] * i["n_prueba"] for i in informes.values()) / total, 5)
    for ref in ("tasa_base", "dixon_coles", "mercado"):
        con = {k: i for k, i in informes.items() if ref in i["referencias"]}
        n = sum(i["referencias"][ref]["n"] for i in con.values())
        if n:
            out["referencias"][ref] = {"n": n, **{c: round(sum(i["referencias"][ref][c] * i["referencias"][ref]["n"] for i in con.values()) / n, 5) for c in ("log_loss", "rps")}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ligas", nargs="*")
    ap.add_argument("--max-ligas", type=int, default=6)
    args = ap.parse_args()
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    codigos = args.ligas or [c for c, _ in sorted(por_liga.items(), key=lambda kv: -len(kv[1]))][: args.max_ligas]
    informes = {}
    for codigo in codigos:
        informe = evaluar_liga(por_liga.get(codigo, []))
        if informe is None:
            print(f"{codigo}: sin partidos suficientes")
            continue
        informes[codigo] = informe
        print(f"{codigo}: n_prueba={informe['n_prueba']} propio={informe['propio']['log_loss']} dc={informe['referencias'].get('dixon_coles', {}).get('log_loss')} "
              f"base={informe['referencias']['tasa_base']['log_loss']} mercado={informe['referencias'].get('mercado', {}).get('log_loss')}")
    if not informes:
        return 1
    resumen = agregar(informes)
    print(json.dumps(resumen, indent=1))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({"corte": "2023-07-01", "resumen": resumen, "por_liga": informes}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
