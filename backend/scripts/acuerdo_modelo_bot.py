"""acuerdo_modelo_bot.py — si se le dan los mismos datos al modelo Laplace y al bot, ¿dan un resultado parecido? Solo lectura de los CSV históricos.

  python backend/scripts/acuerdo_modelo_bot.py [--corte 2023-07-01]

Sobre los partidos de la prueba (posteriores al corte, sin fuga del futuro) con cuotas de apertura compara, partido a partido:
- **modelo Laplace g3** (solo con sus datos, sin cuotas),
- **bot sin cuotas** (lo que el consenso da cuando no hay cuotas: 55 % Laplace + 45 % Dixon-Coles),
- **bot con cuotas** (aproximación del consenso vigente: 0,70 mercado sin margen + 0,25 Dixon-Coles, renormalizado),
- el **mercado** sin margen.
Mide la diferencia media absoluta de probabilidad, el porcentaje de partidos donde eligen el mismo pick y, para cada uno, su log loss. Escribe `backend/data/resultados/acuerdo_modelo_bot.json`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos, dixon_coles, metricas  # noqa: E402
from backend.api.ml.laplace import entrenamiento as e  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "acuerdo_modelo_bot.json"
PESO_LAPLACE_SIN_CUOTAS = 0.55


def _mezcla(ps, ws):
    s = sum(ws)
    return tuple(sum(w * p[i] for p, w in zip(ps, ws)) / s for i in range(3))


def _pick(p):
    return max(range(3), key=lambda i: p[i])


def comparar(a, b) -> dict:
    """Acuerdo entre dos listas de probabilidades (mismos partidos): diferencia media absoluta por resultado, acuerdo de pick y correlación de P(local)."""
    n = len(a)
    dif = [sum(abs(x[i] - y[i]) for x, y in zip(a, b)) / n for i in range(3)]
    mismo = sum(_pick(x) == _pick(y) for x, y in zip(a, b)) / n
    ma, mb = sum(x[0] for x in a) / n, sum(y[0] for y in b) / n
    cov = sum((x[0] - ma) * (y[0] - mb) for x, y in zip(a, b))
    va, vb = sum((x[0] - ma) ** 2 for x in a), sum((y[0] - mb) ** 2 for y in b)
    return {"dif_abs_local": round(dif[0], 4), "dif_abs_empate": round(dif[1], 4), "dif_abs_visitante": round(dif[2], 4), "mismo_pick": round(mismo, 4),
            "correlacion_p_local": round(cov / math.sqrt(va * vb), 4) if va > 0 and vb > 0 else None}


def correr(corte: int) -> dict:
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    art = e.entrenar_jerarquico(por_liga, corte, con_goles=False)
    filas = []
    for codigo, info in art["ligas"].items():
        prueba = sorted((p for p in por_liga[codigo] if p["dia"] >= corte), key=lambda x: (x["dia"], x["local"]))
        st = e.EstadoLiga.de_dict(info["estado"])
        w = e.pesos_de(art, codigo)
        hist = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in por_liga[codigo] if p["dia"] < corte]
        mdc, ddc = None, None
        for p in prueba:
            c = p.get("ap_prom") if isinstance(p.get("ap_prom"), tuple) else None
            pl = e.probs_lineal(w, st.features(p["local"], p["visitante"]))
            if c:
                if ddc is None or p["dia"] - ddc >= 7:
                    mdc, ddc = dixon_coles.ajustar(hist, p["dia"]), p["dia"]
                pdc = dixon_coles.probabilidades(mdc, p["local"], p["visitante"]) if mdc else None
                if pdc:
                    mk = e.sin_margen(c)
                    filas.append({"laplace": pl, "mercado": mk, "dc": pdc, "r": p["resultado"], "liga": codigo})
            st.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], e.tiros_de(p))
            hist.append((p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]))
    for f in filas:
        f["bot_sin_cuotas"] = _mezcla([f["laplace"], f["dc"]], [PESO_LAPLACE_SIN_CUOTAS, 1 - PESO_LAPLACE_SIN_CUOTAS])
        f["bot_con_cuotas"] = _mezcla([f["mercado"], f["dc"]], [0.70, 0.25])
    columnas = ("laplace", "bot_sin_cuotas", "bot_con_cuotas", "mercado")
    perdida = {c: round(metricas.promedio(metricas.log_loss, [(f[c], f["r"]) for f in filas]), 5) for c in columnas}
    pares = [("laplace", "bot_sin_cuotas"), ("laplace", "bot_con_cuotas"), ("laplace", "mercado"), ("bot_sin_cuotas", "bot_con_cuotas"), ("bot_con_cuotas", "mercado")]
    acuerdo = {f"{a} vs {b}": comparar([f[a] for f in filas], [f[b] for f in filas]) for a, b in pares}
    return {"corte": date.fromordinal(corte).isoformat(), "n_partidos": len(filas), "log_loss": perdida, "acuerdo": acuerdo, "generado": date.today().isoformat()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corte", default="2023-07-01")
    args = ap.parse_args()
    r = correr(date.fromisoformat(args.corte).toordinal())
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
