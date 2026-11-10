# Instalación (referencia técnica)

> La receta paso a paso está en la [guía](../guia.md) y lo que necesitas, en los [requisitos](../requisitos.md). Aquí se detalla qué hace el instalador.

## Qué hace el instalador
`instalar.bat` (Windows) e `instalar.sh` (Linux, macOS, WSL) hacen lo mismo y son repetibles:

1. Revisan el equipo (sistema, arquitectura, espacio libre ≥ 2 GB, puertos 9001 y 9100).
2. Descargan **uv** y, con él, instalan **Python 3.13** dentro de `runtime/python`. No se toca el Python del sistema ni el `PATH`.
3. Crean `runtime/venv` e instalan `backend/requirements.txt`.
4. Si falta `frontend/dist` (la web compilada), descargan **Node** y **pnpm** propios y la compilan.
5. Crean `.env` con secretos propios (no piden claves: de eso se encarga `configurar`).
6. Crean la base de datos (`alembic upgrade head`) y corren `doctor`.
7. Si hay terminal y no usaste `-SinAsistente`: ofrecen abrir `configurar` (detecta y prueba tus APIs) y crear tu administrador de la web (`create_admin.py --si-no-hay`: nunca cambia el de una instalación existente; la contraseña se muestra una sola vez).

Cada descarga se compara con la huella SHA-256 fijada en `install/runtime-pins.json`; si no coincide, se cancela sin extraer nada. Correrlo otra vez solo completa lo que falte.

## Opciones
| Windows | Linux / macOS / WSL | Efecto |
|---|---|---|
| `-SinAsistente` | `--sin-asistente` | no pregunta claves |
| `-Reconfigurar` | `--reconfigurar` | al final abre directamente `configurar` (no toca los secretos propios) |
| `-ConNode` | `--con-node` | instala Node/pnpm y recompila la web |
| `-ConML` | `--con-ml` | instala numpy, scipy y scikit-learn (reajuste del modelo y evaluaciones) |
| `-Rehacer` | `--rehacer` | recrea `runtime/venv` |

## Uso diario
`iniciar.bat` / `./iniciar.sh` (avisa si falta algo clave, enciende y abre la web) · `configurar.bat` / `./configurar.sh` (detecta, prueba y cambia tus APIs; `--estado`, `--probar`, `--solo ID`) · control completo con `laplace.bat` / `./laplace.sh`: `iniciar [--lan] [--sin-agente] [--avisar] [--abrir]`, `configurar`, `detener`, `reiniciar`, `estado`, `logs`, `doctor [--red]`, `abrir`.
`--lan` abre el servicio a tu red local (otra PC, el celular); sin él solo responde en este equipo. Los puertos se cambian con `LAPLACE_PUERTO_BACKEND` y `LAPLACE_PUERTO_AGENTE`.

## Requisitos
Internet en la primera instalación; Windows 10+ de 64 bits, o Linux con glibc (Debian, Ubuntu, Fedora, Arch…). Alpine (musl) no está soportada porque Node no publica binarios oficiales para ella. No se necesitan permisos de administrador.

## Comprobado y no comprobado
Instalado y encendido en una carpeta limpia en Windows 11 y en Debian 13 (WSL). **Sin probar:** macOS, arm64 y Termux (Android).
