"""Mide el modelo Laplace por segmentos (MP-15) y frente a la línea de cierre del mercado (MP-6), fuera de muestra y sin mirar el futuro.

Protocolo (el mismo del reentreno): se entrena con todo lo anterior al corte (2023-07-01 por defecto) y se recorre la prueba partido a partido avanzando el estado, con los pesos universales de la variante g3.
- MP-6 «valor de cierre»: log loss del modelo, de la apertura y del cierre (cuotas sin margen, proporcional); diferencia pareada con IC95; y si las desviaciones del modelo respecto de la apertura apuntan hacia donde
  el mercado se movió después (correlación y acierto de dirección). Es una métrica de CALIDAD del modelo, no de apuestas.
- MP-15 segmentos: por liga, tramo de probabilidad del favorito, tramo de la probabilidad de local del cierre y temporada, cada uno con n, log loss, RPS, calibración del favorito (probabilidad media frente a
  acierto) y diferencia pareada con la tasa base y el cierre. Un segmento con menos de `MIN_N` partidos se informa pero no se interpreta.
Uso: python backend/scripts/medir_modelo_segmentos_y_cierre.py [--corte AAAA-MM-DD]   (escribe backend/data/resultados/medicion_segmentos_y_cierre.json)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, datos, metricas  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_segmentos_y_cierre.json"
MIN_N = 200          # por debajo, el segmento no se interpreta
MIN_N_LIGA = 300
N_BOOT = 200


def filas_de_prueba(corte: int) -> list[dict]:
    """Una fila por partido de la prueba: probabilidades del modelo, tasa base, apertura y cierre sin margen (None si no hay cuotas) y el resultado."""
    partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    art = ent.entrenar_jerarquico(por_liga, corte, especializar=False, hiper=ent.HIPERS["g3"], con_goles=False)
    filas = []
    for codigo, info in art["ligas"].items():
        prueba = sorted((p for p in por_liga[codigo] if p["dia"] >= corte), key=lambda x: (x["dia"], x["local"]))
        if not prueba:
            continue
        estado, pesos = ent.EstadoLiga.de_dict(info["estado"]), ent.pesos_de(art, codigo)
        for p in prueba:
            ap = ent.sin_margen(p["ap_prom"]) if isinstance(p.get("ap_prom"), tuple) else None
            ci = ent.sin_margen(p["ci_prom"]) if isinstance(p.get("ci_prom"), tuple) else None
            filas.append({"liga": codigo, "temporada": p["temporada"], "dia": p["dia"], "r": p["resultado"], "p": ent.probs_lineal(pesos, estado.features(p["local"], p["visitante"])),
                          "tb": tuple(info["tasa_base"]), "ap": ap, "ci": ci})
            estado.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], ent.tiros_de(p))
    return filas


def _resumen(filas: list[dict]) -> dict:
    n = len(filas)
    acierto = sum(1 for f in filas if "HDA"[f["p"].index(max(f["p"]))] == f["r"]) / n
    return {"n": n, "log_loss": round(sum(metricas.log_loss(f["p"], f["r"]) for f in filas) / n, 5), "rps": round(sum(metricas.rps(f["p"], f["r"]) for f in filas) / n, 5),
            "prob_media_del_favorito": round(sum(max(f["p"]) for f in filas) / n, 4), "acierto_del_favorito": round(acierto, 4)}


def _contra(filas: list[dict], ref: str) -> dict | None:
    """Modelo frente a la referencia `ref` (`tb` o `ci`) sobre los mismos partidos: positiva = el modelo es mejor."""
    base = [f for f in filas if f.get(ref) is not None]
    if len(base) < 30:
        return None
    r = comparacion.comparar_predicciones([(f[ref], f["r"]) for f in base], [(f["p"], f["r"]) for f in base], bloques=[f["dia"] // 7 for f in base], n_boot=N_BOOT)
    return {"n": r["n"], "mejora_log_loss": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1)}


def _segmento(filas: list[dict], minimo: int) -> dict:
    s = _resumen(filas)
    s["suficiente"] = len(filas) >= minimo
    if s["suficiente"]:
        s["vs_tasa_base"], s["vs_cierre"] = _contra(filas, "tb"), _contra(filas, "ci")
    return s


def _tramo_decimal(x: float, minimo: float, maximo: float) -> str:
    base = min(max(math.floor(x * 10) / 10, minimo), maximo)
    return f"{base:.1f}-{base + 0.1:.1f}"


def _agrupar(filas: list[dict], clave, minimo: int) -> list[dict]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for f in filas:
        k = clave(f)
        if k is not None:
            grupos[k].append(f)
    return [{"clave": k, **_segmento(g, minimo)} for k, g in sorted(grupos.items())]


def valor_de_cierre(filas: list[dict]) -> dict:
    """MP-6. Calidad frente a la apertura y el cierre, y si el modelo se anticipa al movimiento de la línea."""
    con_cuotas = [f for f in filas if f["ap"] is not None and f["ci"] is not None]
    n = len(con_cuotas)
    if n < 100:
        return {"n": n, "nota": "sin cuotas suficientes"}

    def ll(clave):
        return round(sum(metricas.log_loss(f[clave], f["r"]) for f in con_cuotas) / n, 5)

    pares = [(m - a, c - a) for f in con_cuotas for m, a, c in zip(f["p"], f["ap"], f["ci"], strict=True)]
    mx, my = sum(x for x, _ in pares) / len(pares), sum(y for _, y in pares) / len(pares)
    cov = sum((x - mx) * (y - my) for x, y in pares)
    corr = cov / math.sqrt(sum((x - mx) ** 2 for x, _ in pares) * sum((y - my) ** 2 for _, y in pares))
    aciertos = total = 0
    for f in con_cuotas:
        dm = [m - a for m, a in zip(f["p"], f["ap"], strict=True)]
        dc = [c - a for c, a in zip(f["ci"], f["ap"], strict=True)]
        k = max(range(3), key=lambda i: abs(dm[i]))
        if dc[k] != 0 and dm[k] != 0:
            total += 1
            aciertos += (dm[k] > 0) == (dc[k] > 0)
    p = aciertos / total if total else 0.0
    ee = math.sqrt(p * (1 - p) / total) if total else 0.0
    return {"n": n, "log_loss": {"modelo": ll("p"), "apertura": ll("ap"), "cierre": ll("ci"), "tasa_base": ll("tb")},
            "modelo_vs_apertura": _contra([{**f, "ap": f["ap"]} for f in con_cuotas], "ap"), "modelo_vs_cierre": _contra(con_cuotas, "ci"),
            "anticipacion_al_movimiento": {"correlacion_desviacion_modelo_vs_movimiento": round(corr, 4), "pares": len(pares),
                                           "acierto_de_direccion": round(p, 4), "ic95_direccion": [round(p - 1.96 * ee, 4), round(p + 1.96 * ee, 4)], "casos": total,
                                           "lectura": "0,5 = sin información; por encima, las desviaciones del modelo respecto de la apertura apuntan hacia donde el mercado se movió después"},
            "por_liga": [{"liga": k, "n": len(g), "vs_cierre": _contra(g, "ci")} for k, g in sorted(((k, [f for f in con_cuotas if f["liga"] == k]) for k in {f["liga"] for f in con_cuotas}), key=lambda kv: -len(kv[1])) if len(g) >= MIN_N_LIGA][:25]}


def medir(corte: int) -> dict:
    filas = filas_de_prueba(corte)
    return {"corte": date.fromordinal(corte).isoformat(), "partidos_prueba": len(filas), "con_cuotas_de_cierre": sum(1 for f in filas if f["ci"] is not None), "min_n_segmento": MIN_N,
            "global": _segmento(filas, MIN_N), "valor_de_cierre": valor_de_cierre(filas),
            "por_liga": _agrupar(filas, lambda f: f["liga"], MIN_N_LIGA),
            "por_tramo_del_favorito": _agrupar(filas, lambda f: _tramo_decimal(max(f["p"]), 0.3, 0.8), MIN_N),
            "por_tramo_de_local_en_el_cierre": _agrupar(filas, lambda f: _tramo_decimal(f["ci"][0], 0.1, 0.8) if f["ci"] else None, MIN_N),
            "por_temporada": _agrupar(filas, lambda f: f["temporada"], MIN_N)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corte", default="2023-07-01", help="fecha de corte del entrenamiento (AAAA-MM-DD)")
    args = ap.parse_args()
    informe = medir(date.fromisoformat(args.corte).toordinal())
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    g, v = informe["global"], informe["valor_de_cierre"]
    print(f"partidos de prueba {informe['partidos_prueba']} · con cierre {informe['con_cuotas_de_cierre']} · log loss {g['log_loss']} · vs tasa base {g.get('vs_tasa_base')} · vs cierre {g.get('vs_cierre')}")
    print("valor de cierre:", json.dumps(v.get("anticipacion_al_movimiento"), ensure_ascii=False), v.get("log_loss"))
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
