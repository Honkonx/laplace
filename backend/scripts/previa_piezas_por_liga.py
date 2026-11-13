"""previa_piezas_por_liga.py — rendimiento histórico de cada pieza (modelo Laplace, Dixon-Coles, mercado y «bot» aproximado) POR LIGA: la previa de los pesos del agente (MA-20).

  python backend/scripts/previa_piezas_por_liga.py [--corte 2023-07-01]

Entrena el modelo Laplace con lo anterior al corte, recorre la prueba (walk-forward) y mide log loss por liga de cada pieza sobre los MISMOS partidos de esa liga:
- `modelo`: Laplace g3 (sin cuotas);  - `dixon_coles`: Dixon-Coles reajustado cada 7 días (sin cuotas);
- `mercado`: cuotas de apertura sin margen (solo partidos con cuotas);
- `bot`: aproximación del consenso del bot = 0,70 mercado + 0,25 Dixon-Coles (renormalizado) con cuotas y Dixon-Coles solo sin ellas.
Escribe `backend/data/datos/resultados/previa_piezas_por_liga.json` (datos locales, no se publican). Solo lectura de los CSV históricos; no toca la base.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos, dixon_coles, metricas  # noqa: E402
from backend.api.ml.laplace import entrenamiento as e  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "datos" / "resultados" / "previa_piezas_por_liga.json"
MIN_PARTIDOS = 150


def _mezcla_bot(mercado: tuple, dc: tuple) -> tuple:
    return tuple((0.70 * m + 0.25 * d) / 0.95 for m, d in zip(mercado, dc))


def calcular(por_liga: dict[str, list[dict]], corte: int) -> dict:
    art = e.entrenar_jerarquico(por_liga, corte, con_goles=False)
    salida: dict[str, dict] = {}
    for codigo, info in art["ligas"].items():
        prueba = sorted((p for p in por_liga[codigo] if p["dia"] >= corte), key=lambda x: (x["dia"], x["local"]))
        if len(prueba) < MIN_PARTIDOS:
            continue
        st, w = e.EstadoLiga.de_dict(info["estado"]), e.pesos_de(art, codigo)
        hist = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in por_liga[codigo] if p["dia"] < corte]
        mdc, ddc = None, None
        acum: dict[str, list] = {"modelo": [], "dixon_coles": [], "mercado": [], "bot": []}
        for p in prueba:
            r = p["resultado"]
            pm = e.probs_lineal(w, st.features(p["local"], p["visitante"]))
            if ddc is None or p["dia"] - ddc >= 7:
                mdc, ddc = dixon_coles.ajustar(hist, p["dia"]), p["dia"]
            pdc = dixon_coles.probabilidades(mdc, p["local"], p["visitante"]) if mdc else None
            c = p.get("cuotas") or (p.get("ap_prom") if isinstance(p.get("ap_prom"), tuple) else None)
            if pdc:
                acum["modelo"].append((pm, r))
                acum["dixon_coles"].append((pdc, r))
                if c:
                    mk = e.sin_margen(c)
                    acum["mercado"].append((mk, r))
                    acum["bot"].append((_mezcla_bot(mk, pdc), r))
                else:
                    acum["bot"].append((pdc, r))
            st.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], e.tiros_de(p))
            hist.append((p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]))
        salida[codigo] = {pieza: {"n": len(v), "log_loss": round(metricas.promedio(metricas.log_loss, v), 5), "rps": round(metricas.promedio(metricas.rps, v), 5)}
                          for pieza, v in acum.items() if len(v) >= 30}
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corte", default="2023-07-01")
    args = ap.parse_args()
    corte = date.fromisoformat(args.corte).toordinal()
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos())
    resultado = calcular(por_liga, corte)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({"corte": args.corte, "generado": date.today().isoformat(), "ligas": resultado}, indent=1), encoding="utf-8")
    print(f"{len(resultado)} ligas escritas en {SALIDA.name}")
    for codigo, piezas in sorted(resultado.items())[:6]:
        print(codigo, {k: v["log_loss"] for k, v in piezas.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
