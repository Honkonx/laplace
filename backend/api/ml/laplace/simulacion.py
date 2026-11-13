"""simulacion.py — motor de simulaciones: mundos con verdad conocida (manual o masivo), exportación e importador con procedencia.

Toda fila lleva `procedencia` (`real`, `sintetico`). Una simulación es reproducible: misma semilla y parámetros → mismos partidos.
Lo sintético sirve para probar y calibrar el método; la evaluación final es siempre con partidos reales no vistos.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from backend.api.ml import sintetico
from backend.api.ml.laplace import VERSION_GENERADOR

PROCEDENCIAS_VALIDAS = ("real", "sintetico")
COLUMNAS = ("fecha", "liga", "local", "visitante", "gl", "gv")
COLUMNAS_OPCIONALES = ("cuota_local", "cuota_empate", "cuota_visitante")
MAX_FILAS_IMPORTAR = 500_000
PARAMETROS_POR_DEFECTO = {"n_equipos": 16, "temporadas": 3, "sd_fuerza": 0.30, "mu": 0.15, "gamma": 0.28}


class ErrorImportacion(ValueError):
    pass


def simular(semilla: int, **parametros) -> dict:
    """Modo manual: una liga y varias temporadas consecutivas. Devuelve `{parametros, semilla, partidos}`."""
    p = {**PARAMETROS_POR_DEFECTO, **parametros}
    if p["n_equipos"] < 4 or p["temporadas"] < 1:
        raise ValueError("se necesitan al menos 4 equipos y 1 temporada")
    liga = sintetico.generar_liga(semilla, p["n_equipos"], p["sd_fuerza"], p["mu"], p["gamma"], codigo=f"SIM{semilla}", nombre=f"Sim {semilla}")
    inicio, partidos = date(2020, 8, 1), []
    for t in range(p["temporadas"]):
        partidos += sintetico.simular_temporada(liga, inicio, semilla * 1000 + t, f"S{t + 1}")
        inicio = date(inicio.year + 1, inicio.month, inicio.day)
    for fila in partidos:
        fila["procedencia"] = "sintetico"
    return {"semilla": semilla, "parametros": p, "version_generador": VERSION_GENERADOR, "partidos": partidos}


def simular_masivo(semillas: Iterable[int], rejilla: dict[str, list] | None = None) -> list[dict]:
    """Modo masivo: una simulación por semilla × combinación de la rejilla de parámetros (producto cartesiano, orden estable)."""
    combos: list[dict] = [{}]
    for clave, valores in sorted((rejilla or {}).items()):
        combos = [{**c, clave: v} for c in combos for v in valores]
    return [simular(s, **c) for s in semillas for c in combos]


def huella(partidos: list[dict]) -> str:
    h = hashlib.sha256()
    for p in partidos:
        h.update(f"{p['fecha']}|{p['local']}|{p['visitante']}|{p['gl']}|{p['gv']}".encode())
    return h.hexdigest()


def exportar_csv(partidos: list[dict], ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([*COLUMNAS, "procedencia"])
        for p in partidos:
            w.writerow([p["fecha"], p["liga"], p["local"], p["visitante"], p["gl"], p["gv"], p.get("procedencia", "sintetico")])
    return ruta


def exportar_json(simulacion: dict, ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    limpio = {**simulacion, "partidos": [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in p.items() if k != "verdad"} | {"verdad": list(p["verdad"])} for p in simulacion["partidos"]]}
    ruta.write_text(json.dumps(limpio, ensure_ascii=False), encoding="utf-8")
    return ruta


def _fila_valida(crudo: dict, procedencia: str, n: int) -> dict:
    falta = [c for c in COLUMNAS if crudo.get(c) in (None, "")]
    if falta:
        raise ErrorImportacion(f"fila {n}: faltan {', '.join(falta)}")
    try:
        f = date.fromisoformat(str(crudo["fecha"]))
        gl, gv = int(crudo["gl"]), int(crudo["gv"])
    except ValueError as e:
        raise ErrorImportacion(f"fila {n}: valor inválido ({e})") from e
    if gl < 0 or gv < 0 or gl > 30 or gv > 30:
        raise ErrorImportacion(f"fila {n}: goles fuera de rango")
    fila = {"fecha": f, "dia": f.toordinal(), "liga": str(crudo["liga"]), "local": str(crudo["local"]).strip(), "visitante": str(crudo["visitante"]).strip(),
            "gl": gl, "gv": gv, "resultado": "H" if gl > gv else "A" if gv > gl else "D", "procedencia": procedencia}
    if fila["local"] == fila["visitante"]:
        raise ErrorImportacion(f"fila {n}: un equipo no juega contra sí mismo")
    cuotas = [crudo.get(c) for c in COLUMNAS_OPCIONALES]
    if all(c not in (None, "") for c in cuotas):
        try:
            fila["cuotas"] = tuple(float(c) for c in cuotas)
        except ValueError as e:
            raise ErrorImportacion(f"fila {n}: cuota inválida") from e
        if min(fila["cuotas"]) <= 1.0:
            raise ErrorImportacion(f"fila {n}: las cuotas deben ser mayores que 1")
    return fila


def importar(ruta: Path, procedencia: str) -> list[dict]:
    """Importa CSV o JSON (`[{fecha, liga, local, visitante, gl, gv}]` o `{partidos: [...]}`). Rechaza el archivo entero si una fila es inválida."""
    if procedencia not in PROCEDENCIAS_VALIDAS:
        raise ErrorImportacion(f"procedencia inválida: {procedencia} (usa real o sintetico)")
    if ruta.suffix.lower() == ".json":
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        crudos = datos["partidos"] if isinstance(datos, dict) else datos
    elif ruta.suffix.lower() == ".csv":
        with open(ruta, encoding="utf-8", newline="") as f:
            crudos = list(csv.DictReader(f))
    else:
        raise ErrorImportacion("formato no soportado (usa .csv o .json)")
    if len(crudos) > MAX_FILAS_IMPORTAR:
        raise ErrorImportacion(f"demasiadas filas ({len(crudos)} > {MAX_FILAS_IMPORTAR})")
    filas = [_fila_valida(c, procedencia, i) for i, c in enumerate(crudos, start=1)]
    return sorted(filas, key=lambda x: x["dia"])
