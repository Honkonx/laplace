"""test_auth_password.py — hashing/verificación de contraseñas con Argon2id
(services/auth_password.py). test_auth.py ya cubre el camino feliz básico (hash != plano,
prefijo $argon2, verificar ida y vuelta) vía tests indirectos de los routers — acá se agregan
los casos no cubiertos: salteo real, hash corrupto, y valores límite (password vacía/unicode)."""
from __future__ import annotations

from backend.api.services.auth_password import hashear_password, verificar_password


def test_hashear_password_usa_salt_aleatorio_hashes_distintos_misma_password():
    """Argon2id incluye un salt aleatorio por hash — dos hashes de la MISMA password nunca
    deben ser iguales (si lo fueran, indicaría salt fijo/reusado — vulnerabilidad real)."""
    hash1 = hashear_password("mismaClave123")
    hash2 = hashear_password("mismaClave123")
    assert hash1 != hash2
    assert verificar_password("mismaClave123", hash1) is True
    assert verificar_password("mismaClave123", hash2) is True


def test_verificar_password_hash_corrupto_devuelve_false_no_lanza():
    """Caso límite: hash con formato inválido/corrupto (BD dañada, hash de otro esquema) —
    verificar_password debe negar el login, nunca reventar con una excepción no controlada."""
    assert verificar_password("cualquierClave", "no-es-un-hash-argon2-valido") is False
    assert verificar_password("cualquierClave", "") is False


def test_verificar_password_sensible_a_mayusculas():
    hash_ = hashear_password("ClaveConMayusculas1")
    assert verificar_password("claveconmayusculas1", hash_) is False
    assert verificar_password("ClaveConMayusculas1", hash_) is True


def test_hashear_y_verificar_password_con_caracteres_unicode():
    """Passwords con acentos/emoji deben poder hashearse y verificarse igual que ASCII puro."""
    password = "cóntraseña日本語🎯"
    hash_ = hashear_password(password)
    assert verificar_password(password, hash_) is True
    assert verificar_password("cóntraseña日本語", hash_) is False


def test_hashear_password_vacia_no_lanza_y_es_verificable():
    hash_ = hashear_password("")
    assert hash_.startswith("$argon2")
    assert verificar_password("", hash_) is True
    assert verificar_password("no-vacia", hash_) is False
