"""ml/laplace/motor_rust.py — puente a `modelo/rust/lsim`, el núcleo Monte Carlo en Rust: el motor PRINCIPAL del cálculo caliente del simulador.

Rust da el mejor rendimiento (paralelo por bloques fijos, resultado reproducible en cualquier máquina); si falta o falla, la cadena sigue con Go (`motor_go.py`) y por último Python.
Se compila con `cargo build --release` (ver `backend/scripts/construir_rust.py`).
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.api.ml.laplace import motor_nativo
from backend.api.ml.laplace.motor_nativo import MotorNoDisponible  # noqa: F401 — la misma clase para toda la cadena

RAIZ = motor_nativo.RAIZ
NOMBRE = "lsim" + motor_nativo.EXTENSION


def ruta_binario() -> Path | None:
    """`LAPLACE_RUST_LSIM` (ruta explícita) o los directorios de compilación habituales; None si no hay binario. `LAPLACE_MOTOR_SIM=python` lo desactiva."""
    return motor_nativo.buscar_binario("LAPLACE_RUST_LSIM", [RAIZ / "modelo" / "rust" / "bin" / NOMBRE, RAIZ / "modelo" / "rust" / "lsim" / "target" / "release" / NOMBRE, RAIZ / "runtime" / "bin" / ("lsim_rs" + motor_nativo.EXTENSION)])


def disponible() -> bool:
    return ruta_binario() is not None


def correr(equipos: list[dict], partidos: list[dict], n_sim: int, semilla: int, desempates: tuple[str, ...], sigma: float, paso: float) -> tuple[list[list[int]], list[list[int]], int]:
    """Por el microservicio en Go si `LAPLACE_SIMD_URL` está definida y responde (el plazo mata el proceso de verdad); si no, el binario directamente."""
    url = os.environ.get("LAPLACE_SIMD_URL", "")
    if url and not motor_nativo.desactivado():
        try:
            return motor_nativo.correr_servicio(url, equipos, partidos, n_sim, semilla, desempates, sigma, paso)
        except MotorNoDisponible:
            pass
    return motor_nativo.correr_binario(ruta_binario(), "Rust", equipos, partidos, n_sim, semilla, desempates, sigma, paso)
