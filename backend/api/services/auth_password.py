"""services/auth_password.py — hashing de contraseñas (login usuario+clave de app/web).

Argon2id vía `argon2-cffi` — recomendación actual de OWASP para hashes nuevos (por encima de
bcrypt/PBKDF2). Sin dependencias de FastAPI acá a propósito: es lógica pura, testeable sin
levantar la app.
"""
from __future__ import annotations

import logging
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

log = logging.getLogger("laplace.auth_password")

_hasher = PasswordHasher()


def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(password: str, hash_: str) -> bool:
    try:
        return _hasher.verify(hash_, password)
    except VerifyMismatchError:
        return False
    except Exception as exc:
        log.warning("auth_password: hash ilegible, login negado: %s", exc)
        # Hash corrupto/formato viejo — nunca reventar el login por esto, solo negarlo.
        return False
