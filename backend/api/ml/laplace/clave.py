"""clave.py — genera la clave del endpoint interno del modelo (`ML_API_KEY`) y la guarda en `.env` SIN mostrarla.

Un secreto guardado nunca se vuelve a mostrar (`secrets-never-revealed.md`): el comando solo dice si la creó. Si ya existe una clave no la pisa salvo `rotar=True`.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from backend.api.services.admin_env import escribir_variables

VARIABLE = "ML_API_KEY"


def _actual(repo_root: Path) -> str:
    env = repo_root / ".env"
    if not env.exists():
        return ""
    for linea in env.read_text(encoding="utf-8").splitlines():
        if linea.split("=", 1)[0].strip() == VARIABLE and "=" in linea:
            return linea.split("=", 1)[1].strip()
    return ""


def generar(repo_root: Path, rotar: bool = False) -> dict:
    """Crea `ML_API_KEY` en `.env`. Devuelve `{creada, motivo}`; nunca devuelve la clave."""
    if _actual(repo_root) and not rotar:
        return {"creada": False, "motivo": "ya hay una clave configurada (usa --rotar para reemplazarla)"}
    clave = "lap-ml-" + secrets.token_urlsafe(32)
    escribir_variables(repo_root, {VARIABLE: clave})
    return {"creada": True, "motivo": "clave nueva guardada en .env; reinicia el backend para que la use"}
