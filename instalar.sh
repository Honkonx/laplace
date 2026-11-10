#!/usr/bin/env bash
# Instalador de Laplace para Linux/macOS/WSL. Detalle y opciones: ./instalar.sh --help
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install/linux/instalar.sh" "$@"
