"""Mide, fuera de muestra, los mercados de goles del modelo Laplace (más de 2,5 y ambos marcan) frente a la tasa base y, donde hay cuotas, frente al mercado (MP-11).

Protocolo del reentreno: se entrena con todo lo anterior al corte (2023-07-01 por defecto, con calibración de goles) y se recorre la prueba partido a partido avanzando el estado, sin ver el futuro.
- Más de 2,5: log loss del modelo, de la tasa base de la liga (la del entrenamiento) y del mercado (cuotas promedio de más/menos sin margen, proporcional), de apertura y de cierre; diferencias pareadas con IC95.
- Ambos marcan: solo contra la tasa base (el maestro no trae cuotas de ese mercado).
- Calibración por tramos de probabilidad y por si el mercado figura entre los `validados` del modelo (los que superaron a la tasa base fuera de muestra: los únicos que el producto muestra).
Uso: python backend/scripts/medir_mercados_de_goles.py [--corte AAAA-MM-DD]   (escribe backend/data/resultados/medicion_mercados_de_goles.json)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, goles  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_mercados_de_goles.json"
EPS = 1e-9
N_BOOT = 200


def _ll(p: float, y: int) -> float:
    return -math.log(max(p if y else 1 - p, EPS))


def sin_margen_2(mas: float, menos: float) -> float:
    """Probabilidad implícita de «más» sin margen (proporcional)."""
    a, b = 1 / mas, 1 / menos
    return a / (a + b)


def filas_de_prueba(corte: int) -> tuple[list[dict], list[str]]:
    partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    art = ent.entrenar_jerarquico(por_liga, corte, especializar=False, hiper=ent.HIPERS["g3"], con_goles=True)
    calib = art.get("goles")
    validados = [m for m in goles.MERCADOS if (calib or {}).get("util", {}).get(m)]
    filas = []
    for codigo, info in art["ligas"].items():
        tasas = info.get("tasas_goles")
        prueba = sorted((p for p in por_liga[codigo] if p["dia"] >= corte), key=lambda x: (x["dia"], x["local"]))
        if not prueba or not tasas or not calib:
            continue
        estado = ent.EstadoLiga.de_dict(info["estado"])
        for p in prueba:
            r = ent.predecir_liga(art, codigo, p["local"], p["visitante"], estado)
            s = goles.pronosticar(*r["lambdas"], r["medias"], calib, tasas, p1x2=r["p1x2"])
            total = p["gl"] + p["gv"]
            fila = {"liga": codigo, "dia": p["dia"], "o25": (s["over_under"]["2.5"]["mas"], int(total >= 3), tasas["o25"]), "btts": (s["btts"]["si"], int(p["gl"] > 0 and p["gv"] > 0), tasas["btts"]),
                    "m_ap": sin_margen_2(*p["o25"]) if p.get("o25") else None, "m_ci": sin_margen_2(*p["o25_cierre"]) if p.get("o25_cierre") else None}
            filas.append(fila)
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    return filas, validados


def _comparar(filas: list[dict], mercado: str, ref) -> dict | None:
    """Modelo frente a `ref(fila)` (probabilidad de «sí») sobre los mismos partidos: positiva = el modelo es mejor."""
    base = [f for f in filas if ref(f) is not None]
    if len(base) < 100:
        return None
    r = comparacion.comparar_perdidas([_ll(ref(f), f[mercado][1]) for f in base], [_ll(f[mercado][0], f[mercado][1]) for f in base], bloques=[f["dia"] // 7 for f in base], n_boot=N_BOOT)
    return {"n": r["n"], "mejora_log_loss": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1),
            "log_loss_modelo": round(r["perdida_b"], 5), "log_loss_referencia": round(r["perdida_a"], 5)}


def _calibracion(filas: list[dict], mercado: str) -> list[dict]:
    tramos: dict[int, list[tuple[float, int]]] = {}
    for f in filas:
        p, y, _ = f[mercado]
        tramos.setdefault(min(int(p * 10), 9), []).append((p, y))
    return [{"tramo": f"{k / 10:.1f}-{(k + 1) / 10:.1f}", "n": len(v), "prob_media": round(sum(p for p, _ in v) / len(v), 4), "frecuencia": round(sum(y for _, y in v) / len(v), 4)} for k, v in sorted(tramos.items())]


def medir(corte: int) -> dict:
    filas, validados = filas_de_prueba(corte)
    con_mercado = [f for f in filas if f["m_ci"] is not None]
    informe = {"corte": date.fromordinal(corte).isoformat(), "partidos_prueba": len(filas), "con_cuotas_de_mas_menos_2_5_de_cierre": len(con_mercado), "mercados_validados_por_el_modelo": validados,
               "mas_2_5": {"vs_tasa_base": _comparar(filas, "o25", lambda f: f["o25"][2]), "vs_apertura": _comparar(filas, "o25", lambda f: f["m_ap"]), "vs_cierre": _comparar(filas, "o25", lambda f: f["m_ci"]),
                           "calibracion": _calibracion(filas, "o25")},
               "ambos_marcan": {"vs_tasa_base": _comparar(filas, "btts", lambda f: f["btts"][2]), "calibracion": _calibracion(filas, "btts"),
                                "nota": "sin cuotas de este mercado en el maestro: solo se compara con la tasa base"}}
    por_liga = {}
    for codigo in sorted({f["liga"] for f in con_mercado}):
        g = [f for f in con_mercado if f["liga"] == codigo]
        if len(g) >= 300:
            por_liga[codigo] = {"n": len(g), "o25_vs_cierre": _comparar(g, "o25", lambda f: f["m_ci"])}
    informe["mas_2_5_por_liga_vs_cierre"] = por_liga
    return informe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corte", default="2023-07-01", help="fecha de corte del entrenamiento (AAAA-MM-DD)")
    args = ap.parse_args()
    informe = medir(date.fromisoformat(args.corte).toordinal())
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"partidos {informe['partidos_prueba']} · con cuotas de cierre {informe['con_cuotas_de_mas_menos_2_5_de_cierre']} · validados {informe['mercados_validados_por_el_modelo']}")
    for k in ("vs_tasa_base", "vs_apertura", "vs_cierre"):
        print("más 2,5", k, informe["mas_2_5"][k])
    print("ambos marcan vs tasa base", informe["ambos_marcan"]["vs_tasa_base"])
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
