"""Completa `analisis_modulos.pick_correcto` desde resultados ya verificados.

Por defecto solo informa lo que haria. Usar `--apply` para persistir el backfill derivado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.models.partidos import ResultadoPartido  # noqa: E402
from backend.api.models.predicciones import AnalisisModulo  # noqa: E402
from backend.api.services.resultados import _pick_acerto  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persiste los valores derivados")
    args = parser.parse_args()
    db = SessionLocal()
    actualizadas = 0
    try:
        resultados = {str(item.fixture_id): item for item in db.query(ResultadoPartido).all()}
        for modulo in db.query(AnalisisModulo).filter(AnalisisModulo.pick.isnot(None)).all():
            resultado = resultados.get(str(modulo.partido_id))
            if resultado is None:
                continue
            correcto = 1 if _pick_acerto(modulo.pick, resultado.ganador, resultado.local, resultado.visitante) else 0
            if modulo.pick_correcto != correcto:
                modulo.pick_correcto = correcto
                actualizadas += 1
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"module_rows_updated={actualizadas}")
        print(f"mode={'apply' if args.apply else 'dry-run'}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
