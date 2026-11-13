"""Pone el país y el identificador correcto a los partidos que se guardaron antes de que existiera `liga_pais` (ver `services/ligas_ident.py`).

  python backend/scripts/reclasificar_partidos_dia.py                    # SOLO INFORMA: cuántas filas se pueden clasificar y cuántas no (no escribe nada)
  python backend/scripts/reclasificar_partidos_dia.py --aplicar          # escribe; hace una copia de la base antes y pide confirmar si la base no es la local de siempre

Cómo decide: una fila se clasifica solo si el modelo histórico resuelve la liga y AMBOS equipos (así el país sale de la liga real, no del nombre); el resto queda sin país (es lo que no se puede
saber sin inventar). Es idempotente: una fila con país no se toca; correrlo dos veces no cambia nada la segunda. Afecta solo `partidos_dia` (columnas `liga_pais` y `liga_slug`).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.services import ligas_ident, modelo_historico  # noqa: E402

DB_LOCAL = RAIZ / "backend" / "db" / "bot_deportivo.db"


def paises_por_codigo() -> dict[str, str]:
    """{código de liga del histórico: país} leído del maestro (columnas `liga_codigo` y `pais`)."""
    salida: dict[str, str] = {}
    with gzip.open(datos.localizar_archivo(), "rt", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            salida.setdefault(fila["liga_codigo"], fila["pais"])
    return salida


def clasificar(con: sqlite3.Connection, paises: dict[str, str]) -> tuple[list[tuple[str, str, str, str]], Counter]:
    """([(fecha, match_id, país, slug nuevo)], conteo por motivo) para las filas sin país."""
    cambios: list[tuple[str, str, str, str]] = []
    motivos: Counter = Counter()
    for fecha, match_id, nombre, local, visitante in con.execute("SELECT fecha, match_id, liga_nombre, local, visitante FROM partidos_dia WHERE liga_pais IS NULL OR liga_pais = ''"):
        r = modelo_historico._resolver({"liga": nombre or "", "local": local or "", "visitante": visitante or ""})  # noqa: SLF001
        if not r or not r[0]:
            motivos["sin_resolver"] += 1
            continue
        pais = paises.get(r[0], "")
        if not pais:
            motivos["liga_sin_pais"] += 1
            continue
        cambios.append((fecha, match_id, pais, ligas_ident.slug_competicion(nombre, pais)))
        motivos["clasificada"] += 1
    return cambios, motivos


def recalcular_identificadores(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """[(fecha, match_id, slug esperado)] de las filas que YA tienen país pero cuyo identificador no sigue la regla vigente (p. ej. guardadas antes de que los nombres largos llevaran hash)."""
    salida = []
    for fecha, match_id, nombre, pais, slug in con.execute("SELECT fecha, match_id, liga_nombre, liga_pais, liga_slug FROM partidos_dia WHERE liga_pais IS NOT NULL AND liga_pais != ''"):
        esperado = ligas_ident.slug_competicion(nombre, pais)
        if slug != esperado:
            salida.append((fecha, match_id, esperado))
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB_LOCAL))
    ap.add_argument("--aplicar", action="store_true", help="escribe los cambios (por defecto solo informa)")
    ap.add_argument("--si", action="store_true", help="confirma sin preguntar cuando la base no es la local de siempre")
    a = ap.parse_args()
    ruta = Path(a.db)
    if not ruta.is_file():
        print(f"no existe la base: {ruta}")
        return 2
    con = sqlite3.connect(f"file:{ruta}?mode=ro" if not a.aplicar else str(ruta), uri=not a.aplicar)
    if "liga_pais" not in {fila[1] for fila in con.execute("PRAGMA table_info(partidos_dia)")}:
        print("La base aún no tiene la columna liga_pais: se agrega sola al arrancar el backend (migración fa2c4e6a8b0d). Arráncalo y vuelve a correr esto.")
        return 3
    total = con.execute("SELECT COUNT(*) FROM partidos_dia").fetchone()[0]
    cambios, motivos = clasificar(con, paises_por_codigo())
    recalculos = recalcular_identificadores(con)
    print(f"partidos guardados: {total} | sin país: {sum(motivos.values())} | se pueden clasificar: {motivos['clasificada']} | sin resolver: {motivos['sin_resolver']} | liga sin país: {motivos['liga_sin_pais']} | identificadores a recalcular: {len(recalculos)}")
    if not a.aplicar:
        print("(solo informe: con --aplicar se escribe; antes se hace una copia de la base)")
        return 0
    if ruta.resolve() != DB_LOCAL.resolve() and not a.si:
        if input(f"La base {ruta} no es la local de siempre. ¿Aplicar de todos modos? [s/N] ").strip().lower() not in ("s", "si", "sí"):
            print("cancelado")
            return 1
    copia = ruta.with_name(ruta.stem + ".antes_de_reclasificar" + ruta.suffix)
    shutil.copy2(ruta, copia)
    print(f"copia de seguridad: {copia}")
    with con:
        con.executemany("UPDATE partidos_dia SET liga_pais = ?, liga_slug = ? WHERE fecha = ? AND match_id = ? AND (liga_pais IS NULL OR liga_pais = '')", [(p, s, f, m) for f, m, p, s in cambios])
        con.executemany("UPDATE partidos_dia SET liga_slug = ? WHERE fecha = ? AND match_id = ? AND liga_pais IS NOT NULL AND liga_pais != ''", [(s, f, m) for f, m, s in recalculos])
    print(f"filas clasificadas: {len(cambios)} | identificadores recalculados: {len(recalculos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
