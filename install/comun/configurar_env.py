"""install/comun/configurar_env.py — crea y completa el `.env` de Laplace durante la instalación (Windows y Linux).

  python install/comun/configurar_env.py                 crea el `.env` desde `.env.example` y genera los secretos propios (no pregunta nada)
  python install/comun/configurar_env.py --reconfigurar   además regenera lo fijo Y los secretos propios (¡invalida la clave de la app!)

Las CLAVES de las APIs ya no se piden aquí: las detecta, prueba y guarda `install/comun/configurar.py` (`configurar.bat` / `configurar.sh`), que el instalador
ofrece al terminar y que se puede ejecutar cuando se quiera. Reglas (`secrets-never-revealed.md`): un secreto guardado NUNCA se vuelve a mostrar (solo «definida»
/ «vacía»); un valor ya definido no se pisa salvo `--reconfigurar`. Solo usa la librería estándar (corre con el Python del propio instalador).
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
from backend.api.core import conexiones as cx  # noqa: E402 — la lista única de conexiones
ENV = RAIZ / ".env"
EJEMPLO = RAIZ / ".env.example"

# Valores de ejemplo que NO son una clave real: dejarlos haría creer que el proveedor está configurado.
PLACEHOLDER = re.compile(r"^(your_|replace_with|changeme|tu_|comma,separated|<)", re.IGNORECASE)
CLAVES_IA = ("OLLAMA_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")

# Secretos propios del sistema: se generan solos, nunca se piden.
GENERADOS = {"KAIROS_AUTH_SECRET": 32, "WEB_JWT_SECRET": 48}

# Valores por defecto que sí se fijan (no son secretos).
FIJOS = {
    "OLLAMA_CLOUD_MODEL": "gpt-oss:120b",
    "AI_ROUTING_BOT": "ollama_cloud,groq,gemini,openrouter,claude",
    "AI_ROUTING_CANAL": "ollama_cloud,groq,gemini,openrouter,claude",
    "AI_ROUTING_AGENTE": "ollama_cloud,groq,gemini,openrouter,claude",
    "AI_ROUTING_LABORATORIO": "ollama_cloud,groq,gemini,openrouter,claude",
}

# Orígenes que el navegador usa para abrir la web servida por el backend (puerto 9001) y en desarrollo (9002/9003). El agente (9100)
# es otro origen para el navegador, así que debe aceptarlos; se SUMAN a los que ya hubiera, nunca se quitan.
ORIGENES_NECESARIOS = ("http://127.0.0.1:9001", "http://localhost:9001", "http://127.0.0.1:9002", "http://localhost:9002")


def leer(ruta: Path) -> list[str]:
    return ruta.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if ruta.exists() else []


def valor_de(lineas: list[str], variable: str) -> str | None:
    for linea in lineas:
        if linea.startswith(f"{variable}="):
            return linea.split("=", 1)[1].strip()
    return None


def poner(lineas: list[str], variable: str, valor: str) -> None:
    for i, linea in enumerate(lineas):
        if linea.startswith(f"{variable}="):
            lineas[i] = f"{variable}={valor}"
            return
    while lineas and lineas[-1] == "":
        lineas.pop()
    lineas.extend([f"{variable}={valor}", ""])


def definida(lineas: list[str], variable: str) -> bool:
    valor = valor_de(lineas, variable)
    return bool(valor) and not PLACEHOLDER.match(valor)


def crear_base() -> list[str]:
    """`.env` nuevo desde el ejemplo, con los placeholders vaciados y los secretos propios generados."""
    lineas = leer(EJEMPLO)
    for i, linea in enumerate(lineas):
        if "=" in linea and not linea.lstrip().startswith("#"):
            variable, valor = linea.split("=", 1)
            if PLACEHOLDER.match(valor.strip()):
                lineas[i] = f"{variable}="
    return lineas


def aplicar(lineas: list[str], reconfigurar: bool) -> list[str]:
    resumen: list[str] = []
    for variable, largo in GENERADOS.items():
        if reconfigurar or not definida(lineas, variable) or valor_de(lineas, variable) in ("changeme-set-in-env",):
            poner(lineas, variable, secrets.token_urlsafe(largo))
            resumen.append(f"{variable}: generada")
    for variable, valor in FIJOS.items():
        if reconfigurar or not valor_de(lineas, variable):
            poner(lineas, variable, valor)
    actuales = [o.strip() for o in (valor_de(lineas, "CORS_ORIGINS") or "").split(",") if o.strip()]
    poner(lineas, "CORS_ORIGINS", ",".join(actuales + [o for o in ORIGENES_NECESARIOS if o not in actuales]))
    # El ejemplo trae AGENT_IA_ACTIVA=false (sin claves no hay IA). Con al menos una clave de IA el agente debe usarla.
    if any(definida(lineas, c) for c in CLAVES_IA) and (valor_de(lineas, "AGENT_IA_ACTIVA") or "false").lower() == "false":
        poner(lineas, "AGENT_IA_ACTIVA", "true")
        resumen.append("AGENT_IA_ACTIVA: activada (hay al menos una clave de IA)")
    puestas = sum(1 for c in cx.CONEXIONES if definida(lineas, c.variable))
    print(f"\n.env listo: {puestas} de {len(cx.CONEXIONES)} conexiones con clave (los valores nunca se muestran). Para ponerlas o probarlas: configurar.")
    for linea in resumen:
        print(f"  {linea}")
    return lineas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sin-asistente", action="store_true", help="(compatibilidad: este script ya no pregunta nada)")
    ap.add_argument("--reconfigurar", action="store_true", help="regenera lo fijo y los secretos propios")
    args = ap.parse_args()

    if not EJEMPLO.exists():
        print(f"ERROR: falta {EJEMPLO.name} en la raíz del proyecto", file=sys.stderr)
        return 1
    existe = ENV.exists()
    lineas = leer(ENV) if existe else crear_base()
    lineas = aplicar(lineas, args.reconfigurar)
    ENV.write_text("\n".join(lineas).rstrip("\n") + "\n", encoding="utf-8")
    try:
        ENV.chmod(0o600)  # en Linux, solo el dueño lee las claves (en Windows no tiene efecto)
    except OSError:
        pass
    print(f"\n.env {'actualizado' if existe else 'creado'} en {ENV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
