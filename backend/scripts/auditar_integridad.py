"""auditar_integridad.py — cuenta, en SOLO LECTURA, los registros huérfanos de las relaciones lógicas de la base de datos (no hay claves foráneas declaradas).

  python backend/scripts/auditar_integridad.py            tabla con huérfanos por relación
  python backend/scripts/auditar_integridad.py --estricto  sale con 1 si hay algún huérfano

Por qué no hay claves foráneas: la auditoría del 2026-09-10 (`docs/archive/auditorias/`) encontró relaciones 100 % huérfanas en datos de prueba y un `match_id` que no es único por sí solo
en `partidos_dia`; añadirlas exige antes decidir qué hacer con esos datos. Este script mide la deuda sin tocar nada (abre SQLite con `mode=ro`). Solo SQLite.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# (tabla hija, columna hija, tabla padre, columna padre)
RELACIONES = (
    ("jobs", "device_id_app", "usuarios", "device_id"),
    ("jobs", "match_id", "partidos_dia", "match_id"),
    ("analisis_comparativo", "partido_id", "partidos_dia", "match_id"),
    ("uso_diario_app", "device_id", "usuarios", "device_id"),
    ("agent_messages", "session_id", "agent_sessions", "id"),
    ("agent_runs", "session_id", "agent_sessions", "id"),
)


def _columnas(conexion: sqlite3.Connection, tabla: str) -> set[str]:
    return {fila[1] for fila in conexion.execute(f'pragma table_info("{tabla}")')}


def auditar(ruta: Path) -> list[dict]:
    """Una fila por relación: hijos con valor, huérfanos y porcentaje. Una relación cuya tabla o columna no existe se omite."""
    conexion = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    try:
        filas = []
        for hija, col_h, padre, col_p in RELACIONES:
            if col_h not in _columnas(conexion, hija) or col_p not in _columnas(conexion, padre):
                continue
            con_valor = f'"{col_h}" is not null and "{col_h}" != \'\''
            total = conexion.execute(f'select count(*) from "{hija}" where {con_valor}').fetchone()[0]
            huerfanos = conexion.execute(
                f'select count(*) from "{hija}" h where h."{col_h}" is not null and h."{col_h}" != \'\' '
                f'and not exists (select 1 from "{padre}" p where p."{col_p}" = h."{col_h}")'
            ).fetchone()[0]
            filas.append({"relacion": f"{hija}.{col_h} → {padre}.{col_p}", "con_valor": total, "huerfanos": huerfanos,
                          "porcentaje": round(100 * huerfanos / total, 1) if total else 0.0})
        return filas
    finally:
        conexion.close()


def resumen(filas: list[dict]) -> str:
    con = [f for f in filas if f["huerfanos"]]
    if not con:
        return f"{len(filas)} relaciones lógicas sin huérfanos"
    return "huérfanos en " + "; ".join(f"{f['relacion']}: {f['huerfanos']}/{f['con_valor']}" for f in con[:3]) + (" …" if len(con) > 3 else "")


def _ruta_de_la_base() -> Path | None:
    from backend.api.core.config import settings

    if not settings.is_sqlite:
        return None
    return Path(settings.DATABASE_URL.replace("sqlite:///", ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--estricto", action="store_true", help="sale con 1 si hay algún huérfano")
    ap.add_argument("--db", type=Path, default=None, help="ruta de la base SQLite (por defecto, la de DATABASE_URL)")
    args = ap.parse_args()
    ruta = args.db or _ruta_de_la_base()
    if ruta is None or not ruta.exists():
        print("No hay una base SQLite que auditar (¿Postgres o sin crear?).")
        return 0
    filas = auditar(ruta)
    print(f"{'Relación':58s} {'Con valor':>10s} {'Huérfanos':>10s} {'%':>6s}")
    for f in filas:
        print(f"{f['relacion']:58s} {f['con_valor']:10d} {f['huerfanos']:10d} {f['porcentaje']:6.1f}")
    print(resumen(filas))
    return 1 if args.estricto and any(f["huerfanos"] for f in filas) else 0


if __name__ == "__main__":
    sys.exit(main())
