"""ml/laplace/motor_go.py — puente a `modelo/go/lsim`, el núcleo Monte Carlo en Go (MM-41): ahora el RESPALDO nativo; el principal es Rust (`motor_rust.py`).

La ejecución del binario es común (`motor_nativo.py`). Python sigue siendo la referencia y el último respaldo. Se compila con `go build` (ver `backend/scripts/construir_go.py`).
"""
from __future__ import annotations

from pathlib import Path

from backend.api.ml.laplace import motor_nativo
from backend.api.ml.laplace.motor_nativo import MotorNoDisponible, PLAZO_SEGUNDOS  # noqa: F401 — se reexportan: `liga.py` y las pruebas usan estos nombres

RAIZ = motor_nativo.RAIZ
NOMBRE = "lsim" + motor_nativo.EXTENSION


def ruta_binario() -> Path | None:
    """`LAPLACE_GO_LSIM` (ruta explícita) o los directorios de compilación habituales; None si no hay binario. `LAPLACE_MOTOR_SIM=python` lo desactiva."""
    return motor_nativo.buscar_binario("LAPLACE_GO_LSIM", [RAIZ / "modelo" / "go" / "bin" / NOMBRE, RAIZ / "runtime" / "bin" / NOMBRE])


def disponible() -> bool:
    return ruta_binario() is not None


def correr(equipos: list[dict], partidos: list[dict], n_sim: int, semilla: int, desempates: tuple[str, ...], sigma: float, paso: float) -> tuple[list[list[int]], list[list[int]], int]:
    return motor_nativo.correr_binario(ruta_binario(), "Go", equipos, partidos, n_sim, semilla, desempates, sigma, paso)
