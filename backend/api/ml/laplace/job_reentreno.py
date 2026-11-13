"""job_reentreno.py — reentreno semanal del modelo Laplace desde el scheduler, sin romper el backend.

Igual que `ml/job_reajuste.py`: el servidor no tiene numpy/scipy, así que el entrenamiento corre en un SUBPROCESO con `LAPLACE_PYTHON_ML`. Toma el histórico y la capa en vivo, registra el modelo nuevo
en sombra y lo promueve solo si pasa las guardas de `modelo_laplace.reentrenar`. Nunca lanza: devuelve `{ok, detalle, ...}`. `LAPLACE_REENTRENO_AUTOMATICO=0` lo apaga.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from backend.api.ml.job_reajuste import RAIZ_REPO, python_ml

SCRIPT = RAIZ_REPO / "backend" / "scripts" / "modelo_laplace.py"
TIMEOUT_SEGUNDOS = 1800
_FALSOS = {"0", "false", "no", "off", "n", ""}


def reentreno_activo() -> bool:
    return os.getenv("LAPLACE_REENTRENO_AUTOMATICO", "1").strip().lower() not in _FALSOS


def _fallo(detalle: str) -> dict:
    return {"ok": False, "promovido": False, "detalle": detalle[:300]}


def ejecutar_reentreno(ejecutar=subprocess.run, script: Path = SCRIPT, timeout: int = TIMEOUT_SEGUNDOS) -> dict:
    interprete = python_ml()
    if not interprete:
        return _fallo("sin Python para el reentreno: define LAPLACE_PYTHON_ML")
    if not script.exists():
        return _fallo(f"no existe {script.name}")
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        previo = ejecutar([interprete, "-c", "import numpy, scipy"], capture_output=True, text=True, timeout=60, env=entorno)
        if previo.returncode != 0:
            return _fallo(f"{interprete} no tiene numpy/scipy (define LAPLACE_PYTHON_ML)")
        proceso = ejecutar([interprete, str(script), "reentrenar", "--auto"], capture_output=True, text=True, timeout=timeout, env=entorno, cwd=str(RAIZ_REPO))
    except subprocess.TimeoutExpired:
        return _fallo(f"el reentreno excedió {timeout}s y se canceló")
    except (OSError, ValueError) as exc:
        return _fallo(f"no se pudo lanzar el reentreno: {type(exc).__name__}")
    if proceso.returncode != 0:
        cola = (proceso.stderr or proceso.stdout or "").strip().splitlines()[-1:] or ["sin salida"]
        return _fallo(f"el reentreno terminó con código {proceso.returncode}: {cola[0]}")
    lineas = [ln for ln in (proceso.stdout or "").strip().splitlines() if ln.startswith("{")]
    try:
        return json.loads(lineas[-1])
    except (IndexError, ValueError):
        return _fallo("el reentreno no devolvió un resumen JSON legible")
