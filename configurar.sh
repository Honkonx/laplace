#!/usr/bin/env bash
# Configurar Laplace: detecta y prueba tus APIs (datos, IA, Telegram) y deja poner o cambiar cada clave. Opciones: --estado | --probar | --solo ID
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
for carpeta in runtime/venv .venv .venv_backend; do [ -z "$PY" ] && [ -x "$RAIZ/$carpeta/bin/python" ] && PY="$RAIZ/$carpeta/bin/python"; done
[ -n "$PY" ] || { echo "Laplace no está instalado en esta carpeta: ejecuta ./instalar.sh primero." >&2; exit 1; }
exec "$PY" "$RAIZ/install/comun/configurar.py" "$@"
