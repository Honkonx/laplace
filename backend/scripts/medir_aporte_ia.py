"""medir_aporte_ia.py — informe del aporte de la IA (python_baseline vs python_plus_ia del laboratorio). Solo lectura.

  python backend/scripts/medir_aporte_ia.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.services import aporte_ia  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        print(json.dumps(aporte_ia.desde_base(db), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
