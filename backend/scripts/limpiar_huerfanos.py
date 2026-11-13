"""limpiar_huerfanos.py — retira de la base SQLite los datos de prueba y las filas corruptas conocidas, con respaldo previo y un archivo de lo retirado.

  python backend/scripts/limpiar_huerfanos.py            muestra qué retiraría (no escribe nada)
  python backend/scripts/limpiar_huerfanos.py --aplicar   respalda la base, archiva las filas en un .jsonl, las borra y verifica

Qué retira (solo esto, nada más; ver `AUDITORIA_FOREIGN_KEYS_2026-09.md` y `auditar_integridad.py`):
  1. `jobs` y `uso_diario_app` de los dispositivos de prueba (`DISPOSITIVOS_DE_PRUEBA`): datos de un script de verificación, no de usuarios.
  2. `partidos_dia` con una fecha que no es ni AAAA-MM-DD ni AAAAMMDD (p. ej. `2026--0-9-`): filas basura de un error ya corregido (la entrada se valida desde 2026-10-06).
NO retira los `jobs` cuyo partido ya no está en `partidos_dia`: esa tabla se purga a los 90 días, así que no es corrupción sino retención.

Seguridad (`.claude/rules/database-safety.md`): solo SQLite; sin `--aplicar` no escribe; con `--aplicar` hace primero una copia con la API de respaldo de SQLite (válida con WAL), la verifica
(`integrity_check` y SHA-256) y deja las filas retiradas en `backups/laplace/limpieza_<fecha>.jsonl`; es idempotente (una segunda corrida no encuentra nada).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DISPOSITIVOS_DE_PRUEBA = ("verificacion-real",)
FECHA_VALIDA = "(fecha glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' or fecha glob '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')"


def _consultas() -> list[tuple[str, str, str, tuple]]:
    """(etiqueta, tabla, condición SQL, parámetros) de cada grupo a retirar."""
    marcas = ",".join("?" for _ in DISPOSITIVOS_DE_PRUEBA)
    return [
        ("jobs de dispositivos de prueba", "jobs", f"device_id_app in ({marcas})", DISPOSITIVOS_DE_PRUEBA),
        ("uso diario de dispositivos de prueba", "uso_diario_app", f"device_id in ({marcas})", DISPOSITIVOS_DE_PRUEBA),
        ("partidos con fecha basura", "partidos_dia", f"not {FECHA_VALIDA}", ()),
    ]


def contar(conexion: sqlite3.Connection) -> list[dict]:
    resultado = []
    for etiqueta, tabla, condicion, params in _consultas():
        existe = conexion.execute("select 1 from sqlite_master where type='table' and name=?", (tabla,)).fetchone()
        n = conexion.execute(f'select count(*) from "{tabla}" where {condicion}', params).fetchone()[0] if existe else 0
        resultado.append({"grupo": etiqueta, "tabla": tabla, "filas": n})
    return resultado


def respaldar(ruta_db: Path, carpeta: Path, sello: str) -> tuple[Path, str]:
    """Copia consistente con la API de respaldo de SQLite (sirve con WAL) y la verifica."""
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"bot_deportivo_antes_de_limpieza_{sello}.db"
    origen = sqlite3.connect(f"file:{ruta_db.as_posix()}?mode=ro", uri=True)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
        estado = copia.execute("pragma integrity_check").fetchone()[0]
    finally:
        copia.close()
        origen.close()
    if estado != "ok":
        raise RuntimeError(f"el respaldo no pasó integrity_check: {estado}")
    return destino, hashlib.sha256(destino.read_bytes()).hexdigest()


def aplicar(ruta_db: Path, carpeta: Path, ahora: datetime | None = None) -> dict:
    sello = (ahora or datetime.now()).strftime("%Y%m%d_%H%M%S")
    respaldo, sha = respaldar(ruta_db, carpeta, sello)
    archivo = carpeta / f"limpieza_{sello}.jsonl"
    conexion = sqlite3.connect(ruta_db, timeout=30)
    conexion.row_factory = sqlite3.Row
    retiradas: dict[str, int] = {}
    try:
        with archivo.open("w", encoding="utf-8") as f:
            for etiqueta, tabla, condicion, params in _consultas():
                if not conexion.execute("select 1 from sqlite_master where type='table' and name=?", (tabla,)).fetchone():
                    continue
                filas = conexion.execute(f'select * from "{tabla}" where {condicion}', params).fetchall()
                for fila in filas:
                    f.write(json.dumps({"tabla": tabla, "motivo": etiqueta, "fila": dict(fila)}, ensure_ascii=False, default=str) + "\n")
                retiradas[tabla] = retiradas.get(tabla, 0) + len(filas)
        with conexion:  # una sola transacción: o se borra todo o nada
            for etiqueta, tabla, condicion, params in _consultas():
                if conexion.execute("select 1 from sqlite_master where type='table' and name=?", (tabla,)).fetchone():
                    conexion.execute(f'delete from "{tabla}" where {condicion}', params)
        quedan = sum(g["filas"] for g in contar(conexion))
    finally:
        conexion.close()
    return {"respaldo": str(respaldo), "sha256": sha, "archivo": str(archivo), "retiradas": retiradas, "quedan": quedan}


def _ruta_de_la_base() -> Path | None:
    from backend.api.core.config import settings

    return Path(settings.DATABASE_URL.replace("sqlite:///", "")) if settings.is_sqlite else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="respalda, archiva y borra (sin esto, solo informa)")
    ap.add_argument("--db", type=Path, default=None, help="ruta de la base SQLite (por defecto, la de DATABASE_URL)")
    ap.add_argument("--carpeta", type=Path, default=RAIZ / "backups" / "laplace", help="dónde dejar el respaldo y el archivo de lo retirado")
    args = ap.parse_args()
    ruta = args.db or _ruta_de_la_base()
    if ruta is None or not Path(ruta).exists():
        print("No hay una base SQLite que limpiar (¿Postgres o sin crear?). No se hizo nada.")
        return 0
    conexion = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    try:
        grupos = contar(conexion)
    finally:
        conexion.close()
    total = sum(g["filas"] for g in grupos)
    for g in grupos:
        print(f"  {g['grupo']:40s} {g['filas']:6d} filas en {g['tabla']}")
    if total == 0:
        print("Nada que retirar.")
        return 0
    if not args.aplicar:
        print(f"Se retirarían {total} filas. Es una simulación: usa --aplicar para respaldar y borrar (idempotente).")
        return 0
    r = aplicar(Path(ruta), args.carpeta)
    print(f"Respaldo: {r['respaldo']} (sha256 {r['sha256'][:16]}…)\nArchivo de lo retirado: {r['archivo']}\nRetiradas: {r['retiradas']} · quedan {r['quedan']}")
    return 0 if r["quedan"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
