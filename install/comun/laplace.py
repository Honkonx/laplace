"""install/comun/laplace.py — control de Laplace (backend + agente), igual en Windows y Linux.

  laplace iniciar [--lan] [--sin-agente] [--avisar] [--abrir]
                                            enciende el backend (puerto 9001: API, bot de Telegram, planificador y web) y el agente (9100);
                                            --avisar revisa antes lo mínimo para tener pronósticos y ofrece configurarlo; --abrir abre la web al terminar
  laplace configurar [...]                  detecta, prueba y configura las APIs (ver install/comun/configurar.py)
  laplace detener                           los apaga
  laplace reiniciar                         detener + iniciar
  laplace estado                            qué está encendido y si responde
  laplace logs [backend|agente] [-n 40]     últimas líneas del registro
  laplace doctor [--red]                    diagnóstico completo (backend/scripts/doctor.py)
  laplace abrir                             abre la web en el navegador

Los procesos quedan en segundo plano (sin ventana), con su PID en runtime/pids/ y sus registros en backend/logs/. Por defecto solo
escuchan en 127.0.0.1; `--lan` los abre a la red local (otra PC, el celular) y lo dice. Solo librería estándar.
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PIDS = RAIZ / "runtime" / "pids"
LOGS = RAIZ / "backend" / "logs"
ES_WINDOWS = os.name == "nt"

# Los puertos se pueden cambiar con LAPLACE_PUERTO_BACKEND / LAPLACE_PUERTO_AGENTE (p. ej. para probar una segunda copia). La web
# compilada espera el agente en el 9100 del mismo equipo: si lo cambias, la pantalla del agente deja de encontrarlo.
SERVICIOS = {
    "backend": {"modulo": "backend.api.main:app", "puerto": int(os.getenv("LAPLACE_PUERTO_BACKEND", "9001")), "descripcion": "API, bot de Telegram, planificador y web"},
    "agente": {"modulo": "backend.api.agent_main:app", "puerto": int(os.getenv("LAPLACE_PUERTO_AGENTE", "9100")), "descripcion": "agente de chat"},
}


def _vivo(pid: int) -> bool:
    if ES_WINDOWS:
        import ctypes
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        proceso = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not proceso:
            return False
        codigo = ctypes.c_ulong()
        kernel.GetExitCodeProcess(proceso, ctypes.byref(codigo))
        kernel.CloseHandle(proceso)
        return codigo.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _leer_pid(nombre: str) -> int | None:
    ruta = PIDS / f"{nombre}.pid"
    try:
        return int(ruta.read_text().strip())
    except (OSError, ValueError):
        return None


def _responde(puerto: int, ruta: str = "/health") -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{ruta}", timeout=3) as r:  # noqa: S310
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _ip_local() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # no envía nada: solo elige la interfaz de salida
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _origenes_cors(extra: str) -> str:
    actuales = ""
    env = RAIZ / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.startswith("CORS_ORIGINS="):
                actuales = linea.split("=", 1)[1].strip()
    lista = [o for o in actuales.split(",") if o]
    return ",".join(lista + ([extra] if extra and extra not in lista else []))


def _es_interactivo() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def configurar(argumentos: list[str] | None = None) -> int:
    return subprocess.call([sys.executable, str(RAIZ / "install" / "comun" / "configurar.py"), *(argumentos or [])])  # noqa: S603


def avisar_antes_de_iniciar() -> None:
    """Sin red: dice qué falta para tener pronósticos y, si hay terminal, ofrece abrir `configurar`. Nunca bloquea el arranque."""
    for ruta in (str(RAIZ), str(Path(__file__).resolve().parent)):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)
    try:
        import configurar_env as entorno
        from backend.api.core import conexiones as cx

        lineas = entorno.leer(RAIZ / ".env")
        puestas = {c.id for c in cx.CONEXIONES if cx.valor_definido(entorno.valor_de(lineas, c.variable))}
        faltan = cx.faltantes_para_pronosticar(puestas)
    except Exception:  # noqa: BLE001 — un aviso nunca debe impedir encender
        return
    if not faltan:
        return
    print("⚠  Antes de encender, ojo:")
    for texto in faltan:
        print(f"   - {texto}")
    if _es_interactivo():
        try:
            if input("¿Quieres configurarlo ahora? [S/n] ").strip().lower() not in ("n", "no"):
                configurar()
        except (EOFError, KeyboardInterrupt):
            print()
    else:
        print("   (configúralo cuando quieras con: configurar)")


def abrir_web_al_terminar(ip: str) -> None:
    if _es_interactivo() and not os.environ.get("LAPLACE_NO_ABRIR"):
        webbrowser.open(f"http://{ip}:{SERVICIOS['backend']['puerto']}/")


def iniciar(lan: bool, con_agente: bool, avisar: bool = False, abrir: bool = False) -> int:
    if avisar and (RAIZ / ".env").exists():
        avisar_antes_de_iniciar()
    PIDS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    if not (RAIZ / ".env").exists():
        print("Falta el archivo .env: corre primero el instalador (instalar.bat / instalar.sh).")
        return 1
    host = "0.0.0.0" if lan else "127.0.0.1"  # noqa: S104 — solo con --lan, y se avisa
    entorno = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    ip = _ip_local() if lan else "127.0.0.1"
    puerto_web = SERVICIOS["backend"]["puerto"]
    # El agente (otro puerto) debe aceptar el origen desde el que el navegador abre la web servida por el backend.
    origenes = _origenes_cors(f"http://127.0.0.1:{puerto_web}")
    origenes = ",".join([origenes] + [o for o in (f"http://localhost:{puerto_web}", f"http://{ip}:{puerto_web}") if o not in origenes.split(",")])
    entorno["CORS_ORIGINS"] = origenes
    codigo = 0
    for nombre, datos in SERVICIOS.items():
        if nombre == "agente" and not con_agente:
            continue
        pid = _leer_pid(nombre)
        if pid and _vivo(pid) and _responde(datos["puerto"]):
            print(f"{nombre}: ya está encendido (PID {pid}, puerto {datos['puerto']})")
            continue
        if _responde(datos["puerto"]):
            print(f"{nombre}: el puerto {datos['puerto']} ya está en uso por otro proceso; no se inicia (libéralo o cambia de puerto).")
            codigo = 1
            continue
        salida = open(LOGS / f"{nombre}.out.log", "ab")  # noqa: SIM115 — lo hereda el proceso hijo
        error = open(LOGS / f"{nombre}.err.log", "ab")  # noqa: SIM115
        orden = [sys.executable, "-m", "uvicorn", datos["modulo"], "--host", host, "--port", str(datos["puerto"])]
        opciones: dict = {"cwd": str(RAIZ), "env": entorno, "stdout": salida, "stderr": error, "stdin": subprocess.DEVNULL, "close_fds": True}
        if ES_WINDOWS:
            opciones["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        else:
            opciones["start_new_session"] = True
        proceso = subprocess.Popen(orden, **opciones)  # noqa: S603
        (PIDS / f"{nombre}.pid").write_text(str(proceso.pid))
        for _ in range(60):
            if _responde(datos["puerto"]):
                print(f"{nombre}: encendido (PID {proceso.pid}) — {datos['descripcion']}")
                break
            if proceso.poll() is not None:
                print(f"{nombre}: se cerró al arrancar (código {proceso.returncode}). Mira: laplace logs {nombre}")
                codigo = 1
                break
            time.sleep(0.5)
        else:
            print(f"{nombre}: no respondió en 30 s. Mira: laplace logs {nombre}")
            codigo = 1
    if codigo == 0:
        print(f"\nWeb:     http://{ip}:{SERVICIOS['backend']['puerto']}/")
        if lan:
            print("(abierto a tu red local: cualquiera en ella puede entrar; el firewall del sistema puede pedirte permiso)")
        print("Para cambiar claves o proveedores en cualquier momento: configurar")
        if abrir:
            abrir_web_al_terminar(ip)
    return codigo


def _matar(pid: int) -> None:
    if ES_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)  # noqa: S603, S607
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        for _ in range(20):
            if not _vivo(pid):
                return
            time.sleep(0.25)
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def detener() -> int:
    """Apaga lo que ESTE control encendió (por su PID). Un proceso ajeno en el mismo puerto no se toca."""
    for nombre in SERVICIOS:
        pid = _leer_pid(nombre)
        if pid and _vivo(pid):
            _matar(pid)
            print(f"{nombre}: detenido (PID {pid})")
        else:
            print(f"{nombre}: no estaba encendido")
        (PIDS / f"{nombre}.pid").unlink(missing_ok=True)
    return 0


def estado() -> int:
    todo_bien = True
    for nombre, datos in SERVICIOS.items():
        pid = _leer_pid(nombre)
        vivo = bool(pid and _vivo(pid))
        responde = _responde(datos["puerto"])
        if vivo and responde:
            print(f"{nombre}: ENCENDIDO (PID {pid}, puerto {datos['puerto']})")
        elif responde:
            print(f"{nombre}: responde en el puerto {datos['puerto']}, pero no lo inició este control (sin PID registrado)")
        else:
            print(f"{nombre}: APAGADO")
            todo_bien = nombre != "backend" and todo_bien
    return 0 if todo_bien else 1


def logs(nombre: str, lineas: int) -> int:
    for sufijo in ("out", "err"):
        ruta = LOGS / f"{nombre}.{sufijo}.log"
        print(f"--- {ruta.name} ---")
        if ruta.exists():
            contenido = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(contenido[-lineas:]) or "(vacío)")
        else:
            print("(no existe todavía)")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "configurar":  # argparse no deja pasar «--estado» tras un subcomando con REMAINDER
        return configurar(sys.argv[2:])
    ap = argparse.ArgumentParser(prog="laplace", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("iniciar")
    p.add_argument("--lan", action="store_true", help="escuchar en toda la red local (por defecto solo 127.0.0.1)")
    p.add_argument("--sin-agente", action="store_true")
    p.add_argument("--avisar", action="store_true", help="revisa antes lo mínimo para tener pronósticos y ofrece configurarlo")
    p.add_argument("--abrir", action="store_true", help="abre la web en el navegador al terminar (solo con terminal)")
    cf = sub.add_parser("configurar", add_help=False)
    cf.add_argument("resto", nargs=argparse.REMAINDER)
    sub.add_parser("detener")
    r = sub.add_parser("reiniciar")
    r.add_argument("--lan", action="store_true")
    r.add_argument("--sin-agente", action="store_true")
    sub.add_parser("estado")
    lg = sub.add_parser("logs")
    lg.add_argument("servicio", nargs="?", default="backend", choices=list(SERVICIOS))
    lg.add_argument("-n", type=int, default=40)
    d = sub.add_parser("doctor")
    d.add_argument("--red", action="store_true")
    sub.add_parser("abrir")
    args = ap.parse_args(sys.argv[1:] or ["--help"])  # sin argumentos (doble clic en laplace.bat) se muestra la ayuda, no un error

    if args.orden == "iniciar":
        return iniciar(args.lan, not args.sin_agente, args.avisar, args.abrir)
    if args.orden == "configurar":
        return configurar(args.resto)
    if args.orden == "detener":
        return detener()
    if args.orden == "reiniciar":
        detener()
        time.sleep(1)
        return iniciar(args.lan, not args.sin_agente)
    if args.orden == "estado":
        return estado()
    if args.orden == "logs":
        return logs(args.servicio, args.n)
    if args.orden == "doctor":
        return subprocess.call([sys.executable, str(RAIZ / "backend" / "scripts" / "doctor.py")] + (["--red"] if args.red else []))  # noqa: S603
    if args.orden == "abrir":
        webbrowser.open(f"http://127.0.0.1:{SERVICIOS['backend']['puerto']}/")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
