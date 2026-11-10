"""install/actualizar_pines.py — verifica (y opcionalmente actualiza) install/runtime-pins.json contra las fuentes OFICIALES.

  python install/actualizar_pines.py              verifica que cada huella fijada coincida con la que publica la fuente (no modifica nada)
  python install/actualizar_pines.py --escribir   sube uv a su última versión y Node a la última de su línea actual, y reescribe los pines

Fuentes: uv → API de releases de astral-sh/uv (campo `digest`); Node → SHASUMS256.txt de nodejs.org/dist/v<versión>/.
Solo librería estándar. Sale con código 1 si algo no coincide.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PINES = Path(__file__).resolve().parent / "runtime-pins.json"
API_UV = "https://api.github.com/repos/astral-sh/uv/releases/{ref}"
SHASUMS_NODE = "https://nodejs.org/dist/v{version}/SHASUMS256.txt"
INDICE_NODE = "https://nodejs.org/dist/index.json"


def _leer(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": "laplace-instalador"})
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:  # noqa: S310 — URLs fijas de fuentes oficiales
        return respuesta.read()


def huellas_uv(version: str | None) -> tuple[str, dict[str, str]]:
    datos = json.loads(_leer(API_UV.format(ref="latest" if version is None else f"tags/{version}")))
    return datos["tag_name"], {a["name"]: a["digest"].removeprefix("sha256:") for a in datos["assets"] if a.get("digest")}


def huellas_node(version: str) -> dict[str, str]:
    texto = _leer(SHASUMS_NODE.format(version=version)).decode("utf-8")
    return {linea.split()[1]: linea.split()[0] for linea in texto.splitlines() if len(linea.split()) == 2}


def ultima_de_la_linea(linea_mayor: str) -> str:
    versiones = [v["version"].lstrip("v") for v in json.loads(_leer(INDICE_NODE)) if v["version"].startswith(f"v{linea_mayor}.")]
    return max(versiones, key=lambda v: tuple(int(x) for x in v.split(".")))


def verificar(pines: dict, escribir: bool) -> int:
    fallos = 0
    if escribir:
        version_uv, oficiales_uv = huellas_uv(None)
        pines["uv"]["version"] = version_uv
        version_node = ultima_de_la_linea(pines["node"]["version"].split(".")[0])
        pines["node"]["version"] = version_node
    else:
        version_uv, oficiales_uv = huellas_uv(pines["uv"]["version"])
        version_node = pines["node"]["version"]
    oficiales_node = huellas_node(version_node)
    for nombre, oficiales, version in (("uv", oficiales_uv, version_uv), ("node", oficiales_node, version_node)):
        for plataforma, datos in pines[nombre]["archivos"].items():
            if escribir:
                datos["archivo"] = re.sub(r"v?\d+\.\d+\.\d+", lambda m: ("v" if m.group(0).startswith("v") else "") + version, datos["archivo"], count=1)
            esperado = oficiales.get(datos["archivo"])
            if esperado is None:
                print(f"FALTA   {nombre} {plataforma}: {datos['archivo']} no figura en la fuente oficial")
                fallos += 1
            elif escribir:
                datos["sha256"] = esperado
                print(f"ESCRITO {nombre} {plataforma}: {datos['archivo']}")
            elif esperado != datos["sha256"]:
                print(f"DISTINTA {nombre} {plataforma}: fijada {datos['sha256']} / oficial {esperado}")
                fallos += 1
            else:
                print(f"OK      {nombre} {plataforma}: {datos['archivo']}")
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--escribir", action="store_true", help="actualiza los pines a las últimas versiones oficiales")
    args = ap.parse_args()
    pines = json.loads(PINES.read_text(encoding="utf-8"))
    fallos = verificar(pines, args.escribir)
    if args.escribir and not fallos:
        PINES.write_text(json.dumps(pines, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("runtime-pins.json actualizado")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
