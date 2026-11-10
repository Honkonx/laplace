"""reparar_fechas_partidos_dia.py — Diagnóstico y reparación SEGURA de claves `fecha` inválidas
en `partidos_dia` (ej. `2026--0-9-`, hallazgo de la auditoría 2026-10-06: 631 de 5.447 filas).

Origen (verificado en código): `gateway._yyyymmdd_to_bd` parte el texto en [:4]/[4:6]/[6:8]; si le
llega `2026-09-27` produce `2026--0-9-` (se pierde el día). Desde esta ronda `partidos_repo`
rechaza esas claves; este script ocupa de las filas ya guardadas.

Uso (reglas de `.claude/rules/database-safety.md`):

    python backend/scripts/reparar_fechas_partidos_dia.py                 # --dry-run (defecto): solo reporta
    python backend/scripts/reparar_fechas_partidos_dia.py --aplicar --confirmo

- Por defecto abre la BD en SOLO LECTURA (`mode=ro`) y no escribe nada.
- `--aplicar` exige además `--confirmo`; sin ambos aborta. Nunca ejecuta DELETE.
- Clasifica cada fila inválida:
    * `reparable_por_kickoff`  — `kick_off_utc` válido: la fecha real (día en Chile) se deriva de ahí
                                 y la fila se re-clavea (solo si no pisa otra fila existente).
    * `duplicado_de_fila_valida` — el mismo `match_id` ya existe con fecha válida: la fila basura es
                                 un duplicado; se pone `cache_invalidado=1` (cuarentena, queda en la tabla).
    * `irreparable`          — no hay de dónde derivar la fecha: se pone `cache_invalidado=1` y se reporta.
- Idempotente: re-ejecutarlo no vuelve a tocar filas ya reparadas ni ya en cuarentena.
- Cuántas filas afecta: lo informa el reporte (dry-run) antes de cualquier cambio.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RUTA_BD_DEFECTO = Path(__file__).resolve().parents[1] / "db" / "bot_deportivo.db"
TZ_CHILE = ZoneInfo("America/Santiago")
_RE_FECHA_VALIDA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _es_fecha_valida(fecha: str | None) -> bool:
    if not fecha or not _RE_FECHA_VALIDA.match(fecha):
        return False
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def fecha_chile_desde_kickoff(kick_off_utc: str | None) -> str | None:
    """Día calendario en Chile de un `kick_off_utc` (`YYYY-MM-DDTHH:MM:SS[Z]`), o None si no parsea."""
    if not kick_off_utc:
        return None
    try:
        momento = datetime.strptime(kick_off_utc[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return momento.replace(tzinfo=timezone.utc).astimezone(TZ_CHILE).strftime("%Y-%m-%d")


def clasificar_filas(conn: sqlite3.Connection) -> list[dict]:
    """Lista de filas con `fecha` inválida y qué se puede hacer con cada una (solo lectura)."""
    filas = conn.execute(
        "SELECT fecha, match_id, local, visitante, kick_off_utc, cache_invalidado FROM partidos_dia"
    ).fetchall()
    validas = {(f, m) for f, m, *_ in filas if _es_fecha_valida(f)}
    match_ids_validos = {m for _, m in validas}
    resultado: list[dict] = []
    for fecha, match_id, local, visitante, kick_off_utc, invalidado in filas:
        if _es_fecha_valida(fecha):
            continue
        fecha_derivada = fecha_chile_desde_kickoff(kick_off_utc)
        if fecha_derivada and (fecha_derivada, match_id) not in validas:
            clase, destino = "reparable_por_kickoff", fecha_derivada
        elif match_id in match_ids_validos or (fecha_derivada and (fecha_derivada, match_id) in validas):
            clase, destino = "duplicado_de_fila_valida", None
        else:
            clase, destino = "irreparable", None
        resultado.append({
            "fecha": fecha, "match_id": match_id, "local": local, "visitante": visitante,
            "clase": clase, "fecha_destino": destino, "ya_en_cuarentena": bool(invalidado),
        })
    return resultado


def resumir(clasificadas: list[dict]) -> dict:
    por_clase: dict[str, int] = {}
    por_fecha: dict[str, int] = {}
    for fila in clasificadas:
        por_clase[fila["clase"]] = por_clase.get(fila["clase"], 0) + 1
        por_fecha[fila["fecha"]] = por_fecha.get(fila["fecha"], 0) + 1
    pendientes = sum(
        1 for f in clasificadas if f["clase"] == "reparable_por_kickoff" or not f["ya_en_cuarentena"]
    )
    return {
        "filas_invalidas": len(clasificadas), "por_clase": por_clase, "claves_invalidas": por_fecha,
        "filas_que_cambiaria_aplicar": pendientes,
    }


def aplicar(conn: sqlite3.Connection, clasificadas: list[dict]) -> dict:
    """Re-clavea las reparables y pone en cuarentena (`cache_invalidado=1`) el resto. Sin DELETE."""
    reclaveadas = cuarentena = 0
    with conn:
        for fila in clasificadas:
            if fila["clase"] == "reparable_por_kickoff":
                cur = conn.execute(
                    "UPDATE partidos_dia SET fecha=?, cache_invalidado=0 WHERE fecha=? AND match_id=?",
                    (fila["fecha_destino"], fila["fecha"], fila["match_id"]),
                )
                reclaveadas += cur.rowcount
            elif not fila["ya_en_cuarentena"]:
                cur = conn.execute(
                    "UPDATE partidos_dia SET cache_invalidado=1 WHERE fecha=? AND match_id=?",
                    (fila["fecha"], fila["match_id"]),
                )
                cuarentena += cur.rowcount
    return {"reclaveadas": reclaveadas, "puestas_en_cuarentena": cuarentena}


def _abrir(ruta: Path, escritura: bool) -> sqlite3.Connection:
    if not ruta.exists():
        raise SystemExit(f"No existe la BD: {ruta}")
    uri = f"file:{ruta.as_posix()}?mode={'rw' if escritura else 'ro'}"
    return sqlite3.connect(uri, uri=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=RUTA_BD_DEFECTO, help="ruta de la BD SQLite")
    parser.add_argument("--aplicar", action="store_true", help="escribe los cambios (exige --confirmo)")
    parser.add_argument("--confirmo", action="store_true", help="confirmación explícita para --aplicar")
    parser.add_argument("--detalle", action="store_true", help="lista cada fila inválida en el reporte")
    args = parser.parse_args(argv)

    if args.aplicar and not args.confirmo:
        print("ABORTADO: --aplicar exige --confirmo (modifica la BD; nunca borra filas).", file=sys.stderr)
        return 2

    conn = _abrir(args.db, escritura=args.aplicar)
    try:
        clasificadas = clasificar_filas(conn)
        reporte = {"modo": "aplicar" if args.aplicar else "dry-run", "bd": str(args.db), **resumir(clasificadas)}
        if args.detalle:
            reporte["detalle"] = clasificadas
        if args.aplicar:
            reporte["resultado"] = aplicar(conn, clasificadas)
        print(json.dumps(reporte, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
