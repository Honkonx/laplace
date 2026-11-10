"""backend/scripts/doctor.py — diagnóstico de una instalación de Laplace («laplace doctor»).

  python backend/scripts/doctor.py            revisa todo y sale con código 1 si hay algún FALLO
  python backend/scripts/doctor.py --red      además prueba la salida a internet de las fuentes configuradas (sin gastar cuota)
  python backend/scripts/doctor.py --json     resultado en JSON

Cada revisión devuelve (estado, mensaje) con estado «ok» | «aviso» | «fallo». NUNCA se imprime el valor de una clave: solo si está
definida o vacía (`secrets-never-revealed.md`). Pensado para correr con el Python del propio instalador (`runtime/venv`).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sqlite3
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.core import conexiones as cx  # noqa: E402 — la lista única de conexiones (la misma del script configurar y del panel)

PUERTO_BACKEND = int(os.getenv("LAPLACE_PUERTO_BACKEND", "9001"))
PUERTO_AGENTE = int(os.getenv("LAPLACE_PUERTO_AGENTE", "9100"))
MODULOS_NUCLEO = ("fastapi", "uvicorn", "sqlalchemy", "alembic", "pydantic", "pydantic_settings", "httpx", "telegram", "apscheduler",
                  "argon2", "jwt", "slowapi", "tzdata")
# Antes eran listas escritas a mano y doctor contaba 5 fuentes de datos cuando el panel mostraba 6 (faltaba OddsPapi). Ahora salen del registro.
CLAVES_DATOS = tuple(c.variable for c in cx.CONEXIONES if c.grupo in ("partidos", "cuotas", "tablas"))
CLAVES_IA = tuple(c.variable for c in cx.proveedores_ia())


def revisar_python() -> tuple[str, str]:
    version = ".".join(str(x) for x in sys.version_info[:3])
    if sys.version_info < (3, 11):
        return "fallo", f"Python {version}: se necesita 3.11 o superior"
    return "ok", f"Python {version} ({sys.executable})"


def revisar_dependencias() -> tuple[str, str]:
    faltan = []
    for modulo in MODULOS_NUCLEO:
        try:
            importlib.import_module(modulo)
        except ImportError:
            faltan.append(modulo)
    if faltan:
        return "fallo", "faltan paquetes: " + ", ".join(faltan) + " (vuelve a correr el instalador)"
    return "ok", f"{len(MODULOS_NUCLEO)} paquetes del núcleo disponibles"


def _leer_env() -> dict[str, str]:
    ruta = RAIZ / ".env"
    datos: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, valor = linea.split("=", 1)
                datos[clave.strip()] = valor.strip()
    return datos


def _definida(valor: str | None) -> bool:
    return cx.valor_definido(valor)


def revisar_env() -> list[tuple[str, str, str]]:
    env = _leer_env()
    if not (RAIZ / ".env").exists():
        return [("Archivo .env", "fallo", "no existe: corre el instalador o copia .env.example a .env")]
    salida = [("Archivo .env", "ok", "existe")]
    for secreto in ("KAIROS_AUTH_SECRET", "WEB_JWT_SECRET"):
        valor = env.get(secreto, "")
        salida.append((secreto, "ok" if _definida(valor) and len(valor) >= 32 else "fallo",
                       "definido" if _definida(valor) and len(valor) >= 32 else "vacío, corto o de ejemplo: corre la instalación con --reconfigurar"))
    telegram = _definida(env.get("TELEGRAM_BOT_TOKEN"))
    salida.append(("Bot de Telegram principal", "ok" if telegram else "aviso", "token definido" if telegram else "sin TELEGRAM_BOT_TOKEN: el bot no arranca (la web y el agente sí)"))
    salida.append(("Administrador", "ok" if _definida(env.get("SPORTS_ADMIN_IDS")) else "aviso",
                   "SPORTS_ADMIN_IDS definida" if _definida(env.get("SPORTS_ADMIN_IDS")) else "SPORTS_ADMIN_IDS vacía: nadie podrá usar los comandos de administración"))
    ia = [c for c in CLAVES_IA if _definida(env.get(c))]
    salida.append(("IA", "ok" if ia else "aviso", ("proveedores con clave: " + ", ".join(c.removesuffix("_API_KEY").lower() for c in ia)) if ia
                   else "ninguna clave de IA: el bot responde solo con el motor estadístico"))
    datos = [c for c in CLAVES_DATOS if _definida(env.get(c))]
    puestas = {c.id for c in cx.CONEXIONES if _definida(env.get(c.variable))}
    faltan = cx.faltantes_para_pronosticar(puestas)
    salida.append(("Fuentes de datos", "aviso" if faltan else "ok", f"{len(datos)} de {len(CLAVES_DATOS)} con clave"
                   + (" — " + "; ".join(faltan) + ". Ponlas con: configurar" if faltan else " (cuotas + calendario: lo mínimo para pronosticar está puesto)")))
    agente = _definida(env.get("AGENT_TELEGRAM_BOT_TOKEN"))
    salida.append(("Bot de Telegram del agente", "ok" if agente else "aviso", "token definido" if agente else "sin AGENT_TELEGRAM_BOT_TOKEN: el agente solo funciona por la web"))
    return salida


def revisar_base() -> tuple[str, str]:
    try:
        from backend.api.core.config import settings
    except Exception as exc:  # noqa: BLE001
        return "fallo", f"no se pudo cargar la configuración: {type(exc).__name__}"
    if not settings.is_sqlite:
        return "aviso", "la base no es SQLite (Postgres): no se revisa aquí"
    ruta = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
    if not ruta.exists():
        return "fallo", f"no existe {ruta.name}: corre «alembic upgrade head» (el instalador lo hace)"
    try:
        conexion = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
        estado = conexion.execute("pragma quick_check").fetchone()[0]
        tablas = {fila[0] for fila in conexion.execute("select name from sqlite_master where type='table'")}
        conexion.close()
    except sqlite3.DatabaseError as exc:
        return "fallo", f"la base está dañada o no se puede leer: {exc}"
    faltan = [t for t in ("usuarios", "partidos_dia", "analisis_comparativo", "jobs") if t not in tablas]
    if estado != "ok" or faltan:
        return "fallo", f"quick_check={estado}; tablas que faltan: {', '.join(faltan) or 'ninguna'}"
    return "ok", f"{ruta.name} íntegra, {len(tablas)} tablas"


def revisar_integridad() -> tuple[str, str]:
    """Huérfanos de las relaciones lógicas (no hay claves foráneas): solo informa, nunca falla."""
    try:
        from backend.api.core.config import settings
        from backend.scripts import auditar_integridad

        if not settings.is_sqlite:
            return "aviso", "no se revisa en Postgres"
        ruta = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
        if not ruta.exists():
            return "aviso", "sin base de datos que revisar"
        filas = auditar_integridad.auditar(ruta)
    except Exception as exc:  # noqa: BLE001 — diagnóstico
        return "aviso", f"no se pudo revisar: {type(exc).__name__}"
    huerfanos = [f for f in filas if f["huerfanos"]]
    return ("aviso" if huerfanos else "ok"), auditar_integridad.resumen(filas)


def revisar_modelo() -> tuple[str, str]:
    try:
        from backend.api.services import modelo_historico
        artefactos = modelo_historico._artefactos()  # noqa: SLF001 — diagnóstico
    except Exception as exc:  # noqa: BLE001
        return "fallo", f"no cargó el módulo histórico: {type(exc).__name__}"
    if artefactos is None:
        return "aviso", "sin modelo histórico (no se publica; se entrena con tus datos): el motor usa solo las cuotas, y sin cuotas el partido queda sin pronóstico propio"
    return "ok", f"modelo histórico con {len(artefactos['ligas'])} ligas"


def revisar_web() -> tuple[str, str]:
    if (RAIZ / "frontend" / "dist" / "index.html").is_file():
        return "ok", "web compilada en frontend/dist (se sirve desde el puerto 9001)"
    return "aviso", "no hay frontend/dist: la web no se sirve (el instalador la compila si hay Node, o usa el paquete ya compilado)"


def _puerto_ocupado(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def revisar_servicios() -> list[tuple[str, str, str]]:
    salida = []
    for nombre, puerto, ruta in (("Backend", PUERTO_BACKEND, "/health"), ("Agente", PUERTO_AGENTE, "/health")):
        if not _puerto_ocupado(puerto):
            salida.append((nombre, "aviso", f"apagado (puerto {puerto} libre): «laplace iniciar» lo enciende"))
            continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{ruta}", timeout=5) as r:  # noqa: S310
                salida.append((nombre, "ok" if r.status == 200 else "fallo", f"responde en el puerto {puerto} (HTTP {r.status})"))
        except Exception as exc:  # noqa: BLE001
            salida.append((nombre, "fallo", f"el puerto {puerto} está ocupado pero no responde como Laplace: {type(exc).__name__}"))
    return salida


def revisar_red() -> list[tuple[str, str, str]]:
    salida = []
    for nombre, url in (("Ollama Cloud", "https://ollama.com/api/tags"), ("Telegram", "https://api.telegram.org"), ("The Odds API", "https://api.the-odds-api.com")):
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=10)  # noqa: S310
            salida.append((f"Red: {nombre}", "ok", "alcanzable"))
        except urllib.error.HTTPError as exc:  # responde (401/404): hay salida a internet, que es lo que se prueba
            salida.append((f"Red: {nombre}", "ok", f"alcanzable (HTTP {exc.code})"))
        except Exception as exc:  # noqa: BLE001
            salida.append((f"Red: {nombre}", "aviso", f"sin salida: {type(exc).__name__}"))
    return salida


def ejecutar(con_red: bool = False) -> list[tuple[str, str, str]]:
    resultados: list[tuple[str, str, str]] = []
    for nombre, revision in (("Python", revisar_python), ("Dependencias", revisar_dependencias)):
        resultados.append((nombre, *revision()))
    resultados.extend(revisar_env())
    for nombre, revision in (("Base de datos", revisar_base), ("Integridad referencial", revisar_integridad), ("Modelo histórico", revisar_modelo), ("Web", revisar_web)):
        resultados.append((nombre, *revision()))
    resultados.extend(revisar_servicios())
    if con_red:
        resultados.extend(revisar_red())
    return resultados


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--red", action="store_true", help="prueba la salida a internet")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    resultados = ejecutar(args.red)
    if args.json:
        print(json.dumps([{"revision": n, "estado": e, "detalle": d} for n, e, d in resultados], ensure_ascii=False, indent=2))
    else:
        marcas = {"ok": "[ OK  ]", "aviso": "[AVISO]", "fallo": "[FALLO]"}
        for nombre, estado, detalle in resultados:
            print(f"{marcas[estado]} {nombre}: {detalle}")
        fallos = sum(e == "fallo" for _, e, _ in resultados)
        avisos = sum(e == "aviso" for _, e, _ in resultados)
        print(f"\nResultado: {fallos} fallo(s), {avisos} aviso(s).")
    return 1 if any(e == "fallo" for _, e, _ in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
