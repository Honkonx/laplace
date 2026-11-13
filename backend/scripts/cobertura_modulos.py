"""Cuántos módulos de pronóstico votaron en los análisis guardados, por liga (solo lectura sobre `analisis_comparativo`).

Sirve para ver dónde el análisis se apoya en poco: una liga con 1 módulo de 7 produce un pronóstico poco respaldado y hay que mejorar sus datos antes que su modelo.
Uso: python backend/scripts/cobertura_modulos.py [--desde AAAA-MM-DD] [--db ruta]   (no escribe nada; imprime una tabla Markdown)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DB = RAIZ / "backend" / "db" / "bot_deportivo.db"
COLUMNAS = {"cuotas": "pick_odds", "tabla": "pick_tabla", "H2H": "pick_h2h", "forma": "pick_form", "Poisson/histórico": "pick_python", "externo": "pick_externo", "IA": "pick_claude"}


def resumen(db: Path, desde: str = "") -> list[dict]:
    """Una fila por liga: análisis, promedio de módulos votantes y cuántos análisis tuvieron cada fuente."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = ", ".join(COLUMNAS.values())
        filas = con.execute(f"SELECT liga, total_modulos, {cols} FROM analisis_comparativo WHERE creado_en >= ?", (desde or "0000",)).fetchall()
    finally:
        con.close()
    por: dict[str, list] = defaultdict(list)
    for f in filas:
        por[f[0] or "(sin liga)"].append(f)
    salida = []
    for liga, fs in por.items():
        n = len(fs)
        salida.append({"liga": liga, "analisis": n, "modulos_promedio": round(sum((f[1] or 0) for f in fs) / n, 2),
                       **{nombre: sum(1 for f in fs if f[2 + i] is not None) for i, nombre in enumerate(COLUMNAS)}})
    return sorted(salida, key=lambda r: (-r["analisis"], r["liga"]))


def tabla_markdown(filas: list[dict]) -> str:
    if not filas:
        return "Sin análisis guardados en ese periodo."
    nombres = list(COLUMNAS)
    out = ["| Liga | Análisis | Módulos (prom.) | " + " | ".join(nombres) + " |", "|---|---:|---:|" + "---:|" * len(nombres)]
    for r in filas:
        out.append(f"| {r['liga']} | {r['analisis']} | {r['modulos_promedio']} | " + " | ".join(str(r[n]) for n in nombres) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", default="")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()
    if not Path(a.db).exists():
        sys.exit(f"no existe la base: {a.db}")
    print(tabla_markdown(resumen(Path(a.db), a.desde)))
