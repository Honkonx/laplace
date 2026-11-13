"""comparar_versiones_modelo.py — compara dos versiones del modelo Laplace con significancia (walk-forward, mismos partidos, corte fijo).

  python backend/scripts/comparar_versiones_modelo.py --a g3 --b v1.1
  python backend/scripts/comparar_versiones_modelo.py --a g3 --b v1.1 --corte 2022-07-01 --hasta 2023-07-01   # un pliegue de validación móvil

Entrena cada versión solo con lo anterior al corte; diferencias positivas = `b` mejor. Escribe `backend/data/datos/resultados/comparacion_<a>_vs_<b>.json` (datos locales, no se publican).
Solo lectura de los CSV históricos; no toca la base de datos.
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
from backend.api.ml.laplace import entrenamiento, versiones  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "datos" / "resultados"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="g3", choices=sorted(entrenamiento.HIPERS))
    ap.add_argument("--b", default="v1.1", choices=sorted(entrenamiento.HIPERS))
    ap.add_argument("--corte", default="2023-07-01")
    ap.add_argument("--hasta", default=None)
    args = ap.parse_args()
    corte = date.fromisoformat(args.corte).toordinal()
    hasta = date.fromisoformat(args.hasta).toordinal() if args.hasta else None
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    r = versiones.comparar_versiones(por_liga, corte, entrenamiento.HIPERS[args.a], entrenamiento.HIPERS[args.b], hasta=hasta)
    for clave, texto in r["veredicto"].items():
        print(f"{clave}: {args.b} frente a {args.a} {texto}")
    print(json.dumps({k: r[k] for k in ("n", "por_liga")}, indent=1))
    SALIDA.mkdir(parents=True, exist_ok=True)
    archivo = SALIDA / f"comparacion_{args.a}_vs_{args.b}.json".replace("/", "_")
    archivo.write_text(json.dumps({"corte": args.corte, "hasta": args.hasta, **r}, indent=1, default=list), encoding="utf-8")
    print(f"escrito {archivo.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
