"""construir_rust.py — compila el núcleo Monte Carlo en Rust (`modelo/rust/lsim`) a `modelo/rust/bin/lsim[.exe]`.

  python backend/scripts/construir_rust.py [--probar]

Necesita Rust (https://rustup.rs). Busca `cargo` en el PATH y en `~/.cargo/bin` (el instalador no siempre lo añade a la sesión actual). Sin el binario, el simulador sigue con Go o con Python
(más lento). `--probar` corre `cargo test` antes de compilar.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FUENTE = RAIZ / "modelo" / "rust" / "lsim"
EXTENSION = ".exe" if sys.platform == "win32" else ""
DESTINO = RAIZ / "modelo" / "rust" / "bin" / f"lsim{EXTENSION}"


def buscar_cargo() -> str | None:
    return shutil.which("cargo") or next((str(p) for p in [Path.home() / ".cargo" / "bin" / f"cargo{EXTENSION}"] if p.is_file()), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probar", action="store_true", help="correr cargo test antes de compilar")
    args = ap.parse_args()
    cargo = buscar_cargo()
    if cargo is None:
        print("No encuentro cargo. Instala Rust desde https://rustup.rs o usa el simulador con Go o Python (más lento).")
        return 1
    if args.probar and subprocess.run([cargo, "test", "--release"], cwd=FUENTE, check=False).returncode != 0:  # noqa: S603
        return 1
    r = subprocess.run([cargo, "build", "--release"], cwd=FUENTE, check=False)  # noqa: S603
    binario = FUENTE / "target" / "release" / f"lsim{EXTENSION}"
    if r.returncode != 0 or not binario.is_file():
        print("falló la compilación")
        return r.returncode or 1
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binario, DESTINO)
    print(f"compilado: {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
