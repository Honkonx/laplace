"""Cambio controlado de claves y proveedores desde el panel de administración.

El navegador entrega el secreto una sola vez al backend autenticado. Nunca se guarda en la
base de datos, en auditoría ni en una respuesta: se escribe únicamente en `.env` local para que
el launcher lo cargue al reiniciar los procesos. Qué variables se pueden escribir lo decide el
registro único de conexiones (`core/conexiones.py`): una variable que no esté ahí no se escribe.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from backend.api.core import conexiones as cx

_PROVIDERS = {c.ia: (c.variable, c.modelo_variable) for c in cx.proveedores_ia()}
_MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,180}$")
# Caracteres de una API key real (base64/url-safe, prefijos tipo sk-/gsk_/AIza). Sin espacios,
# comillas, `$`, `#` ni saltos de línea: un valor así no puede abrir una línea nueva en `.env`.
_API_KEY = re.compile(r"^[A-Za-z0-9._~+/=:@-]{8,512}$")


def proveedores_permitidos() -> list[str]:
    return list(_PROVIDERS)


def guardar_proveedor_env(repo_root: Path, provider: str, api_key: str, model: str) -> dict:
    if provider not in _PROVIDERS:
        raise ValueError("Proveedor no permitido")
    if any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in api_key):
        raise ValueError("La clave no puede contener saltos de línea ni caracteres de control")
    if not _API_KEY.fullmatch(api_key.strip()):
        raise ValueError("La clave debe tener entre 8 y 512 caracteres sin espacios, comillas ni símbolos especiales")
    if not _MODEL.fullmatch(model.strip()):
        raise ValueError("El modelo contiene caracteres no permitidos")
    key_name, model_name = _PROVIDERS[provider]
    escribir_variables(repo_root, {key_name: api_key.strip(), model_name: model.strip()})
    return {"provider": provider, "model": model.strip(), "restart_required": True}


def escribir_variables(repo_root: Path, reemplazos: dict[str, str], solo_si_vacia: frozenset[str] = frozenset()) -> None:
    """Escribe variables en `.env` conservando el resto del archivo; escritura atómica y permisos 600. Los valores ya están validados por quien llama."""
    target = repo_root / ".env"
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        name = line.split("=", 1)[0].strip() if "=" in line else ""
        if name in reemplazos:
            actual = line.split("=", 1)[1].strip()
            output.append(f"{name}={actual}" if (name in solo_si_vacia and actual) else f"{name}={reemplazos[name]}")
            seen.add(name)
        else:
            output.append(line)
    output.extend(f"{name}={value}" for name, value in reemplazos.items() if name not in seen)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, target)


def _conexion(conexion_id: str) -> cx.Conexion:
    conexion = cx.por_id(conexion_id)
    if conexion is None:
        raise ValueError("Conexión no permitida")
    return conexion


def guardar_clave_conexion(repo_root: Path, conexion_id: str, clave: str) -> dict:
    """Guarda la clave de CUALQUIER conexión del registro (datos, IA o Telegram). Devuelve solo metadatos, nunca la clave."""
    conexion = _conexion(conexion_id)
    motivo = cx.formato_invalido(clave)
    if motivo:
        raise ValueError(motivo)
    reemplazos = {conexion.variable: clave.strip()}
    solo_si_vacia: set[str] = set()
    if conexion.modelo_variable and conexion.modelo_defecto:
        reemplazos[conexion.modelo_variable] = conexion.modelo_defecto
        solo_si_vacia.add(conexion.modelo_variable)  # no pisa un modelo que el administrador ya eligió
    escribir_variables(repo_root, reemplazos, frozenset(solo_si_vacia))
    return {"id": conexion.id, "variable": conexion.variable, "configurada": True, "restart_required": True}


def borrar_clave_conexion(repo_root: Path, conexion_id: str) -> dict:
    conexion = _conexion(conexion_id)
    escribir_variables(repo_root, {conexion.variable: ""})
    return {"id": conexion.id, "variable": conexion.variable, "configurada": False, "restart_required": True}


def guardar_orden_ia(repo_root: Path, orden: list[str]) -> dict:
    """Orden de la cascada de IA (los 4 roles `AI_ROUTING_*`). Solo ids de proveedores de IA del registro, sin repetir."""
    permitidos = set(_PROVIDERS)
    if not orden or len(set(orden)) != len(orden) or any(p not in permitidos for p in orden):
        raise ValueError("El orden debe listar proveedores de IA conocidos, sin repetir")
    escribir_variables(repo_root, {rol: ",".join(orden) for rol in cx.ROLES_IA})
    return {"orden": orden, "restart_required": True}
