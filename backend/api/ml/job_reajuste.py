"""ml/job_reajuste.py — ejecuta el reajuste semanal de los modelos desde el scheduler, sin romper el backend.

El runtime del servidor NO tiene numpy/scipy (solo lee el JSON del artefacto), así que el reajuste
(`backend/scripts/reajustar_modelos.py`) corre en un SUBPROCESO con un Python que sí los tenga:
`LAPLACE_PYTHON_ML` (ruta al intérprete) o, por defecto, el `python` del PATH. Si ese Python no
tiene las dependencias, el script no existe, falla o excede el tiempo, el resultado es `ok=False` con
un detalle claro — nunca una excepción hacia el scheduler. Una validación que NO pasa (datos en vivo
insuficientes, modelo peor) no es un fallo: el job cumplió y el artefacto vigente se conserva (`ok=True`).

Variables de entorno (leídas con `os.getenv`, no pasan por `core/config.py`):
  LAPLACE_REAJUSTE_AUTOMATICO  "1" por defecto; "0"/"false"/"no"/"off" apaga el cron (no el disparo manual).
  LAPLACE_PYTHON_ML            intérprete con numpy+scipy; por defecto `python` del PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
SCRIPT_REAJUSTE = RAIZ_REPO / "backend" / "scripts" / "reajustar_modelos.py"
TIMEOUT_SEGUNDOS = 900
_FALSOS = {"0", "false", "no", "off", "n", ""}


def reajuste_activo() -> bool:
    return os.getenv("LAPLACE_REAJUSTE_AUTOMATICO", "1").strip().lower() not in _FALSOS


def python_ml() -> str | None:
    """Intérprete configurado (`LAPLACE_PYTHON_ML`) o el primer `python`/`python3` del PATH."""
    configurado = os.getenv("LAPLACE_PYTHON_ML", "").strip()
    if configurado:
        return configurado
    return shutil.which("python") or shutil.which("python3")


def _fallo(detalle: str) -> dict:
    return {"ok": False, "reemplazado": False, "detalle": detalle[:300]}


def ejecutar_reajuste(
    ejecutar=subprocess.run, script: Path = SCRIPT_REAJUSTE, timeout: int = TIMEOUT_SEGUNDOS,
) -> dict:
    """Exporta resultados vivos + reajusta + valida + reemplaza (atómico) en un subproceso.

    `ejecutar` es inyectable (tests con subprocesos simulados). Devuelve siempre un dict
    {ok, reemplazado, detalle, ...}; nunca lanza."""
    interprete = python_ml()
    if not interprete:
        return _fallo("sin Python para el reajuste: define LAPLACE_PYTHON_ML o pon python en el PATH")
    if not script.exists():
        return _fallo(f"no existe {script.name}")
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        previo = ejecutar([interprete, "-c", "import numpy, scipy"], capture_output=True, text=True, timeout=60, env=entorno)
        if previo.returncode != 0:
            return _fallo(f"{interprete} no tiene numpy/scipy (define LAPLACE_PYTHON_ML con un Python que los tenga)")
        proceso = ejecutar([interprete, str(script), "--exportar", "--aplicar", "--json"], capture_output=True,
                           text=True, timeout=timeout, env=entorno, cwd=str(RAIZ_REPO))
    except subprocess.TimeoutExpired:
        return _fallo(f"el reajuste excedio {timeout}s y se cancelo")
    except (OSError, ValueError) as exc:
        return _fallo(f"no se pudo lanzar el reajuste: {type(exc).__name__}")
    if proceso.returncode != 0:
        cola = (proceso.stderr or proceso.stdout or "").strip().splitlines()[-1:] or ["sin salida"]
        from backend.api.ml import datos

        if "FileNotFoundError" in cola[0] and not datos.RUTA_DATOS.exists():
            # Instalación sin datos históricos propios (p. ej. el repo público): el reajuste no aplica; no es un fallo.
            return {"ok": True, "reemplazado": False, "detalle": "sin datos históricos propios (backend/data/datos/football-data): el reajuste no aplica en esta instalación"}
        return _fallo(f"el reajuste termino con codigo {proceso.returncode}: {cola[0]}")
    lineas = [ln for ln in (proceso.stdout or "").strip().splitlines() if ln.startswith("{")]
    try:
        resumen = json.loads(lineas[-1])
    except (IndexError, ValueError):
        return _fallo("el reajuste no devolvio un resumen JSON legible")
    return {"ok": True, "reemplazado": bool(resumen.get("reemplazado")), "detalle": detalle_corto(resumen), "resumen": resumen}


def detalle_corto(resumen: dict) -> str:
    """Una línea para `scheduler_runs.detalle`."""
    if resumen.get("reemplazado"):
        return f"reemplazado: {len(resumen.get('ligas_reajustadas', []))} ligas; {resumen.get('motivo', '')}"[:300]
    return f"sin reemplazo: {resumen.get('motivo', 'sin motivo')}"[:300]


if __name__ == "__main__":  # humo manual: python -m backend.api.ml.job_reajuste
    print(json.dumps(ejecutar_reajuste(), ensure_ascii=False, default=str)[:2000], file=sys.stdout)
