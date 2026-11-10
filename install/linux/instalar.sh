#!/usr/bin/env bash
# Instalador de Laplace para Linux (y macOS / WSL): detecta, descarga, instala y configura todo lo necesario SIN tocar el Python,
# el Node ni el PATH del sistema, y SIN permisos de administrador.
#
#   ./instalar.sh                    instalación normal (Python propio + dependencias + .env + base de datos; compila la web si hace falta) y al final
#                                    ofrece configurar tus conexiones (APIs) y crear tu administrador de la web
#   ./instalar.sh --sin-asistente    no pregunta nada (solo crea el .env con los secretos propios); luego: ./configurar.sh
#   ./instalar.sh --reconfigurar     al final abre directamente configurar (cambiar claves); no toca los secretos propios
#   ./instalar.sh --con-node         instala también Node + pnpm propios y recompila la web (desarrollo)
#   ./instalar.sh --con-ml           instala numpy/scipy/scikit-learn (reajuste semanal del modelo y evaluaciones)
#   ./instalar.sh --rehacer          borra y recrea el entorno de Python (runtime/venv)
#
# Todo vive dentro de esta carpeta (runtime/). Cada descarga se verifica contra una huella SHA-256 fijada en install/runtime-pins.json
# (uv: GitHub de Astral; Node: nodejs.org) y se aborta si no coincide. Es repetible: correrlo otra vez solo completa lo que falte.
# Requiere: bash, curl o wget, tar, gzip y sha256sum (o shasum). Distribuciones con glibc (Debian, Ubuntu, Fedora, Arch…); Alpine (musl)
# no está soportada porque Node no publica binarios oficiales para musl.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="$RAIZ/runtime"
CACHE="$RUNTIME/cache"
VENV="$RUNTIME/venv"
PYTHON_VENV="$VENV/bin/python"
PINES="$RAIZ/install/runtime-pins.json"
cd "$RAIZ"

SIN_ASISTENTE=0; RECONFIGURAR=0; CON_NODE=0; CON_ML=0; REHACER=0
for arg in "$@"; do
  case "$arg" in
    --sin-asistente) SIN_ASISTENTE=1 ;;
    --reconfigurar) RECONFIGURAR=1 ;;
    --con-node) CON_NODE=1 ;;
    --con-ml) CON_ML=1 ;;
    --rehacer) REHACER=1 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $arg (usa --help)" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then V=$'\033[32m'; A=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else V=""; A=""; R=""; C=""; N=""; fi
paso()  { printf '\n%s==> %s%s\n' "$C" "$1" "$N"; }
ok()    { printf '    %s[OK]%s %s\n' "$V" "$N" "$1"; }
aviso() { printf '    %s[AVISO]%s %s\n' "$A" "$N" "$1"; }
fallo() { printf '    %s[FALLO]%s %s\n' "$R" "$N" "$1" >&2; exit 1; }

# --- lectura de runtime-pins.json sin depender de jq ni de Python (todavía no hay Python propio) -------------------------------
pin_simple() { sed -nE "s/^  \"$1\": *\"([^\"]+)\".*/\1/p" "$PINES" | head -n1; }
pin_version() { awk -v sec="$1" '$0 ~ "\"" sec "\": *\\{" {d=1; next} d && /"version":/ {gsub(/.*"version": *"|".*/, ""); print; exit}' "$PINES"; }
pin_url() { awk -v sec="$1" '$0 ~ "\"" sec "\": *\\{" {d=1; next} d && /"url":/ {gsub(/.*"url": *"|",?$/, ""); print; exit}' "$PINES"; }
pin_plataforma() { # seccion plataforma campo
  awk -v sec="$1" -v plat="$2" '$0 ~ "\"" sec "\": *\\{" {d=1; next} d && $0 ~ "\"" plat "\":" {print; exit}' "$PINES" \
    | sed -nE "s/.*\"$3\": *\"([^\"]+)\".*/\1/p"
}

# --- sistema ----------------------------------------------------------------------------------------------------------------
sistema() {
  local so arq
  case "$(uname -s)" in Linux) so=linux ;; Darwin) so=macos ;; *) fallo "Sistema no soportado: $(uname -s) (usa Windows con instalar.bat)" ;; esac
  case "$(uname -m)" in x86_64|amd64) arq=x64 ;; aarch64|arm64) arq=arm64 ;; *) fallo "Arquitectura no soportada: $(uname -m)" ;; esac
  if [ "$so" = linux ] && { ldd --version 2>&1 | grep -qi musl; }; then
    fallo "Esta distribución usa musl (p. ej. Alpine): Node no publica binarios oficiales para ella. Usa Debian, Ubuntu, Fedora, Arch u otra con glibc."
  fi
  echo "$so-$arq"
}

descargar() { # url destino
  if command -v curl >/dev/null 2>&1; then curl -fL --retry 3 --retry-delay 2 -sS -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q --tries=3 -O "$2" "$1"
  else fallo "Falta curl o wget para descargar (instala uno con el gestor de tu distribución)."; fi
}

huella() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

descargar_verificado() { # url destino sha256
  mkdir -p "$(dirname "$2")"
  if [ -f "$2" ] && [ "$(huella "$2")" = "$3" ]; then ok "ya descargado y verificado: $(basename "$2")"; return; fi
  rm -f "$2"
  echo "    descargando $1"
  descargar "$1" "$2" || fallo "No se pudo descargar $1 (¿hay conexión a internet?)"
  local real; real="$(huella "$2")"
  if [ "$real" != "$3" ]; then
    rm -f "$2"
    fallo "La huella SHA-256 NO coincide para $(basename "$2").
    esperada: $3
    recibida: $real
    Se canceló la instalación por seguridad (no se extrajo nada)."
  fi
  ok "huella SHA-256 verificada: $(basename "$2")"
}

# ---------------------------------------------------------------------------------------------------------------------------
paso "Revisando el equipo"
PLATAFORMA="$(sistema)"
ok "sistema: $PLATAFORMA"
for herramienta in tar gzip; do command -v "$herramienta" >/dev/null 2>&1 || fallo "Falta '$herramienta'."; done
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || fallo "Falta sha256sum (o shasum)."
LIBRE_KB="$(df -Pk "$RAIZ" | awk 'NR==2 {print $4}')"
[ "${LIBRE_KB:-0}" -ge 2097152 ] || fallo "Poco espacio libre ($((LIBRE_KB / 1024)) MB). Se necesitan al menos 2 GB."
ok "espacio libre: $((LIBRE_KB / 1024)) MB"
for puerto in 9001 9100; do
  if (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$puerto "); then aviso "el puerto $puerto ya está en uso (si es otra instancia de Laplace, es normal)"; fi
done
[ -f "$PINES" ] || fallo "Falta $PINES"

# ---------------------------------------------------------------------------------------------------------------------------
UV_VERSION="$(pin_version uv)"
paso "uv $UV_VERSION (instala Python sin tocar el del sistema)"
UV_DIR="$RUNTIME/uv"; UV="$UV_DIR/uv"
ARCHIVO_UV="$(pin_plataforma uv "$PLATAFORMA" archivo)"; SHA_UV="$(pin_plataforma uv "$PLATAFORMA" sha256)"
[ -n "$ARCHIVO_UV" ] || fallo "No hay uv fijado para $PLATAFORMA en runtime-pins.json"
if [ -x "$UV" ] && "$UV" --version 2>/dev/null | grep -q "$UV_VERSION"; then
  ok "uv $UV_VERSION ya instalado"
else
  URL_UV="$(pin_url uv | sed "s/{version}/$UV_VERSION/; s/{archivo}/$ARCHIVO_UV/")"
  descargar_verificado "$URL_UV" "$CACHE/$ARCHIVO_UV" "$SHA_UV"
  rm -rf "$RUNTIME/uv-tmp"; mkdir -p "$RUNTIME/uv-tmp" "$UV_DIR"
  tar -xzf "$CACHE/$ARCHIVO_UV" -C "$RUNTIME/uv-tmp"
  cp -f "$(find "$RUNTIME/uv-tmp" -type f -name uv | head -n1)" "$UV"
  chmod +x "$UV"; rm -rf "$RUNTIME/uv-tmp"
  ok "$("$UV" --version)"
fi
# Aislamiento: Python gestionado dentro de runtime/, nunca el del sistema; caché dentro de runtime/.
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python" UV_CACHE_DIR="$CACHE/uv" UV_PYTHON_PREFERENCE=only-managed UV_NO_CONFIG=1

# ---------------------------------------------------------------------------------------------------------------------------
PY_VERSION="$(pin_simple python)"
paso "Python $PY_VERSION propio"
[ "$REHACER" = 1 ] && [ -d "$VENV" ] && { rm -rf "$VENV"; ok "entorno anterior eliminado"; }
"$UV" python install "$PY_VERSION" || fallo "No se pudo instalar Python (¿hay conexión a internet?)"
[ -x "$PYTHON_VENV" ] || "$UV" venv "$VENV" --python "$PY_VERSION" || fallo "No se pudo crear el entorno de Python"
ok "entorno: $VENV ($("$PYTHON_VENV" --version))"

paso "Dependencias de Python"
REQUISITOS=(-r backend/requirements.txt)
[ "$CON_ML" = 1 ] && REQUISITOS+=(-r backend/requirements-ml.txt)
"$UV" pip install --python "$PYTHON_VENV" "${REQUISITOS[@]}" || fallo "Falló la instalación de dependencias"
ok "dependencias instaladas"

# ---------------------------------------------------------------------------------------------------------------------------
if [ "$CON_NODE" = 1 ] || [ ! -f "$RAIZ/frontend/dist/index.html" ]; then
  NODE_VERSION="$(pin_version node)"
  paso "Node $NODE_VERSION y pnpm $(pin_simple pnpm) propios (para compilar la web)"
  NODE_DIR="$RUNTIME/node"
  ARCHIVO_NODE="$(pin_plataforma node "$PLATAFORMA" archivo)"; SHA_NODE="$(pin_plataforma node "$PLATAFORMA" sha256)"
  [ -n "$ARCHIVO_NODE" ] || fallo "No hay Node fijado para $PLATAFORMA en runtime-pins.json"
  if [ ! -x "$NODE_DIR/bin/node" ]; then
    URL_NODE="$(pin_url node | sed "s/{version}/$NODE_VERSION/; s/{archivo}/$ARCHIVO_NODE/")"
    descargar_verificado "$URL_NODE" "$CACHE/$ARCHIVO_NODE" "$SHA_NODE"
    rm -rf "$RUNTIME/node-tmp"; mkdir -p "$RUNTIME/node-tmp"
    # El .tar.xz se abre con el Python propio (módulo lzma): no hace falta tener el programa 'xz' instalado.
    "$PYTHON_VENV" -c "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='data')" "$CACHE/$ARCHIVO_NODE" "$RUNTIME/node-tmp"
    rm -rf "$NODE_DIR"; mv "$(find "$RUNTIME/node-tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)" "$NODE_DIR"; rm -rf "$RUNTIME/node-tmp"
  fi
  ok "Node $("$NODE_DIR/bin/node" --version)"
  export PATH="$NODE_DIR/bin:$PATH" COREPACK_HOME="$RUNTIME/corepack" COREPACK_ENABLE_DOWNLOAD_PROMPT=0 npm_config_store_dir="$RUNTIME/pnpm-store"
  if [ -f "$RAIZ/frontend/package.json" ]; then
    ( cd "$RAIZ/frontend" && corepack pnpm install --frozen-lockfile && corepack pnpm build ) || fallo "Falló la compilación de la web (frontend/)"
    ok "web compilada en frontend/dist"
  else
    aviso "Este paquete no incluye los fuentes de la web (frontend/package.json): no se puede compilar. Usa el paquete que trae frontend/dist ya compilada."
  fi
else
  paso "Web"; ok "frontend/dist ya está compilada (no hace falta Node)"
fi

# ---------------------------------------------------------------------------------------------------------------------------
paso "Configuración (.env)"
"$PYTHON_VENV" install/comun/configurar_env.py || fallo "No se pudo preparar el .env"

paso "Base de datos"
"$PYTHON_VENV" -m alembic -c backend/api/alembic.ini upgrade head || fallo "Falló la creación de la base de datos"
ok "base de datos al día"

if [ "$CON_ML" = 1 ] && ! grep -q '^LAPLACE_PYTHON_ML=' .env; then
  printf '\nLAPLACE_PYTHON_ML=%s\n' "$PYTHON_VENV" >> .env
  ok "el reajuste semanal del modelo usará este Python (LAPLACE_PYTHON_ML)"
fi

paso "Diagnóstico"
"$PYTHON_VENV" backend/scripts/doctor.py || true

if [ -t 0 ] && [ -t 1 ] && { [ "$SIN_ASISTENTE" != 1 ] || [ "$RECONFIGURAR" = 1 ]; }; then
  paso "Conexiones (APIs de datos, IA y Telegram)"
  RESPUESTA=s
  [ "$RECONFIGURAR" = 1 ] || read -r -p "¿Configurar ahora tus conexiones? Detecta y prueba cada API [S/n] " RESPUESTA || RESPUESTA=n
  case "$RESPUESTA" in n|N|no|NO) ;; *) "$PYTHON_VENV" install/comun/configurar.py || true ;; esac
  if [ "$SIN_ASISTENTE" != 1 ]; then
    paso "Administrador de la web"
    read -r -p "¿Crear tu administrador de la web (entra al panel de administración)? [S/n] " RESPUESTA || RESPUESTA=n
    case "$RESPUESTA" in
      n|N|no|NO) ;;
      *) read -r -p "Nombre de usuario del administrador [admin]: " USUARIO || USUARIO=""
         "$PYTHON_VENV" backend/scripts/create_admin.py --username "${USUARIO:-admin}" --si-no-hay || true ;;
    esac
  fi
fi

printf '\n%sListo.%s Para encender Laplace:  ./iniciar.sh\n' "$V" "$N"
echo "   cambiar claves o proveedores: ./configurar.sh   |   control completo: ./laplace.sh (estado, detener, logs, doctor)"
