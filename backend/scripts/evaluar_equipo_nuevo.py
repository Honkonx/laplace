"""backend/scripts/evaluar_equipo_nuevo.py — ¿qué probabilidad dar cuando un equipo no está en el modelo?

Regla `evidencia-historica-antes-de-promover.md`: antes de dejar que `historico` responda con un equipo
ausente del ajuste (ascendido, recién llegado o con otro nombre) se mide, walk-forward, contra la tasa base
y contra el mercado SOBRE LOS MISMOS partidos. Se compara, solo en partidos donde al menos un equipo es
desconocido para el modelo vigente en esa fecha:

  tasa_base        frecuencias H/D/A de la liga acumuladas antes del partido.
  dc_promedio      Dixon-Coles tratando al desconocido como promedio de la liga (lo que hace `lambdas`).
  dc_prior         igual, pero con un ataque/defensa de "equipo nuevo" estimado en el periodo de desarrollo
                   (< 2023-07-01) y evaluado en el de prueba (>= 2023-07-01), que el ajuste nunca vio.
  mercado          cuotas promedio sin margen (Shin), solo donde existen.

Uso:  .venv_backend\\Scripts\\python.exe backend/scripts/evaluar_equipo_nuevo.py [--json ruta]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, dixon_coles, mercado, metricas  # noqa: E402
from backend.scripts.evaluar_modelo_historico import CORTE_DEV_TEST, INICIO_EVALUACION  # noqa: E402

XI, RIDGE = dixon_coles.XI_POR_DEFECTO, dixon_coles.RIDGE_POR_DEFECTO
RESULTADOS = REPO / "backend" / "data" / "resultados"
MIN_PREVIOS_LIGA = 200


def _tasa_base(previos: list[dict]) -> tuple[float, float, float]:
    n = len(previos)
    return tuple(sum(p["resultado"] == r for p in previos) / n for r in "HDA")  # type: ignore[return-value]


def estimar_prior(filas_dev: list[dict], modelos_mu: dict[str, tuple[float, float]]) -> dict:
    """Ataque/defensa medios de un equipo desconocido: cuántos goles marca/recibe de más o de menos que el
    promedio de su liga cuando el modelo lo trata como promedio. Una sola pareja global (robusta)."""
    gf = lam_f = gc = lam_c = 0.0
    n = 0
    for f in filas_dev:
        p = f["p"]
        desconocido_local = f["local_desconocido"]
        desconocido_visita = f["visita_desconocido"]
        if desconocido_local == desconocido_visita:  # solo el caso limpio: exactamente uno desconocido
            continue
        if desconocido_local:
            gf += p["gl"]; lam_f += f["lam_h"]; gc += p["gv"]; lam_c += f["lam_a"]
        else:
            gf += p["gv"]; lam_f += f["lam_a"]; gc += p["gl"]; lam_c += f["lam_h"]
        n += 1
    if n < 30 or lam_f <= 0 or lam_c <= 0 or gf <= 0 or gc <= 0:
        return {"ataque": 0.0, "defensa": 0.0, "n": n}
    return {"ataque": math.log(gf / lam_f), "defensa": -math.log(gc / lam_c), "n": n}


def _con_prior(f: dict, prior: dict) -> tuple[float, float]:
    lam_h, lam_a = f["lam_h"], f["lam_a"]
    if f["local_desconocido"]:
        lam_h *= math.exp(prior["ataque"])
        lam_a *= math.exp(-prior["defensa"])
    if f["visita_desconocido"]:
        lam_a *= math.exp(prior["ataque"])
        lam_h *= math.exp(-prior["defensa"])
    return lam_h, lam_a


def _resumen(pares: list[tuple[tuple[float, float, float], str]]) -> dict:
    if not pares:
        return {"n": 0, "rps": None, "log_loss": None}
    return {"n": len(pares), "rps": round(metricas.promedio(metricas.rps, pares), 4),
            "log_loss": round(metricas.promedio(metricas.log_loss, pares), 4)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", default=str(RESULTADOS / "evaluacion_equipo_nuevo.json"))
    args = ap.parse_args()
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    por_liga = {k: v for k, v in por_liga.items() if len(v) >= 400}
    # `recorrer_dc` solo informa si ambos son conocidos; aquí hace falta saber CUÁL lado es el desconocido.
    detallado = []
    for liga, partidos in por_liga.items():
        tuplas = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in partidos]
        modelo, proximo = None, 0
        for i, p in enumerate(partidos):
            if p["dia"] < INICIO_EVALUACION:
                continue
            if modelo is None or p["dia"] >= proximo:
                modelo = dixon_coles.ajustar(tuplas[:i], p["dia"], xi=XI, ridge=RIDGE)
                proximo = p["dia"] + 28
            if modelo is None or i < MIN_PREVIOS_LIGA:
                continue
            ld, vd = p["local"] not in modelo.ataque, p["visitante"] not in modelo.ataque
            if not (ld or vd):
                continue
            lam_h, lam_a, _ = dixon_coles.lambdas(modelo, p["local"], p["visitante"])
            detallado.append({"p": p, "lam_h": lam_h, "lam_a": lam_a, "local_desconocido": ld, "visita_desconocido": vd,
                              "rho": modelo.rho, "base": _tasa_base(partidos[max(0, i - 1500):i])})
    dev = [f for f in detallado if f["p"]["dia"] < CORTE_DEV_TEST]
    prueba = [f for f in detallado if f["p"]["dia"] >= CORTE_DEV_TEST]
    prior = estimar_prior(dev, {})
    print(f"partidos con algún equipo desconocido: dev={len(dev)} prueba={len(prueba)}; prior={prior}")

    salida: dict = {"prior_estimado_en_desarrollo": prior, "n_dev": len(dev), "n_prueba": len(prueba), "estratos": {}}
    estratos = {
        "un_desconocido": [f for f in prueba if f["local_desconocido"] != f["visita_desconocido"]],
        "ambos_desconocidos": [f for f in prueba if f["local_desconocido"] and f["visita_desconocido"]],
    }
    for nombre, grupo in estratos.items():
        metodos: dict[str, list] = defaultdict(list)
        con_cuotas = [f for f in grupo if f["p"].get("ap_prom")]
        for f in grupo:
            r = f["p"]["resultado"]
            metodos["tasa_base"].append((f["base"], r))
            metodos["dc_promedio"].append((dixon_coles.probabilidades_desde_lambdas(f["lam_h"], f["lam_a"], f["rho"]), r))
            lh, la = _con_prior(f, prior)
            metodos["dc_prior"].append((dixon_coles.probabilidades_desde_lambdas(lh, la, f["rho"]), r))
        mismos = {"tasa_base": [], "dc_promedio": [], "dc_prior": [], "mercado": []}
        for f in con_cuotas:
            r = f["p"]["resultado"]
            mismos["tasa_base"].append((f["base"], r))
            mismos["dc_promedio"].append((dixon_coles.probabilidades_desde_lambdas(f["lam_h"], f["lam_a"], f["rho"]), r))
            lh, la = _con_prior(f, prior)
            mismos["dc_prior"].append((dixon_coles.probabilidades_desde_lambdas(lh, la, f["rho"]), r))
            mismos["mercado"].append((mercado.quitar_margen_shin(*f["p"]["ap_prom"]), r))
        salida["estratos"][nombre] = {
            "todos": {m: _resumen(v) for m, v in metodos.items()},
            "solo_con_cuotas_mismos_partidos": {m: _resumen(v) for m, v in mismos.items()},
        }
        print(f"\n== {nombre}: n={len(grupo)} (con cuotas {len(con_cuotas)}) ==")
        for sub, tabla in salida["estratos"][nombre].items():
            print(f"  [{sub}]")
            for m, r in tabla.items():
                print(f"    {m:<12} n={r['n']:<6} rps={r['rps']} log_loss={r['log_loss']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresultado en {args.json}")


if __name__ == "__main__":
    main()
