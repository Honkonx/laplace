"""Mide el tiempo de los tres núcleos del simulador (Python, Go y Rust) con una liga realista y comprueba que coinciden dentro del error Monte Carlo.

Uso: python backend/scripts/medir_motores.py [--n-sim 20000] [--equipos 20]   (no escribe nada; imprime una tabla Markdown)
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.ml.laplace import liga, motor_go, motor_rust  # noqa: E402


def mundo(n: int, jugados: float = 0.5):
    eq = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    pares = [(a, b) for a in eq for b in eq if a != b]
    pend = [{"local": a, "visitante": b} for a, b in pares[int(len(pares) * jugados):]]
    return tabla, pend, lambda l, v: (1.3 + 0.03 * (int(l[1:]) % 7), 1.0 + 0.02 * (int(v[1:]) % 5))


def medir(motor: str, n_sim: int, equipos: int, repeticiones: int = 3) -> tuple[float, dict]:
    tabla, pend, lam = mundo(equipos)
    tiempos, ultimo = [], {}
    for _ in range(repeticiones):
        t = time.perf_counter()
        ultimo = liga.simular_temporada(tabla, pend, lam, n_sim=n_sim, semilla=3, motor=motor)
        tiempos.append(time.perf_counter() - t)
    return statistics.median(tiempos), ultimo


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-sim", type=int, default=20000)
    ap.add_argument("--equipos", type=int, default=20)
    a = ap.parse_args()
    disponibles = {"python": True, "go": motor_go.disponible(), "rust": motor_rust.disponible()}
    resultados = {m: medir(m, a.n_sim, a.equipos) for m, ok in disponibles.items() if ok}
    base_t = resultados["python"][0]
    print("| Motor | Mediana (s) | Veces más rápido que Python | Máx. diferencia en P(posición) frente a Python |\n|---|---:|---:|---:|")
    ref = resultados["python"][1]["resultado"]["posiciones"]
    for m, (t, r) in resultados.items():
        dif = max(abs(x - y) for e in ref for x, y in zip(ref[e], r["resultado"]["posiciones"][e]))
        print(f"| {r['motor']} | {t:.3f} | {base_t / t:.1f}× | {dif:.4f} (error esperado ≈ {5 * math.sqrt(0.25 / a.n_sim * 2):.4f}) |")
    print(f"\n{a.equipos} equipos, {len(mundo(a.equipos)[1])} partidos pendientes, {a.n_sim} simulaciones, mediana de 3 corridas (incluye el arranque del proceso y la conversión JSON).")
