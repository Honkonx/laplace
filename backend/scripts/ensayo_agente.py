"""Ensayo del agente sin Telegram: corre una conversación típica (seguir un equipo, avisos, perfil, pronóstico, perfil de equipo, jerga y fechas) y muestra cada respuesta, para ver el comportamiento antes de probarlo en Telegram.

Trabaja sobre una COPIA de la base (en una carpeta temporal): no guarda nada en la real ni envía nada por Telegram. Si el bot deportivo (puerto 9001) no está encendido, el agente responde con lo que tiene (el modelo en proceso).
Uso: python backend/scripts/ensayo_agente.py [--usuario 12345] [--ia] [--base ruta.db]
  --usuario  el id con el que se conversa (por defecto uno de prueba); --ia  permite la IA en cada turno (necesita un proveedor configurado); --base  copia otra base en vez de la real.
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

GUION = (
    ("saludo", "hola"),
    ("seguir (pide consentimiento)", "sigue al Real Madrid"),
    ("consentimiento", "acepto"),
    ("seguir un equipo", "sigue al Real Madrid"),
    ("seguir una liga", "sigue la Premier League"),
    ("qué sigo", "que sigo"),
    ("activar avisos", "activa los avisos"),
    ("perfil: zona horaria", "estoy en Chile"),
    ("perfil: estilo", "responde corto"),
    ("perfil: mercados", "me interesan goles y ambos marcan"),
    ("ver el perfil", "mi perfil"),
    ("pronóstico de un equipo seguido (sin preguntar la vía)", "quien se lleva el Madrid vs Barça"),
    ("pronóstico de un partido ajeno (pregunta la vía)", "quien gana Boca vs River"),
    ("fecha relativa", "partidos del sábado"),
    ("jerga", "como pinta el finde"),
    ("tabla propia de una liga", "tabla de la premier"),
    ("retroalimentación de estilo", "más corto"),
    ("perfil de un equipo con la memoria del modelo", "perfil de Boca Juniors"),
    ("cultura de fútbol (solo con IA)", "explicame que es el var"),
    ("fuera del fútbol", "dame una receta de empanadas"),
    ("dejar de seguir", "deja de seguir al Real Madrid"),
    ("borrar el perfil", "borra mi perfil"),
)


def copiar_base(origen: Path, destino: Path) -> None:
    a = sqlite3.connect(f"file:{origen.as_posix()}?mode=ro", uri=True)
    b = sqlite3.connect(destino)
    a.backup(b)
    b.close()
    a.close()


async def conversar(db, usuario: str, usar_ia: bool) -> None:
    from backend.api.services import agent_runtime

    for titulo, texto in GUION:
        r = await agent_runtime.procesar_mensaje(db, usuario, texto, None, "ensayo", usar_ia, False)
        print(f"\n── {titulo}\n   tú:      {texto}\n   agente:  {r['respuesta'].strip()[:600]}\n   [{r['herramienta'] or 'sin herramienta'} · {r['modo']}]")


def main() -> int:
    import logging

    logging.disable(logging.ERROR)  # el bot deportivo apagado es un caso normal del ensayo: el agente lo dice en su respuesta, no hace falta el rastro
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--usuario", default="telegram:900000001")
    ap.add_argument("--ia", action="store_true")
    ap.add_argument("--base", default=None)
    args = ap.parse_args()
    from backend.api.core.config import settings

    origen = Path(args.base) if args.base else Path(settings.DATABASE_URL.replace("sqlite:///", ""))
    if not origen.exists():
        print(f"No encuentro la base en {origen}. Indica otra con --base.")
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # en Windows el archivo puede seguir abierto un instante: no es un fallo del ensayo
        copia = Path(tmp) / "ensayo.db"
        copiar_base(origen, copia)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        motor = create_engine(f"sqlite:///{copia.as_posix()}", connect_args={"check_same_thread": False})
        sesion = sessionmaker(bind=motor)
        from alembic import command
        from alembic.config import Config

        settings.DATABASE_URL = f"sqlite:///{copia.as_posix()}"
        command.upgrade(Config(str(RAIZ / "backend" / "api" / "alembic.ini")), "head")  # lleva la COPIA al esquema actual (la real no se toca)
        print(f"Ensayo sobre una copia de {origen.name}; usuario {args.usuario}; IA {'activada' if args.ia else 'apagada'}.")
        with sesion() as db:
            asyncio.run(conversar(db, args.usuario, args.ia))
        motor.dispose()
    print("\nListo. Nada se guardó en la base real ni se envió por Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
