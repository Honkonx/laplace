"""Crea o actualiza un administrador global local.

Uso:
    python backend/scripts/create_admin.py --username laplace-admin
    python backend/scripts/create_admin.py --username laplace-admin --password '...'
    python backend/scripts/create_admin.py --username admin --si-no-hay      (el instalador: solo crea uno si todavía no existe ninguno)

La contraseña generada solo se imprime una vez y nunca se guarda en el repositorio.
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.db.session import Base, SessionLocal, engine  # noqa: E402
from backend.api.models.usuarios import Usuario  # noqa: E402
from backend.api.services.auth_password import hashear_password  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear administrador global de Laplace")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default=None)
    parser.add_argument("--si-no-hay", action="store_true", help="no hace nada (ni cambia contraseñas) si ya existe algún administrador")
    args = parser.parse_args()
    password = args.password or "".join(secrets.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(24))
    Base.metadata.create_all(engine)
    if args.si_no_hay:
        with SessionLocal() as db:
            existente = db.query(Usuario).filter(Usuario.rol == "admin").first()
        if existente is not None:
            print(f"Ya hay un administrador ({existente.username}): no se cambia nada.")
            return
    with SessionLocal() as db:
        usuario = db.query(Usuario).filter(Usuario.username == args.username).first()
        if usuario is None:
            usuario = Usuario(device_id=f"admin:{args.username}", username=args.username, origen="web", plan="max", rol="admin", activo=1, creado_en="seed")
            db.add(usuario)
        usuario.password_hash = hashear_password(password)
        usuario.plan = "max"
        usuario.rol = "admin"
        usuario.activo = 1
        db.commit()
    print(f"Usuario administrador: {args.username}")
    print(f"Contraseña: {password}")
    print("Guárdala en un gestor seguro; no la agregues a .env.example, Git ni documentación pública. Se muestra una sola vez.")
    print("Entra en http://127.0.0.1:9001/entrar con ese usuario y abre «Administración» (Conexiones) para configurar tus APIs desde la web.")


if __name__ == "__main__":
    main()
