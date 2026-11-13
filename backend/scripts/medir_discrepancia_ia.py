"""medir_discrepancia_ia.py — ¿cuando la IA diverge del consenso, éste falla más? (MB-15). Solo lectura.

  python backend/scripts/medir_discrepancia_ia.py

Lee `analisis_comparativo` de la base configurada y muestra la tabla 2×2 con su veredicto. No cambia el ajuste de −8 de `consenso_ia`: eso solo se decide con ≥ 200 partidos por grupo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.services import discrepancia_ia  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        print(json.dumps(discrepancia_ia.desde_base(db), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
