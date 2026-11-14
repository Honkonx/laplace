"""El hook que rechaza enlaces de sesión de Claude en commits, PR y releases (regla `commits-sin-enlaces-de-sesion-y-directos`)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "bloquear_enlaces_en_commits.py"
ENLACE = "https://claude" + ".ai/code/session_abcdef123"      # partido a propósito: el texto de este archivo no debe parecer un mensaje de commit con enlace


def _decision(comando: str) -> str:
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_input": {"command": comando}}), capture_output=True, text=True, encoding="utf-8", timeout=20)
    salida = json.loads(r.stdout or "{}")
    return (salida.get("hookSpecificOutput") or {}).get("permissionDecision", "permitido")


@pytest.mark.skipif(not HOOK.exists(), reason="los hooks de trabajo no se publican")
@pytest.mark.parametrize("comando, esperado", [
    (f'git commit -m "agrega X\n\nGenerated with [Claude Code]({ENLACE})"', "deny"),
    ('git commit -m "agrega X \U0001F916"', "deny"),
    (f'gh pr create --body "ver {ENLACE}"', "deny"),
    ('git tag -a v1 -m "https://claude.com/claude-code"', "deny"),
    ('git commit -m "agrega X\n\nCo-Authored-By: Claude <noreply@anthropic.com>"', "permitido"),
    ("grep claude.ai README.md", "permitido"),
    ('echo "claude.ai/code"', "permitido"),
])
def test_el_hook_solo_rechaza_los_enlaces_en_textos_que_se_publican(comando, esperado):
    assert _decision(comando) == esperado
