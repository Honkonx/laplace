#!/usr/bin/env bash
# Iniciar Laplace: avisa si falta algo clave, enciende el backend y el agente, y abre la web. Opciones: --lan | --sin-agente
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
for carpeta in runtime/venv .venv .venv_backend; do [ -z "$PY" ] && [ -x "$RAIZ/$carpeta/bin/python" ] && PY="$RAIZ/$carpeta/bin/python"; done
[ -n "$PY" ] || { echo "Laplace no está instalado en esta carpeta: ejecuta ./instalar.sh primero." >&2; exit 1; }
exec "$PY" "$RAIZ/install/comun/laplace.py" iniciar --avisar --abrir "$@"
