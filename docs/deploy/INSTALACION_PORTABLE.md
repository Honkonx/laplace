# Instalación portable

Laplace se instala en una carpeta autocontenida: Python propio (instalado con `uv`), Node y pnpm propios si hace falta compilar la web, y todo bajo `runtime/`. No toca el Python ni el Node del sistema. Las descargas se verifican con SHA-256 contra `install/runtime-pins.json`.

## Los cuatro comandos
| Comando | Qué hace |
|---|---|
| `instalar` (`.bat` / `.sh`) | Crea `runtime/`, instala dependencias, genera `.env` con secretos aleatorios, ofrece abrir `configurar` y crear el primer administrador (solo con terminal) |
| `configurar` | Menú para ver, probar, poner o cambiar claves, el orden de la IA, el administrador de Telegram y el canal; `configurar --estado` lista sin preguntar |
| `iniciar` | Enciende API + bot de Telegram + planificador + web (puerto 9001) y el agente (9100); avisa qué falta y abre la web si hay terminal |
| `laplace` | Control: `iniciar`, `detener`, `reiniciar`, `estado`, `logs`, `doctor`, `abrir`, `configurar` |

Opciones de `instalar`: `-SinAsistente` / `--sin-asistente` (sin preguntas), `-Reconfigurar` / `--reconfigurar` (abre `configurar` sobre una instalación existente), `-ConNode` / `--con-node` (instala Node y pnpm y recompila la web), `-ConML` / `--con-ml` (numpy, scipy y scikit-learn para el reajuste de modelos), `-Rehacer` / `--rehacer` (recrea `runtime/venv`). La primera forma es de `instalar.ps1`; la segunda, de `instalar.sh`.

Los `.bat` esperan una tecla antes de cerrarse solo si se abrieron con doble clic; `LAPLACE_SIN_PAUSA=1` lo desactiva. Buscan el entorno en `runtime/venv`, `.venv` y `.venv_backend`.

## Estructura
- `install/windows/instalar.ps1`, `install/linux/instalar.sh`: instaladores por sistema.
- `install/comun/laplace.py` (control), `configurar.py` (asistente de claves), `configurar_env.py` (`.env`: genera secretos y escribe de forma atómica con permisos restringidos).
- `backend/api/core/conexiones.py`: registro único de las conexiones externas (enlace, plan, variable, prueba gratuita). Lo usan `configurar`, `doctor` y el panel «Conexiones» de la web.
- `backend/scripts/doctor.py`: diagnóstico (`laplace doctor`): entorno, claves, fuentes, base de datos, puertos.
- La web compilada (`frontend/dist`) la sirve el propio backend (`backend/api/web_estatico.py`); el service worker no cachea `index.html` ni a sí mismo.

## Respaldar
Detén Laplace (`laplace detener`) y copia `backend/db/` (la base de datos) y `.env`. Ver [`BACKUPS_LAPLACE.md`](BACKUPS_LAPLACE.md) en el repositorio de trabajo.

## Sin modelo ni datos históricos
El repositorio público no trae datos ni modelos entrenados. Sin ellos el producto arranca y el motor trabaja con las cuotas; `laplace doctor` lo indica. Los trabajos de colecta y reajuste responden «no aplica en esta instalación» en vez de fallar.
