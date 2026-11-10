"""generar_referencia_docs.py — genera las referencias técnicas de `docs/backend/referencia/` a partir del CÓDIGO (no de otros documentos).

  python backend/scripts/generar_referencia_docs.py             escribe los 4 documentos
  python backend/scripts/generar_referencia_docs.py --verificar  sale con 1 si alguno está desactualizado (lo usa una prueba)

Documentos: API (rutas reales de FastAPI y quién puede llamarlas), base de datos (tablas, columnas, claves y índices de SQLAlchemy), scripts (docstring de cada
script y de los lanzadores) y trabajos programados (cron, función y docstring de `main.py`). La salida es determinista: sin fechas ni rutas de la máquina.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DESTINO = RAIZ / "docs" / "backend" / "referencia"
AVISO = "> Generado por `backend/scripts/generar_referencia_docs.py` a partir del código. No se edita a mano: se regenera con ese script (una prueba avisa si quedó desactualizado).\n"
# Mismas reglas que el exportador del público: estos scripts son del repo de trabajo.
PREFIJOS_SCRIPTS_DEV = ("qa_", "benchmark_", "sandbox_")


def _primera_linea(doc: str | None) -> str:
    """Primera frase del primer párrafo del docstring (una frase completa, no una línea cortada)."""
    if not doc:
        return "—"
    parrafo = " ".join(l.strip() for l in doc.strip().split("\n\n")[0].splitlines()).strip()
    parrafo = re.sub(r"^[\w./-]+\.py\s*[—-]\s*", "", parrafo)
    frase = re.split(r"(?<=\.)\s", parrafo, maxsplit=1)[0]
    if len(frase) > 170:
        frase = frase[:167].rsplit(" ", 1)[0] + "…"
    return (frase.rstrip(":") or "—").replace("|", "\\|")


# ---------------------------------------------------------------- API
def _acceso(ruta) -> str:
    dependant = ruta.dependant
    nombres = {getattr(d.call, "__name__", "") for d in dependant.dependencies}
    if "requerir_admin" in nombres:
        return "admin (JWT con rol admin)"
    if "obtener_usuario_actual" in nombres:
        return "sesión (JWT)"
    if any(h.alias == "x-kairos-key" or h.name == "x_kairos_key" for h in dependant.header_params):
        return "app Android (`x-kairos-key`)"
    return "público"


def referencia_api() -> str:
    from backend.api.main import app

    filas: dict[str, list[tuple[str, str, str, str]]] = {}
    for ruta in app.routes:
        if not hasattr(ruta, "dependant") or not getattr(ruta, "include_in_schema", True):
            continue
        etiqueta = (getattr(ruta, "tags", None) or ["(sin grupo)"])[0]
        resumen = _primera_linea(getattr(ruta.endpoint, "__doc__", None))
        for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
            filas.setdefault(etiqueta, []).append((ruta.path, metodo, _acceso(ruta), resumen))
    total = sum(len(v) for v in filas.values())
    sal = ["# Referencia de la API", "", AVISO, f"{total} rutas en {len(filas)} grupos. «Acceso» sale de las dependencias reales de cada ruta; la API interactiva está en `/docs` con el backend encendido.", ""]
    for etiqueta in sorted(filas):
        sal += [f"## {etiqueta}", "", "| Método | Ruta | Acceso | Qué hace |", "|---|---|---|---|"]
        for ruta, metodo, acceso, resumen in sorted(filas[etiqueta]):
            sal.append(f"| {metodo} | `{ruta}` | {acceso} | {resumen} |")
        sal.append("")
    return "\n".join(sal)


# ---------------------------------------------------------------- Base de datos
def referencia_base_de_datos() -> str:
    import backend.api.models  # noqa: F401  (registra todos los modelos)
    from backend.api.db.session import Base

    sal = ["# Referencia de la base de datos", "", AVISO,
           f"{len(Base.metadata.tables)} tablas, tomadas de los modelos de SQLAlchemy (`backend/api/models/`). SQLite por defecto; PostgreSQL con `DATABASE_URL`. Las fechas se escriben siempre desde Python.", ""]
    for nombre in sorted(Base.metadata.tables):
        tabla = Base.metadata.tables[nombre]
        sal += [f"## `{nombre}`", "", "| Columna | Tipo | Nulo | Clave / valor por defecto |", "|---|---|---|---|"]
        for col in tabla.columns:
            extra = []
            if col.primary_key:
                extra.append("PK")
            extra += [f"FK → `{fk.target_fullname}`" for fk in col.foreign_keys]
            if col.unique:
                extra.append("único")
            if col.server_default is not None:
                extra.append(f"defecto `{getattr(col.server_default.arg, 'text', col.server_default.arg)}`")
            sal.append(f"| `{col.name}` | {str(col.type)} | {'sí' if col.nullable else 'no'} | {', '.join(extra) or '—'} |")
        indices = sorted(tabla.indexes, key=lambda i: i.name or "")
        if indices:
            sal += ["", "Índices: " + "; ".join(f"`{i.name}` ({', '.join(c.name for c in i.columns)}{', único' if i.unique else ''})" for i in indices)]
        sal.append("")
    return "\n".join(sal)


# ---------------------------------------------------------------- Scripts
LANZADORES = (
    ("instalar.bat / instalar.sh", "Instala Laplace: Python y Node propios, dependencias, `.env`, primer administrador."),
    ("configurar.bat / configurar.sh", "Menú para ver, probar, poner o cambiar las claves y el orden de la IA (`install/comun/configurar.py`)."),
    ("iniciar.bat / iniciar.sh", "Enciende API + bot de Telegram + planificador + web, y el agente."),
    ("laplace.bat / laplace.sh", "Control general: `iniciar`, `detener`, `estado`, `doctor`, `configurar`…"),
)


def _docstring(ruta: Path) -> str:
    try:
        return _primera_linea(ast.get_docstring(ast.parse(ruta.read_text(encoding="utf-8"))))
    except (SyntaxError, UnicodeDecodeError):
        return "—"


def referencia_scripts() -> str:
    sal = ["# Referencia de scripts", "", AVISO, "## Lanzadores de la raíz", "", "| Script | Para qué |", "|---|---|"]
    sal += [f"| `{n}` | {d} |" for n, d in LANZADORES]
    sal += ["", "## `backend/scripts/`", "", "Se ejecutan con el Python del entorno: `python backend/scripts/<nombre>.py --help`.", "", "| Script | Qué hace |", "|---|---|"]
    for ruta in sorted((RAIZ / "backend" / "scripts").glob("*.py")):
        if ruta.name.startswith("_") or ruta.name.startswith(PREFIJOS_SCRIPTS_DEV):
            continue
        sal.append(f"| `{ruta.name}` | {_docstring(ruta)} |")
    sal += ["", "## `install/comun/`", "", "| Módulo | Qué hace |", "|---|---|"]
    for ruta in sorted((RAIZ / "install" / "comun").glob("*.py")):
        sal.append(f"| `{ruta.name}` | {_docstring(ruta)} |")
    sal.append("")
    return "\n".join(sal)


# ---------------------------------------------------------------- Trabajos programados
def referencia_jobs() -> str:
    texto = (RAIZ / "backend" / "api" / "main.py").read_text(encoding="utf-8")
    arbol = ast.parse(texto)
    docs = {n.name: _primera_linea(ast.get_docstring(n)) for n in ast.walk(arbol) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    sal = ["# Referencia de trabajos programados", "", AVISO,
           "El planificador (APScheduler) corre dentro del backend, en la zona horaria de Chile (`America/Santiago`). Cada trabajo también se puede lanzar a mano por `POST /api/v1/scheduler/...` (ver la referencia de la API).", "",
           "| Id | Cuándo | Función | Qué hace |", "|---|---|---|---|"]
    trabajos = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "attr", "") == "add_job" and len(nodo.args) >= 2 and isinstance(nodo.args[1], ast.Call):
            cron = ", ".join(f"{k.arg}={ast.unparse(k.value).strip(chr(39))}" for k in nodo.args[1].keywords if k.arg != "timezone")
            id_ = next((ast.literal_eval(k.value) for k in nodo.keywords if k.arg == "id"), "?")
            trabajos.append((nodo.lineno, id_, cron, ast.unparse(nodo.args[0])))
    for _, id_, cron, funcion in sorted(trabajos):
        sal.append(f"| `{id_}` | {cron} | `{funcion}` | {docs.get(funcion, '—')} |")
    sal.append("")
    return "\n".join(sal)


def construir() -> dict[str, str]:
    return {
        "API.md": referencia_api(), "BASE_DE_DATOS.md": referencia_base_de_datos(),
        "SCRIPTS.md": referencia_scripts(), "TRABAJOS_PROGRAMADOS.md": referencia_jobs(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verificar", action="store_true", help="no escribe; sale con 1 si algún documento está desactualizado")
    args = ap.parse_args()
    obsoletos = []
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in construir().items():
        archivo = DESTINO / nombre
        actual = archivo.read_bytes().decode("utf-8").replace("\r\n", "\n") if archivo.exists() else None
        if actual != contenido:
            obsoletos.append(nombre)
            if not args.verificar:
                archivo.write_bytes(contenido.encode("utf-8"))
    if args.verificar:
        print("desactualizados:", ", ".join(obsoletos) or "ninguno")
        return 1 if obsoletos else 0
    print("escritos:", ", ".join(obsoletos) or "(todo estaba al día)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
