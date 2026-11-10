"""Verifica proveedores deportivos configurados sin revelar credenciales.

Uso en Windows:
    .venv_backend\\Scripts\\python.exe -m backend.scripts.verificar_fuentes

La comprobación de The Odds API consume una consulta de cuota; se incluye porque este
script se ejecuta de forma manual y deliberada. El scheduler diario mantiene la prueba
de bajo costo definida por ``source_health.verificar_fuentes``.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from backend.api.db.session import SessionLocal
from backend.api.services.source_health import verificar_fuentes


async def main() -> None:
    db = SessionLocal()
    try:
        async with httpx.AsyncClient() as client:
            resultados = await verificar_fuentes(db, client, incluir_cuota_costosa=True)
        # La salida sirve para QA y CI local. Nunca incluye URL con query string, headers o keys.
        seguro = [
            {clave: item.get(clave) for clave in (
                "fuente", "configurada", "saludable", "status_http", "latencia_ms",
                "cuota_restante", "detalle",
            )}
            for item in resultados
        ]
        print(json.dumps(seguro, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
