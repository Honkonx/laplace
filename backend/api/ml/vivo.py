"""ml/vivo.py — capa de resultados en vivo: los marcadores que el propio bot verifica.

Por qué existe (2026-10-07): las ligas hispanohablantes y asiáticas del maestro solo llegan a 2024
(api-football plan free no da 2025+), así que sus ratings tienen ~2 años. El bot ya guarda el
marcador real de todo partido que ve (`resultados_partidos`, `partidos_dia` terminados): son datos
gratuitos y legítimos que cierran ese hueco. Este módulo (solo librería estándar) lee esas tablas
en SOLO LECTURA, descarta lo dudoso con una razón y escribe filas con el esquema canónico del
maestro (`fuente='laplace_vivo'`) que `ml/datos.cargar_partidos_con_vivo` mezcla sin duplicar.

Criterio central: una fila entra solo si la liga y AMBOS equipos se resuelven con certeza contra el
modelo de esa liga (`resolver`, inyectado por el caller: normalmente `services/modelo_historico`).
Ante la duda se descarta y se reporta; nunca se adivina.
"""
from __future__ import annotations

import csv
import gzip
import io
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

from backend.api.ml.datos import RUTA_VIVO  # noqa: F401  (re-exportado: ruta canónica de la capa)

FUENTE_VIVO = "laplace_vivo"
MAX_GOLES_CREIBLE = 20
FECHA_MINIMA = date(2000, 1, 1)

# Mismo orden de columnas que `partidos.csv.gz` (maestro): un lector del maestro lee esta capa tal cual.
CAMPOS = [
    "liga_codigo", "liga_nombre", "pais", "temporada", "fecha", "hora", "local", "visitante",
    "local_canon", "visitante_canon", "goles_local", "goles_visitante", "resultado",
    "tiros_local", "tiros_visit", "tiros_arco_local", "tiros_arco_visit", "corners_local", "corners_visit",
    "amarillas_local", "amarillas_visit", "rojas_local", "rojas_visit", "arbitro",
    "ap_b365_h", "ap_b365_d", "ap_b365_a", "ap_pinnacle_h", "ap_pinnacle_d", "ap_pinnacle_a",
    "ap_max_h", "ap_max_d", "ap_max_a", "ap_prom_h", "ap_prom_d", "ap_prom_a",
    "ci_b365_h", "ci_b365_d", "ci_b365_a", "ci_pinnacle_h", "ci_pinnacle_d", "ci_pinnacle_a",
    "ci_max_h", "ci_max_d", "ci_max_a", "ci_prom_h", "ci_prom_d", "ci_prom_a",
    "over25_prom", "under25_prom", "over25_prom_cierre", "under25_prom_cierre", "fuente",
]

# Estados que significan "terminado en 90 minutos con marcador definitivo". AET/PEN se excluyen: el
# marcador incluye prórroga o penales y no es comparable con el de los 90 minutos del maestro.
ESTADOS_TERMINADOS = {"finished", "ft"}

# (liga_nombre, liga_id, local, visitante) -> (codigo, local_canonico, visitante_canonico) | (None, razon, detalle)
Resolver = Callable[[dict], tuple]


def fecha_valida(texto: object, hoy: date | None = None) -> date | None:
    """`YYYY-MM-DD` estricto (la cuarentena de `partidos_dia` guarda basura tipo '20260909' o '')."""
    if not isinstance(texto, str) or len(texto) != 10 or texto[4] != "-" or texto[7] != "-":
        return None
    try:
        f = date.fromisoformat(texto)
    except ValueError:
        return None
    limite = (hoy or date.today()) + timedelta(days=1)
    return f if FECHA_MINIMA <= f <= limite else None


def _entero(valor: object) -> int | None:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= MAX_GOLES_CREIBLE else None


def leer_crudos_bd(ruta_db: Path) -> list[dict]:
    """Resultados con marcador de `resultados_partidos` y `partidos_dia`, SOLO lectura (`mode=ro`).

    Cada dict: origen, fecha, local, visitante, gl, gv, liga, liga_id, estado, fixture_id. Los de
    `resultados_partidos` (verificados contra la API) heredan `liga`/`liga_id` de `partidos_dia` cuando
    comparten fixture (la tabla de resultados guarda a veces la liga vacía y nunca el id)."""
    uri = f"file:{Path(ruta_db).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        dia = con.execute(
            "SELECT fecha, match_id, apifootball_fixture_id, liga_nombre, liga_codigo, local, visitante,"
            " goles_local, goles_visitante, status FROM partidos_dia"
            " WHERE goles_local IS NOT NULL AND goles_visitante IS NOT NULL").fetchall()
        res = con.execute(
            "SELECT fixture_id, local, visitante, liga, goles_local, goles_visitante, status_api, fecha_partido"
            " FROM resultados_partidos WHERE goles_local IS NOT NULL AND goles_visitante IS NOT NULL").fetchall()
    finally:
        con.close()
    por_fixture: dict[str, sqlite3.Row] = {}
    for r in dia:
        for clave in (r["match_id"], r["apifootball_fixture_id"]):
            if clave:
                por_fixture.setdefault(str(clave), r)
    crudos: list[dict] = []
    for r in res:
        hermano = por_fixture.get(str(r["fixture_id"]))
        liga = r["liga"] or (hermano["liga_nombre"] if hermano else "") or ""
        crudos.append({
            "origen": "resultados_partidos", "fecha": r["fecha_partido"], "local": r["local"], "visitante": r["visitante"],
            "gl": r["goles_local"], "gv": r["goles_visitante"], "liga": liga,
            "liga_id": (hermano["liga_codigo"] if hermano else None) or "",
            "estado": (r["status_api"] or "").lower(), "fixture_id": str(r["fixture_id"] or ""),
        })
    for r in dia:
        crudos.append({
            "origen": "partidos_dia", "fecha": r["fecha"], "local": r["local"], "visitante": r["visitante"],
            "gl": r["goles_local"], "gv": r["goles_visitante"], "liga": r["liga_nombre"] or "",
            "liga_id": r["liga_codigo"] or "", "estado": (r["status"] or "").lower(),
            "fixture_id": str(r["match_id"] or ""),
        })
    return crudos


def _temporada(fecha: date, europea: bool) -> str:
    if not europea:
        return str(fecha.year)
    inicio = fecha.year if fecha.month >= 7 else fecha.year - 1
    return f"{inicio}/{inicio + 1}"


def fila_canonica(crudo: dict, fecha: date, codigo: str, local: str, visitante: str, meta: dict) -> dict:
    """Fila con el esquema del maestro. `meta` = {nombre, pais, europea} de la liga ya resuelta."""
    gl, gv = int(crudo["gl"]), int(crudo["gv"])
    fila = dict.fromkeys(CAMPOS, "")
    fila.update({
        "liga_codigo": codigo, "liga_nombre": meta.get("nombre", ""), "pais": meta.get("pais", ""),
        "temporada": _temporada(fecha, bool(meta.get("europea"))), "fecha": fecha.isoformat(),
        "local": crudo["local"], "visitante": crudo["visitante"], "local_canon": local, "visitante_canon": visitante,
        "goles_local": gl, "goles_visitante": gv, "resultado": "H" if gl > gv else "A" if gv > gl else "D",
        "fuente": FUENTE_VIVO,
    })
    return fila


def clave_partido(fila: dict) -> tuple[str, str, str]:
    return fila["fecha"], fila["local_canon"], fila["visitante_canon"]


def _hay_duplicado(clave: tuple[str, str, str], vistos: dict) -> tuple[str, str, str] | None:
    """Mismo partido el mismo día o ±1 día (la fecha UTC y la local de una fuente pueden diferir)."""
    f, loc, vis = clave
    base = date.fromisoformat(f)
    for delta in (0, -1, 1):
        k = ((base + timedelta(days=delta)).isoformat(), loc, vis)
        if k in vistos:
            return k
    return None


def clasificar(
    crudos: Iterable[dict],
    resolver: Resolver,
    metas: dict[str, dict],
    existentes: Iterable[dict] = (),
    hoy: date | None = None,
) -> tuple[list[dict], list[dict]]:
    """(filas_aceptadas, descartes). `existentes` = filas ya exportadas antes: se conservan siempre
    (el job de purga borra `partidos_dia` viejos; la capa en vivo no puede perder lo ya acumulado).

    Cada descarte: {razon, origen, fecha, local, visitante, liga, detalle}."""
    aceptadas: dict[tuple, dict] = {}
    for fila in existentes:
        aceptadas.setdefault(clave_partido(fila), fila)
    descartes: list[dict] = []

    def descartar(c: dict, razon: str, detalle: str = "") -> None:
        descartes.append({"razon": razon, "origen": c.get("origen"), "fecha": c.get("fecha"), "local": c.get("local"),
                          "visitante": c.get("visitante"), "liga": c.get("liga"), "liga_id": c.get("liga_id"), "detalle": detalle})

    # resultados_partidos primero: está verificado contra la API; partidos_dia es el respaldo.
    for c in sorted(crudos, key=lambda x: 0 if x["origen"] == "resultados_partidos" else 1):
        fecha = fecha_valida(c.get("fecha"), hoy)
        gl, gv = _entero(c.get("gl")), _entero(c.get("gv"))
        if fecha is None:
            descartar(c, "fecha_invalida", str(c.get("fecha")))
        elif gl is None or gv is None:
            descartar(c, "marcador_invalido", f"{c.get('gl')}-{c.get('gv')}")
        elif c.get("estado") not in ESTADOS_TERMINADOS:
            descartar(c, "estado_no_terminado", str(c.get("estado")))
        elif not (c.get("local") or "").strip() or not (c.get("visitante") or "").strip() or c["local"] == c["visitante"]:
            descartar(c, "equipos_invalidos")
        else:
            r = resolver(c)
            if r[0] is None:
                descartar(c, r[1], r[2] if len(r) > 2 else "")
                continue
            codigo, local, visitante = r
            fila = fila_canonica({**c, "gl": gl, "gv": gv}, fecha, codigo, local, visitante, metas.get(codigo, {}))
            previo = _hay_duplicado(clave_partido(fila), aceptadas)
            if previo is None:
                aceptadas[clave_partido(fila)] = fila
            elif (int(aceptadas[previo]["goles_local"]), int(aceptadas[previo]["goles_visitante"])) != (gl, gv):
                descartar(c, "marcador_en_conflicto", f"ya {aceptadas[previo]['goles_local']}-{aceptadas[previo]['goles_visitante']}, ahora {gl}-{gv}")
            else:
                descartar(c, "duplicado")
    filas = sorted(aceptadas.values(), key=lambda f: (f["fecha"], f["liga_codigo"], f["local_canon"], f["visitante_canon"]))
    return filas, descartes


def escribir_csv_gz(filas: list[dict], ruta: Path) -> None:
    """Escritura determinista (mtime=0, orden fijo): misma entrada -> mismos bytes (idempotente).
    Atómica: escribe a un temporal vecino y reemplaza."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=CAMPOS, lineterminator="\n")
    w.writeheader()
    w.writerows(filas)
    tmp = ruta.with_name(ruta.name + ".tmp")
    with open(tmp, "wb") as crudo, gzip.GzipFile(filename="", mode="wb", fileobj=crudo, mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    tmp.replace(ruta)


def leer_csv_gz(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with io.TextIOWrapper(gzip.open(ruta, "rb"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def resumen_por_liga(filas: list[dict], descartes: list[dict]) -> dict:
    """Cifras para el reporte: asignados por liga y descartes por razón (y por liga cuando se conoce)."""
    por_liga = Counter(f["liga_codigo"] for f in filas)
    razones = Counter(d["razon"] for d in descartes if d["razon"] != "duplicado")
    return {
        "filas_totales": len(filas),
        "por_liga": dict(sorted(por_liga.items(), key=lambda kv: -kv[1])),
        "descartes_por_razon": dict(razones),
        "duplicados_ignorados": sum(1 for d in descartes if d["razon"] == "duplicado"),
    }
