#!/usr/bin/env bash
# Control de Laplace: ./laplace.sh iniciar | configurar | detener | reiniciar | estado | logs | doctor | abrir
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
for carpeta in runtime/venv .venv .venv_backend; do [ -z "$PY" ] && [ -x "$RAIZ/$carpeta/bin/python" ] && PY="$RAIZ/$carpeta/bin/python"; done
[ -n "$PY" ] || { echo "Laplace no está instalado en esta carpeta: ejecuta ./instalar.sh primero." >&2; exit 1; }
exec "$PY" "$RAIZ/install/comun/laplace.py" "$@"
