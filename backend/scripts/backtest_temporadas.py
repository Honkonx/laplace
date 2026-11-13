"""backtest_temporadas.py — ¿el simulador de temporadas (`ml/laplace/liga.py`) acierta lo que dice? (MM-22/MM-23). Solo lectura de los CSV históricos.

  python backend/scripts/backtest_temporadas.py [--fraccion 0.6] [--n-sim 2000] [--ligas E0 SP1 ...]

Para cada temporada completa de cada liga: se congela el estado del modelo (Elo y tasas de gol) cuando se jugó `fraccion` de los partidos, se simula el resto con `simular_temporada`
y se compara con la tabla FINAL real:
- cobertura: fracción de equipos cuyos puntos finales caen dentro del intervalo p05–p95 simulado (objetivo ≈ 0,90);
- error medio absoluto de los puntos finales esperados frente a una extrapolación simple (puntos por partido actuales × partidos restantes);
- Brier de «campeón»: suma de (probabilidad − 1 si fue campeón)² de la liga frente a una referencia que reparte por puntos actuales.
Escribe `backend/data/resultados/backtest_temporadas.json`; el simulador marca `validado: true` solo si la cobertura está en [0,85; 0,95] y supera a la extrapolación (datos locales: sin el archivo sigue `false`).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as e  # noqa: E402
from backend.api.ml.laplace import liga  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "backtest_temporadas.json"
LIGAS_POR_DEFECTO = ("E0", "SP1", "I1", "D1", "F1", "N1", "P1", "B1", "T1", "SC0")
DESDE = "2019/2020"


def _tabla(partidos: list[dict]) -> dict[str, dict]:
    t: dict[str, dict] = defaultdict(lambda: {"pj": 0, "pts": 0, "gf": 0, "gc": 0})
    for p in partidos:
        for eq, a, b in ((p["local"], p["gl"], p["gv"]), (p["visitante"], p["gv"], p["gl"])):
            f = t[eq]
            f["pj"] += 1
            f["gf"] += a
            f["gc"] += b
            f["pts"] += 3 if a > b else 1 if a == b else 0
    return dict(t)


def una_temporada(historia: list[dict], temporada: list[dict], fraccion: float, n_sim: int, sigma: float = 0.0) -> dict | None:
    """Resultado del backtest de UNA temporada; None si no tiene la forma de un campeonato todos contra todos."""
    ps = sorted(temporada, key=lambda p: (p["dia"], p["local"]))
    equipos = {p["local"] for p in ps} | {p["visitante"] for p in ps}
    if len(equipos) < 10 or len(ps) != len(equipos) * (len(equipos) - 1):
        return None
    corte = int(len(ps) * fraccion)
    jugados, pendientes = ps[:corte], ps[corte:]
    estado = e.EstadoLiga(k_elo=e.HIPER_DEFECTO["k_elo"], alfa=e.HIPER_DEFECTO["alfa"], extras=tuple(e.HIPER_DEFECTO["extras"]))
    for p in [*historia, *jugados]:
        estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], e.tiros_de(p))
    tabla_jugada, tabla_final = _tabla(jugados), _tabla(ps)
    filas = [{"equipo": eq, **tabla_jugada.get(eq, {"pj": 0, "pts": 0, "gf": 0, "gc": 0})} for eq in sorted(equipos)]
    res = liga.simular_temporada(filas, [{"local": p["local"], "visitante": p["visitante"]} for p in pendientes], lambda a, b: estado.lambdas(a, b), n_sim=n_sim, semilla=11, sigma_fuerza=sigma)
    pts_sim, pos = res["resultado"]["puntos"], res["resultado"]["posiciones"]
    restantes = defaultdict(int)
    for p in pendientes:
        restantes[p["local"]] += 1
        restantes[p["visitante"]] += 1
    dentro, err_modelo, err_base = 0, 0.0, 0.0
    for eq in equipos:
        real = tabla_final[eq]["pts"]
        s = pts_sim[eq]
        dentro += s["p05"] <= real <= s["p95"]
        err_modelo += abs(s["media"] - real)
        actual = tabla_jugada.get(eq, {"pj": 0, "pts": 0})
        err_base += abs(actual["pts"] + (actual["pts"] / actual["pj"] if actual["pj"] else 1.35) * restantes[eq] - real)
    campeon = max(equipos, key=lambda q: (tabla_final[q]["pts"], tabla_final[q]["gf"] - tabla_final[q]["gc"]))
    brier_modelo = sum((pos[eq][0] - (1.0 if eq == campeon else 0.0)) ** 2 for eq in equipos)
    total = sum(max(tabla_jugada.get(eq, {"pts": 0})["pts"], 0) ** 4 for eq in equipos) or 1  # referencia: reparto por puntos actuales (potencia 4 para concentrar)
    brier_base = sum((max(tabla_jugada.get(eq, {"pts": 0})["pts"], 0) ** 4 / total - (1.0 if eq == campeon else 0.0)) ** 2 for eq in equipos)
    n = len(equipos)
    return {"equipos": n, "cobertura": dentro / n, "mae_modelo": err_modelo / n, "mae_extrapolacion": err_base / n, "brier_campeon_modelo": brier_modelo, "brier_campeon_referencia": brier_base}


def correr(por_liga: dict[str, list[dict]], ligas, fraccion: float, n_sim: int, sigma: float = 0.0) -> dict:
    filas = []
    for codigo in ligas:
        ps = por_liga.get(codigo, [])
        temporadas = sorted({p["temporada"] for p in ps})
        for t in temporadas:
            if t < DESDE:
                continue
            actual = [p for p in ps if p["temporada"] == t]
            r = una_temporada([p for p in ps if p["temporada"] < t], actual, fraccion, n_sim, sigma)
            if r:
                filas.append({"liga": codigo, "temporada": t, **r})
    if not filas:
        return {"n_temporadas": 0, "validado": False}
    n_eq = sum(f["equipos"] for f in filas)
    cobertura = sum(f["cobertura"] * f["equipos"] for f in filas) / n_eq
    mae_m = sum(f["mae_modelo"] * f["equipos"] for f in filas) / n_eq
    mae_b = sum(f["mae_extrapolacion"] * f["equipos"] for f in filas) / n_eq
    bm = sum(f["brier_campeon_modelo"] for f in filas) / len(filas)
    bb = sum(f["brier_campeon_referencia"] for f in filas) / len(filas)
    return {"n_temporadas": len(filas), "n_equipos": n_eq, "fraccion": fraccion, "n_sim": n_sim, "sigma_fuerza": sigma, "cobertura_p05_p95": round(cobertura, 4), "mae_puntos_modelo": round(mae_m, 3),
            "mae_puntos_extrapolacion": round(mae_b, 3), "brier_campeon_modelo": round(bm, 4), "brier_campeon_referencia": round(bb, 4),
            "validado": 0.85 <= cobertura <= 0.95 and mae_m <= mae_b, "generado": date.today().isoformat(), "detalle": filas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fraccion", type=float, default=0.6)
    ap.add_argument("--n-sim", type=int, default=2000)
    ap.add_argument("--sigma", type=float, default=0.0, help="incertidumbre de la fuerza de cada equipo (log)")
    ap.add_argument("--ligas", nargs="*", default=list(LIGAS_POR_DEFECTO))
    args = ap.parse_args()
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    r = correr(por_liga, args.ligas, args.fraccion, args.n_sim, args.sigma)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print({k: v for k, v in r.items() if k != "detalle"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
