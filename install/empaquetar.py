"""install/empaquetar.py — arma la carpeta portable `laplace/` (y sus .zip / .tar.gz) con SOLO lo necesario para correr Laplace.

  python install/empaquetar.py                    compila la web (pnpm) si falta y arma dist-portable/laplace/
  python install/empaquetar.py --sin-compilar     no compila la web (usa frontend/dist tal como está)
  python install/empaquetar.py --con-datos        incluye también el histórico completo para entrenar (≈60 MB)
  python install/empaquetar.py --salida RUTA      carpeta de salida (por defecto dist-portable/)

La carpeta resultante no trae Python, Node ni dependencias: el instalador (`instalar.bat` / `instalar.sh`) los descarga, verifica y
deja dentro de `runtime/`. Tampoco trae `.env`, base de datos, registros ni claves. Los `.sh` salen siempre con LF y los `.bat` con
CRLF, aunque el árbol de trabajo esté en Windows. Solo librería estándar; compilar la web usa pnpm (npm está prohibido).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.db", "*.db-wal", "*.db-shm", ".pytest_cache", "*.log", "node_modules")

# (origen, destino) relativos a la raíz; las carpetas se copian completas (menos IGNORAR).
CARPETAS = ["backend/api", "backend/scripts", "backend/agents", "backend/knowledge", "install", "frontend/dist"]
ARCHIVOS = ["backend/requirements.txt", "backend/requirements-dev.txt", "backend/requirements-postgres.txt", "backend/requirements-ml.txt",
            ".env.example", "instalar.bat", "instalar.sh", "configurar.bat", "configurar.sh", "iniciar.bat", "iniciar.sh", "laplace.bat", "laplace.sh", "pytest.ini"]
DATOS_MINIMOS = ["backend/data/datos/football-data/equipos_alias.json", "backend/data/datos/vivo", "backend/data/datos/catalogo_ligas.json"]

LEEME = """# Laplace — carpeta portable

Bot de pronósticos de fútbol (Telegram), agente de chat y web, en una sola carpeta. No necesitas instalar Python ni Node: el instalador
los descarga (verificando su huella SHA-256), los deja dentro de `runtime/` y no toca nada del sistema.

## Instalar (una sola vez)
- **Windows:** doble clic en `instalar.bat` (o `instalar.bat -SinAsistente` para no preguntar nada ahora).
- **Linux / macOS / WSL:** `bash instalar.sh` (o `bash instalar.sh --sin-asistente`).

Al terminar te ofrece **configurar tus conexiones**: `configurar` detecta qué APIs (datos, IA, Telegram) tienes, prueba cada una y te deja poner o cambiar
su clave por número (sin mostrarla). Todas son opcionales y puedes volver cuando quieras con `configurar.bat` / `./configurar.sh`.

## Usar
| Qué | Windows | Linux / macOS |
|---|---|---|
| Encender (avisa si falta algo y abre la web) | `iniciar.bat` | `./iniciar.sh` |
| Configurar o cambiar tus APIs | `configurar.bat` | `./configurar.sh` |
| Ver si está encendido | `laplace.bat estado` | `./laplace.sh estado` |
| Apagar | `laplace.bat detener` | `./laplace.sh detener` |
| Revisar la instalación | `laplace.bat doctor` | `./laplace.sh doctor` |
| Ver los registros | `laplace.bat logs` | `./laplace.sh logs` |
| Abrir la web | `laplace.bat abrir` | `./laplace.sh abrir` |

La web queda en http://127.0.0.1:9001/ . Por defecto solo se abre en este equipo; `iniciar --lan` la abre a tu red local (otra PC, el celular).

## Qué hay dentro
`backend/` (API, bot de Telegram, planificador), `backend/agents/` y `backend/knowledge/` (agente y base de conocimiento), `frontend/dist/` (la web ya
compilada), `install/` (instalador, asistente de claves, control) y, tras instalar, `runtime/` (Python propio) y `.env` (tus claves; no lo compartas).

Más datos de entrenamiento (para el reajuste semanal del modelo) no vienen en el paquete básico: se generan con los resultados que el propio
bot recoge, o se empaqueta con `--con-datos`.
"""


def compilar_web() -> None:
    web = RAIZ / "frontend"
    if (web / "dist" / "index.html").exists():
        return
    pnpm = shutil.which("pnpm")
    if not pnpm:
        sys.exit("Falta frontend/dist y pnpm no está en el PATH: compila la web (cd frontend && pnpm install && pnpm build) o pasa --sin-compilar.")
    subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=web, check=True)  # noqa: S603
    subprocess.run([pnpm, "build"], cwd=web, check=True)  # noqa: S603


def normalizar_fines_de_linea(raiz_paquete: Path) -> None:
    for ruta in raiz_paquete.rglob("*"):
        if not ruta.is_file():
            continue
        if ruta.suffix == ".sh":
            ruta.write_bytes(ruta.read_bytes().replace(b"\r\n", b"\n"))
        elif ruta.suffix in (".bat", ".cmd"):
            ruta.write_bytes(ruta.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


def armar(salida: Path, con_datos: bool) -> Path:
    paquete = salida / "laplace"
    if paquete.exists():
        shutil.rmtree(paquete)
    paquete.mkdir(parents=True)
    for carpeta in CARPETAS:
        origen = RAIZ / carpeta
        if origen.exists():
            shutil.copytree(origen, paquete / carpeta, ignore=IGNORAR)
        else:
            print(f"aviso: no existe {carpeta}, se omite")
    for archivo in ARCHIVOS:
        origen = RAIZ / archivo
        if origen.exists():
            (paquete / archivo).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, paquete / archivo)
    for dato in DATOS_MINIMOS + (["backend/data"] if con_datos else []):
        origen = RAIZ / dato
        destino = paquete / dato
        if origen.is_dir():
            shutil.copytree(origen, destino, ignore=IGNORAR, dirs_exist_ok=True)
        elif origen.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino)
    (paquete / "backend" / "db").mkdir(parents=True, exist_ok=True)
    (paquete / "backend" / "db" / ".gitkeep").write_text("", encoding="utf-8")
    (paquete / "LEEME.md").write_text(LEEME, encoding="utf-8")
    normalizar_fines_de_linea(paquete)
    return paquete


def comprimir(paquete: Path) -> list[Path]:
    salida = paquete.parent
    archivos = []
    destino_zip = salida / "laplace-portable.zip"
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(paquete.rglob("*")):
            if ruta.is_file():
                z.write(ruta, ruta.relative_to(paquete.parent).as_posix())
    archivos.append(destino_zip)
    destino_tar = salida / "laplace-portable.tar.gz"
    with tarfile.open(destino_tar, "w:gz") as t:
        t.add(paquete, arcname="laplace", filter=lambda info: _con_permisos(info))
    archivos.append(destino_tar)
    return archivos


def _con_permisos(info: tarfile.TarInfo) -> tarfile.TarInfo:
    if info.isfile() and info.name.endswith((".sh",)):
        info.mode = 0o755  # que `./instalar.sh` funcione directo en Linux
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--salida", default=str(RAIZ / "dist-portable"))
    ap.add_argument("--sin-compilar", action="store_true")
    ap.add_argument("--con-datos", action="store_true")
    args = ap.parse_args()
    if not args.sin_compilar:
        compilar_web()
    if not (RAIZ / "frontend" / "dist" / "index.html").exists():
        print("aviso: el paquete saldrá SIN la web compilada (frontend/dist no existe)")
    paquete = armar(Path(args.salida), args.con_datos)
    tamano = sum(f.stat().st_size for f in paquete.rglob("*") if f.is_file())
    print(f"paquete: {paquete} ({tamano / 1_048_576:.1f} MB, {sum(1 for f in paquete.rglob('*') if f.is_file())} archivos)")
    for archivo in comprimir(paquete):
        print(f"  {archivo.name}: {archivo.stat().st_size / 1_048_576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
