"""medir_cobertura_historico.py — mide qué fracción de los partidos reales resuelve el módulo `historico`.

Solo lectura: abre `backend/db/bot_deportivo.db` con `mode=ro` y llama a
`modelo_historico.validar_historico`. No escribe nada (ni en la BD ni en disco).
Es idempotente: re-ejecutarlo da el mismo resultado mientras no cambien BD ni artefactos.

Uso:
    python -m backend.scripts.medir_cobertura_historico [--desde 2026-09-24] [--top 25]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.api.services import modelo_historico as mh  # noqa: E402

RUTA_BD = REPO / "backend" / "db" / "bot_deportivo.db"


def _conectar() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{RUTA_BD.as_posix()}?mode=ro", uri=True)


def _partidos_dia(con: sqlite3.Connection, desde: str) -> list[dict]:
    filas = con.execute(
        "SELECT liga_nombre, liga_codigo, local, visitante FROM partidos_dia "
        "WHERE fecha >= ? AND local IS NOT NULL AND visitante IS NOT NULL", (desde,))
    out = []
    for liga, codigo, local, visitante in filas:
        d = {"liga": liga or "", "local": local, "visitante": visitante}
        if codigo and str(codigo).isdigit():
            d["liga_id"] = int(codigo)
        out.append(d)
    return out


def _analisis(con: sqlite3.Connection) -> list[dict]:
    filas = con.execute("SELECT liga, local, visitante FROM analisis_comparativo")
    return [{"liga": liga or "", "local": local, "visitante": visitante} for liga, local, visitante in filas]


def _medir(nombre: str, partidos: list[dict], top: int) -> None:
    if not partidos:
        print(f"\n== {nombre}: sin partidos")
        return
    cubiertos = 0
    ligas_sin: Counter = Counter()
    equipos_fallan: Counter = Counter()
    for d in partidos:
        ok, _ = mh.validar_historico(d)
        if ok:
            cubiertos += 1
            continue
        ligas_sin[d["liga"]] += 1
        # "Liga cubierta pero equipos no": la liga resuelve a un código del artefacto.
        if mh.ligas_candidatas(d):
            equipos_fallan[(d["liga"], d["local"])] += 1
            equipos_fallan[(d["liga"], d["visitante"])] += 1
    print(f"\n== {nombre}: {cubiertos}/{len(partidos)} cubiertos = {100 * cubiertos / len(partidos):.1f}%")
    print(f"-- ligas con más partidos SIN cobertura (top {top}):")
    for liga, n in ligas_sin.most_common(top):
        print(f"   {n:5d}  {liga}")
    print(f"-- equipos que fallan dentro de ligas con histórico (top {top}; cuenta ambos lados, "
          "incluye al rival que sí resuelve):")
    for (liga, equipo), n in equipos_fallan.most_common(top):
        print(f"   {n:5d}  {equipo}  [{liga}]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--desde", default="2026-09-24", help="fecha mínima de partidos_dia (YYYY-MM-DD)")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    con = _conectar()
    try:
        _medir(f"partidos_dia desde {args.desde}", _partidos_dia(con, args.desde), args.top)
        _medir("analisis_comparativo (todos)", _analisis(con), args.top)
    finally:
        con.close()


if __name__ == "__main__":
    main()
