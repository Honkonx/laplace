"""Mide si dar más peso a los partidos recientes al entrenar mejora al modelo (MP-3), fuera de muestra y con la puerta común del plan.

Protocolo (hiperparámetros elegidos SIN mirar la prueba):
- DESARROLLO: se entrena con lo anterior a 2022-07-01 y se evalúa hasta 2023-07-01, para cada semivida candidata frente a la variante g3 sin recencia (`ml/laplace/versiones.py`, mismos partidos, pareado). Se elige la de mayor mejora.
- PRUEBA: con el corte 2023-07-01 y todo lo posterior (que el desarrollo no vio), la semivida elegida frente a g3. Esa es la cifra que se reporta; la puerta común exige ≥ 0,001 de log loss, z ≥ 3 e IC95 sin cero.
Uso: python backend/scripts/medir_recencia.py   (escribe backend/data/resultados/medicion_recencia.json)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from backend.api.ml import datos  # noqa: E402
from backend.api.ml.laplace import entrenamiento as ent, versiones  # noqa: E402

SALIDA = RAIZ / "backend" / "data" / "resultados" / "medicion_recencia.json"
SEMIVIDAS = (365, 730, 1460)  # días
CORTE_DESARROLLO, CORTE_PRUEBA = date(2022, 7, 1).toordinal(), date(2023, 7, 1).toordinal()
N_BOOT = 200


def _resumen(r: dict) -> dict | None:
    g = r.get("global")
    if not g:
        return None
    return {"n": g["n"], "mejora_log_loss": round(g["diferencia_media"], 5), "ic95": [round(g["ic95"][0], 5), round(g["ic95"][1], 5)], "z": round(g["z"], 1), "cumple_la_puerta": bool(g["acepta"])}


def medir() -> dict:
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    base = ent.HIPER_DEFECTO
    desarrollo = {}
    for v in SEMIVIDAS:
        desarrollo[v] = _resumen(versiones.comparar_versiones(por_liga, CORTE_DESARROLLO, base, {**base, "recencia_dias": v}, hasta=CORTE_PRUEBA, n_boot=N_BOOT))
    elegida = max((v for v in SEMIVIDAS if desarrollo[v]), key=lambda v: desarrollo[v]["mejora_log_loss"])
    prueba = _resumen(versiones.comparar_versiones(por_liga, CORTE_PRUEBA, base, {**base, "recencia_dias": elegida}, n_boot=N_BOOT))
    return {"referencia": "g3 sin recencia; positiva = la candidata con recencia es mejor", "desarrollo": {"corte": "2022-07-01", "hasta": "2023-07-01", "por_semivida_dias": desarrollo}, "semivida_elegida_dias": elegida,
            "prueba": {"corte": "2023-07-01", **(prueba or {})}}


def main() -> int:
    informe = medir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print("desarrollo:", json.dumps(informe["desarrollo"]["por_semivida_dias"], ensure_ascii=False))
    print("elegida:", informe["semivida_elegida_dias"], "· prueba:", json.dumps(informe["prueba"], ensure_ascii=False))
    print(f"escrito en {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
