"""ml/datos.py — carga el histórico normalizado (`backend/data/datos/football-data/`).

Solo librería estándar (mismo criterio que `ml/dixon_coles.py::probabilidades`): leer datos no
debe exigir pandas. Devuelve dicts simples ordenados por fecha; cada partido lleva su `dia`
ordinal (`date.toordinal()`) para que el ajuste compare fechas sin parsear texto en el bucle.
"""
from __future__ import annotations

import csv
import gzip
import io
from datetime import date
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
RUTA_DATOS = RAIZ_REPO / "backend" / "data" / "datos" / "football-data"
RUTA_VIVO = RAIZ_REPO / "backend" / "data" / "datos" / "vivo" / "resultados_vivos.csv.gz"

_CAMPOS_CUOTA = (
    "ap_b365", "ap_pinnacle", "ap_max", "ap_prom", "ci_b365", "ci_pinnacle", "ci_max", "ci_prom",
)


def _abrir(ruta: Path) -> io.TextIOBase:
    if ruta.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(ruta, "rb"), encoding="utf-8", newline="")
    return open(ruta, encoding="utf-8", newline="")


RUTA_ACTUAL = RAIZ_REPO / "backend" / "data" / "datos" / "actual" / "resultados_actuales.csv.gz"  # temporada en curso desde football-data.co.uk (el script de actualización de resultados actuales, que no se publica)


def _numero(texto: str | None) -> float | None:
    if texto is None or texto == "":
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _mas_menos(fila: dict, mas: str, menos: str) -> tuple[float, float] | None:
    """Cuotas (más, menos) de la línea de 2,5 goles, o None si faltan o no son válidas."""
    o, u = _numero(fila.get(mas)), _numero(fila.get(menos))
    return (o, u) if o is not None and u is not None and min(o, u) > 1.0 else None


def _cuotas(fila: dict, prefijo: str) -> tuple[float, float, float] | None:
    h, d, a = (_numero(fila.get(f"{prefijo}_{s}")) for s in "hda")
    if h is None or d is None or a is None or min(h, d, a) <= 1.0:
        return None
    return h, d, a


def localizar_archivo(base: Path = RUTA_DATOS) -> Path:
    for nombre in ("partidos.csv", "partidos.csv.gz"):
        if (base / nombre).exists():
            return base / nombre
    raise FileNotFoundError(f"No hay partidos.csv[.gz] en {base} — correr normalizar_football_data.py")


def cargar_partidos(ruta: Path | None = None) -> list[dict]:
    """Partidos con resultado, ordenados por fecha. Descarta filas sin marcador o sin fecha."""
    partidos: list[dict] = []
    with _abrir(ruta or localizar_archivo()) as f:
        for fila in csv.DictReader(f):
            gl, gv = _numero(fila.get("goles_local")), _numero(fila.get("goles_visitante"))
            try:
                fecha = date.fromisoformat(fila.get("fecha", ""))
            except ValueError:
                continue
            if gl is None or gv is None:
                continue
            local = fila.get("local_canon") or fila["local"]
            visitante = fila.get("visitante_canon") or fila["visitante"]
            p = {
                "liga": fila["liga_codigo"], "liga_nombre": fila["liga_nombre"],
                "temporada": fila["temporada"], "fecha": fecha, "dia": fecha.toordinal(),
                "local": local, "visitante": visitante,
                "gl": int(gl), "gv": int(gv),
                "resultado": "H" if gl > gv else "A" if gv > gl else "D",
                # estadísticas de partido (44 % de las filas): tiros y tiros a puerta; None si no vienen (el plan de mejoras (repo de trabajo), `registro_experimentos.md`)
                "tl": _numero(fila.get("tiros_local")), "tv": _numero(fila.get("tiros_visit")),
                "al": _numero(fila.get("tiros_arco_local")), "av": _numero(fila.get("tiros_arco_visit")),
            }
            for campo in _CAMPOS_CUOTA:
                p[campo] = _cuotas(fila, campo)
            p["o25"] = _mas_menos(fila, "over25_prom", "under25_prom")  # más/menos 2,5 promedio de apertura y de cierre (MP-11); nadie del motor las usa
            p["o25_cierre"] = _mas_menos(fila, "over25_prom_cierre", "under25_prom_cierre")
            partidos.append(p)
    partidos.sort(key=lambda p: (p["dia"], p["liga"], p["local"]))
    return partidos


def agrupar_por_liga(partidos: list[dict]) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {}
    for p in partidos:
        salida.setdefault(p["liga"], []).append(p)
    return salida


def cargar_partidos_con_vivo(
    ruta_maestro: Path | None = None, ruta_vivo: Path | None = None,
) -> tuple[list[dict], dict]:
    """Maestro + capa en vivo (`ml/vivo.py`), sin duplicar partidos ya presentes en el maestro.

    Clave de duplicado: fecha + local + visitante (nombres canónicos), con ±1 día de tolerancia (la
    fecha UTC de una fuente y la local de otra difieren). El maestro manda: una fila en vivo que ya
    está en él se descarta. Devuelve (partidos ordenados, info) con `vivos_nuevos` por liga."""
    partidos = cargar_partidos(ruta_maestro)
    ruta = ruta_vivo if ruta_vivo is not None else RUTA_VIVO
    info: dict = {"maestro": len(partidos), "vivos_leidos": 0, "vivos_duplicados": 0, "vivos_nuevos": {}, "vivos_todos": [], "actuales_nuevos": 0}
    vistos = {(p["dia"], p["local"], p["visitante"]) for p in partidos}
    nuevos = []
    # capa «actual» (temporada en curso de football-data.co.uk): manda sobre la del bot, que solo tiene lo que el bot alcanzó a ver; solo si se usan las rutas por defecto
    if ruta_maestro is None and ruta_vivo is None and RUTA_ACTUAL.exists():
        for p in cargar_partidos(RUTA_ACTUAL):
            if any((p["dia"] + d, p["local"], p["visitante"]) in vistos for d in (0, -1, 1)):
                continue
            vistos.add((p["dia"], p["local"], p["visitante"]))
            nuevos.append({**p, "vivo": True, "actual": True})
            info["actuales_nuevos"] += 1
    if not ruta.exists():
        partidos.extend(nuevos)
        partidos.sort(key=lambda p: (p["dia"], p["liga"], p["local"]))
        return partidos, info
    for p in cargar_partidos(ruta):
        info["vivos_leidos"] += 1
        info["vivos_todos"].append(p)  # todos los verificados, también los que el maestro ya trae
        if any((p["dia"] + d, p["local"], p["visitante"]) in vistos for d in (0, -1, 1)):
            info["vivos_duplicados"] += 1
            continue
        vistos.add((p["dia"], p["local"], p["visitante"]))
        nuevos.append({**p, "vivo": True})
        info["vivos_nuevos"][p["liga"]] = info["vivos_nuevos"].get(p["liga"], 0) + 1
    partidos.extend(nuevos)
    partidos.sort(key=lambda p: (p["dia"], p["liga"], p["local"]))
    return partidos, info
