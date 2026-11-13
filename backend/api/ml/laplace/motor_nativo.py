"""ml/laplace/motor_nativo.py — ejecución común de los núcleos Monte Carlo nativos (Rust y Go) del simulador.

Reparto de lenguajes de Laplace: **Rust** para el cálculo caliente (`modelo/rust/lsim`), **Go** para microservicios y conexión (`modelo/go`; su núcleo `lsim` queda como respaldo del cálculo)
y **Python** para la lógica y como referencia: si ningún binario existe, falla o tarda demasiado, `liga.py` simula en Python como siempre. Los binarios hablan JSON por stdin/stdout, sin cgo ni
dependencias en tiempo de ejecución. Con otro generador aleatorio que Python los resultados son estadísticamente equivalentes (se mide en `test_motor_go.py` y `test_motor_rust.py`), no
idénticos bit a bit; por eso la salida declara qué `motor` la produjo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
EXTENSION = ".exe" if sys.platform == "win32" else ""
PLAZO_SEGUNDOS = 15.0  # menor que el plazo del router (20 s): el proceso muere antes de que la petición se dé por vencida
MAX_BYTES_SALIDA = 8_000_000


class MotorNoDisponible(RuntimeError):
    """El binario nativo no existe o no pudo ejecutarse; quien llama usa el siguiente de la cadena (Rust → Go → Python)."""


def desactivado() -> bool:
    """`LAPLACE_MOTOR_SIM=python` apaga todos los núcleos nativos (pruebas, comparación y diagnóstico)."""
    return os.environ.get("LAPLACE_MOTOR_SIM", "").lower() == "python"


def buscar_binario(variable: str, candidatas: list[Path]) -> Path | None:
    """La ruta explícita de la variable de entorno o la primera candidata que exista; None si no hay o los núcleos nativos están apagados."""
    if desactivado():
        return None
    rutas = [Path(p) for p in [os.environ.get(variable, "")] if p] + candidatas
    return next((c for c in rutas if c.is_file()), None)


def correr_binario(exe: Path | None, nombre: str, equipos: list[dict], partidos: list[dict], n_sim: int, semilla: int, desempates: tuple[str, ...],
                   sigma: float, paso: float) -> tuple[list[list[int]], list[list[int]], int]:
    """(conteo de posiciones por equipo, puntos finales por equipo, simulaciones útiles). `partidos` = [{h, a, lh, la, fijo?}]."""
    if exe is None:
        raise MotorNoDisponible(f"no hay binario de {nombre}")
    carga = json.dumps({"equipos": equipos, "partidos": partidos, "n_sim": n_sim, "semilla": semilla, "desempates": list(desempates), "sigma": sigma, "paso": paso})
    try:
        r = subprocess.run([str(exe)], input=carga.encode("utf-8"), capture_output=True, timeout=PLAZO_SEGUNDOS, check=False)  # noqa: S603 — ruta fija del repo o variable de entorno del operador
    except (OSError, subprocess.SubprocessError) as exc:
        raise MotorNoDisponible(f"no se pudo ejecutar el motor de {nombre}: {type(exc).__name__}") from exc
    if r.returncode != 0 or not r.stdout or len(r.stdout) > MAX_BYTES_SALIDA:
        raise MotorNoDisponible(f"el motor de {nombre} terminó con código {r.returncode}")
    try:
        datos = json.loads(r.stdout)
        puntos = [[h["min"] + k for k, c in enumerate(h["conta"]) for _ in range(c)] for h in datos["puntos"]]
        return datos["conteo"], puntos, int(datos["utiles"])
    except (ValueError, KeyError, TypeError) as exc:
        raise MotorNoDisponible(f"respuesta inválida del motor de {nombre}") from exc


def _local(url: str) -> bool:
    """El servicio solo se llama por la interfaz local: una URL ajena podría ser un servidor que devuelva lo que quiera."""
    from urllib.parse import urlparse

    return urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")


def correr_servicio(url: str, equipos: list[dict], partidos: list[dict], n_sim: int, semilla: int, desempates: tuple[str, ...], sigma: float, paso: float) -> tuple[list[list[int]], list[list[int]], int]:
    """Mismo cálculo por el microservicio en Go (`modelo/go/simd`): tope de simulaciones y plazo que mata de verdad el proceso. Cualquier fallo (apagado, lleno, plazo) es `MotorNoDisponible`."""
    if not _local(url):
        raise MotorNoDisponible("el servicio de simulación solo se llama por la interfaz local")
    carga = json.dumps({"equipos": equipos, "partidos": partidos, "n_sim": n_sim, "semilla": semilla, "desempates": list(desempates), "sigma": sigma, "paso": paso}).encode("utf-8")
    peticion = urllib.request.Request(url.rstrip("/") + "/v1/simular", data=carga, headers={"Content-Type": "application/json"}, method="POST")  # noqa: S310 — solo loopback, comprobado arriba
    try:
        with urllib.request.urlopen(peticion, timeout=PLAZO_SEGUNDOS) as r:  # noqa: S310
            cuerpo = r.read(MAX_BYTES_SALIDA + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise MotorNoDisponible(f"el servicio de simulación no respondió: {type(exc).__name__}") from exc
    if not cuerpo or len(cuerpo) > MAX_BYTES_SALIDA:
        raise MotorNoDisponible("respuesta vacía o demasiado grande del servicio de simulación")
    try:
        datos = json.loads(cuerpo)
        puntos = [[h["min"] + k for k, c in enumerate(h["conta"]) for _ in range(c)] for h in datos["puntos"]]
        return datos["conteo"], puntos, int(datos["utiles"])
    except (ValueError, KeyError, TypeError) as exc:
        raise MotorNoDisponible("respuesta inválida del servicio de simulación") from exc
