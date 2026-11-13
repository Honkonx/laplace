"""Mide si un rating inicial propio para un equipo que el modelo no conoce (recién llegado a la liga) mejora al modelo Laplace (MP-10), fuera de muestra y con la puerta común del plan.

Hoy un equipo sin historia en la liga entra con Elo 1500 (el valor por defecto de `EstadoLiga`), aunque la media de esa liga esté en otro valor. El candidato lo siembra en la MEDIA de la liga más un desfase δ (un recién
llegado suele ser más débil que la media): `elo_inicial = media_de_la_liga + δ`. Protocolo (δ elegido SIN mirar la prueba):
- DESARROLLO: modelo entrenado hasta 2022-07-01; los partidos hasta 2023-07-01 con al menos un equipo sin historia en su liga eligen el δ de la rejilla con menor log loss.
- PRUEBA: los partidos desde 2023-07-01 (que el desarrollo no vio), δ elegido frente al valor por defecto, sobre los mismos partidos y de forma pareada (puerta común: ≥ 0,001 de log loss, z ≥ 3, IC95 sin cero).
Uso: python backend/scripts/medir_equipo_nuevo_elo.py   (escribe backend/data/resultados/medicion_equipo_nuevo_elo.json)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import comparacion, datos, metricas  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_equipo_nuevo_elo.json"
CORTE_MODELO, CORTE_PRUEBA = date(2022, 7, 1).toordinal(), date(2023, 7, 1).toordinal()
REJILLA = (0.0, -25.0, -50.0, -75.0, -100.0, -150.0)   # desfase respecto de la media de la liga
N_BOOT = 200


def _sembrar(estado, equipo: str, delta: float) -> None:
    if equipo not in estado.elo and estado.elo:
        estado.elo[equipo] = sum(estado.elo.values()) / len(estado.elo) + delta


def recorrer() -> list[dict]:
    """Una fila por partido (desde el corte del modelo) con las probabilidades del valor por defecto y de cada δ, y si algún equipo no tenía historia en su liga."""
    partidos, _ = datos.cargar_partidos_con_vivo()
    por_liga = datos.agrupar_por_liga(partidos)
    art = ent.entrenar_jerarquico(por_liga, CORTE_MODELO, especializar=False, hiper=ent.HIPERS["g3"], con_goles=False)
    filas = []
    for codigo, info in art["ligas"].items():
        prueba = sorted((p for p in por_liga[codigo] if p["dia"] >= CORTE_MODELO), key=lambda x: (x["dia"], x["local"]))
        if not prueba:
            continue
        pesos = ent.pesos_de(art, codigo)
        base = ent.EstadoLiga.de_dict(info["estado"])
        estados = {d: ent.EstadoLiga.de_dict(info["estado"]) for d in REJILLA}
        for p in prueba:
            nuevo = base.n.get(p["local"], 0) == 0 or base.n.get(p["visitante"], 0) == 0
            probs = {}
            for d, est in estados.items():
                if d != 0.0:
                    _sembrar(est, p["local"], d)
                    _sembrar(est, p["visitante"], d)
                probs[d] = ent.probs_lineal(pesos, est.features(p["local"], p["visitante"]))
            filas.append({"liga": codigo, "dia": p["dia"], "r": p["resultado"], "nuevo": nuevo, "probs": probs})
            tiros = ent.tiros_de(p)
            base.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], tiros)
            for est in estados.values():
                est.actualizar(p["local"], p["visitante"], p["gl"], p["gv"], tiros)
    return filas


def _ll(filas: list[dict], d: float) -> float:
    return sum(metricas.log_loss(f["probs"][d], f["r"]) for f in filas) / len(filas)


def _contra_defecto(filas: list[dict], d: float) -> dict | None:
    if len(filas) < 30:
        return None
    r = comparacion.comparar_predicciones([(f["probs"][0.0], f["r"]) for f in filas], [(f["probs"][d], f["r"]) for f in filas], bloques=[f["dia"] // 7 for f in filas], n_boot=N_BOOT)
    return {"n": r["n"], "mejora_log_loss": round(r["diferencia_media"], 5), "ic95": [round(r["ic95"][0], 5), round(r["ic95"][1], 5)], "z": round(r["z"], 1), "cumple_la_puerta": bool(r["acepta"])}


def medir() -> dict:
    filas = recorrer()
    nuevos_dev = [f for f in filas if f["nuevo"] and f["dia"] < CORTE_PRUEBA]
    nuevos_prueba = [f for f in filas if f["nuevo"] and f["dia"] >= CORTE_PRUEBA]
    desarrollo = {str(d): round(_ll(nuevos_dev, d), 5) for d in REJILLA} if nuevos_dev else {}
    elegido = min((d for d in REJILLA if d != 0.0), key=lambda d: _ll(nuevos_dev, d)) if nuevos_dev else 0.0
    return {"corte_del_modelo": "2022-07-01", "prueba_desde": "2023-07-01", "partidos": len(filas), "con_equipo_sin_historia": {"desarrollo": len(nuevos_dev), "prueba": len(nuevos_prueba)},
            "log_loss_en_desarrollo_por_delta": desarrollo, "delta_elegido": elegido,
            "prueba_frente_al_valor_por_defecto": _contra_defecto(nuevos_prueba, elegido),
            "todos_los_partidos_de_prueba_frente_al_valor_por_defecto": _contra_defecto([f for f in filas if f["dia"] >= CORTE_PRUEBA], elegido)}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False))
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
