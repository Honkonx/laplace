"""construir_go.py — compila los programas en Go: el núcleo Monte Carlo de respaldo (`modelo/go/lsim`) y el microservicio del simulador (`modelo/go/simd`) a `modelo/go/bin/`.

  python backend/scripts/construir_go.py [--probar]

Necesita Go (https://go.dev/dl/). Sin el binario, el simulador sigue funcionando en Python (más lento). `--probar` corre `go test` antes de compilar.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
EXT = ".exe" if sys.platform == "win32" else ""
PROGRAMAS = (("lsim", "núcleo Monte Carlo de respaldo"), ("simd", "microservicio del simulador"))
BIN = RAIZ / "modelo" / "go" / "bin"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probar", action="store_true", help="correr go test antes de compilar")
    args = ap.parse_args()
    go = shutil.which("go") or str(Path("C:/Program Files/Go/bin/go.exe"))
    if not Path(go).exists() and not shutil.which("go"):
        print("No encuentro Go. Instálalo desde https://go.dev/dl/ o usa el simulador en Python (más lento).")
        return 1
    BIN.mkdir(parents=True, exist_ok=True)
    for nombre, para_que in PROGRAMAS:
        fuente = RAIZ / "modelo" / "go" / nombre
        if args.probar and subprocess.run([go, "test", "./..."], cwd=fuente, check=False).returncode != 0:  # noqa: S603
            return 1
        r = subprocess.run([go, "build", "-o", str(BIN / f"{nombre}{EXT}"), "."], cwd=fuente, check=False)  # noqa: S603
        print(f"compilado ({para_que}): {BIN / (nombre + EXT)}" if r.returncode == 0 else f"falló la compilación de {nombre}")
        if r.returncode != 0:
            return r.returncode
    return 0

if __name__ == "__main__":
    sys.exit(main())
