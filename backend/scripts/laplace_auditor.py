#!/usr/bin/env python3
"""backend/scripts/laplace_auditor.py — Auditoría real de winrate/calibración, contra la BD real.

Lee `analisis_comparativo`/`analisis_modulos` de `backend/db/bot_deportivo.db` (o el
`DATABASE_URL` real que esté configurado) y reporta, con HONESTIDAD sobre la validez
estadística (ver `.claude/rules/product-philosophy.md` y
`.claude/rules/empirical-verification-before-fix.md`):

  - Volumen real de filas por tabla.
  - Winrate real del pick final y de cada módulo (poisson/forma/h2h/odds/tabla/externo),
    marcado como "confiable" solo si el `n` real alcanza el umbral mínimo razonable
    (`calibracion.MUESTRA_MINIMA_WINRATE`) — nunca esconde el número, pero nunca lo presenta
    como válido si no lo es.
  - Brier score del módulo Poisson (calibración de probabilidades) si hay suficiente dato
    real para que tenga sentido calcularlo — nunca fuerza Platt scaling/isotonic regression,
    que necesitan muchísimo más volumen del que este proyecto tiene hoy.

Toda la lógica de cálculo vive en `backend/api/services/calibracion.py` — este script es solo
el I/O (leer BD real, imprimir, guardar JSON). El mismo cálculo lo expone
`GET /api/v1/admin/calibracion` para el dashboard de admin.

Es de SOLO LECTURA — nunca hace INSERT/UPDATE/DELETE contra la BD real.

Uso:
    .venv_backend/Scripts/python.exe backend/scripts/laplace_auditor.py

Guarda el reporte completo en backend/scripts/_reporte_calibracion.json (gitignored) y lo
imprime resumido en consola.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# La consola de Windows no siempre usa UTF-8 por defecto — mismo fix ya aplicado en
# verificar_calidad_datos_reales.py, encontrado real al correr scripts con caracteres fuera de
# cp1252 (✓, →, etc.).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.services.calibracion import calcular_metricas_calibracion  # noqa: E402


def _imprimir_bloque_winrate(titulo: str, bloque: dict) -> None:
    wr = f"{bloque['winrate_pct']}%" if bloque["winrate_pct"] is not None else "sin datos"
    confiable = "SI" if bloque["confiable"] else "NO"
    print(f"  {titulo}: {bloque['aciertos']}/{bloque['evaluados']} evaluados -> winrate={wr} "
          f"| confiable={confiable} (mínimo {bloque['muestra_minima_requerida']})")
    print(f"    -> {bloque['nota']}")


def main() -> None:
    print("=== Laplace Auditor — winrate/calibración real, contra la BD real ===")
    db = SessionLocal()
    try:
        reporte = calcular_metricas_calibracion(db)
    finally:
        db.close()

    vol = reporte["volumen_real"]
    print("\nVolumen real en BD:")
    print(f"  analisis_comparativo: {vol['total_filas_analisis_comparativo']} filas")
    print(f"  analisis_modulos:     {vol['total_filas_analisis_modulos']} filas")

    print("\n=== Winrate — pick final ===")
    _imprimir_bloque_winrate("pick_final", reporte["pick_final"])

    print(f"\n=== Winrate por módulo (fuente: {reporte['fuente_por_modulo']}) ===")
    for modulo, bloque in reporte["por_modulo"].items():
        _imprimir_bloque_winrate(modulo, bloque)

    brier = reporte["brier_score_poisson"]
    print("\n=== Brier score — módulo Poisson (calibración de probabilidades) ===")
    print(f"  muestra={brier['muestra']} brier_score={brier['brier_score']} "
          f"confiable={'SI' if brier['confiable'] else 'NO'} (mínimo {brier['muestra_minima_requerida']})")
    print(f"    -> {brier['nota']}")

    print("\n=== Veredicto honesto ===")
    print(f"  {reporte['advertencia_general']}")

    salida = {"generado_en": datetime.now().isoformat(), **reporte}
    out_path = Path(__file__).parent / "_reporte_calibracion.json"
    out_path.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReporte completo guardado en {out_path}")


if __name__ == "__main__":
    main()
