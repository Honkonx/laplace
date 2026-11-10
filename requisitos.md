# Requisitos 📋

Lo que necesitas para instalar y usar Laplace. Spoiler: casi nada, porque el instalador trae lo suyo.

## 💻 Tu equipo

| | Qué necesitas |
|---|---|
| **Sistema** | Windows 10/11 de 64 bits · Linux con glibc (Debian, Ubuntu, Fedora, Arch…) · WSL · macOS (instalador sin probar) |
| **Procesador** | x86-64 o ARM64 |
| **Disco libre** | al menos **2 GB** (el instalador lo revisa). El entorno de Python ocupa unos 0,2 GB; si además se compila la web con Node, unos 0,5 GB más |
| **Memoria** | 4 GB o más es lo razonable. No está medida: son dos procesos de Python (backend y agente) |
| **Permisos** | ninguno especial: **no pide administrador** ni toca el Python, el Node ni el PATH de tu sistema |
| **Internet** | sí, en la instalación (descarga uv, Python, y Node si hace falta, más las dependencias) y para usar las fuentes de datos y la IA |

**No funciona** en Alpine Linux (usa musl y Node no publica binarios oficiales para él). **Sin probar:** Termux/Android y macOS.

## 🧩 Programas

**Ninguno previo.** El instalador descarga y deja dentro de la carpeta:
- **uv** → instala **Python 3.13** propio (en `runtime/`).
- **Node** y **pnpm** → solo si falta la web compilada y hay que construirla.

Lo único que sí debe existir en tu sistema:

| Sistema | Qué |
|---|---|
| Windows | PowerShell 5.1 (ya viene con Windows) |
| Linux / macOS / WSL | `bash`, `curl` o `wget`, `tar`, `gzip` y `sha256sum` (o `shasum`) |
| Opcional | **git**, para clonar el repositorio y actualizarlo (si no, descarga el `.zip`) |

## 🔌 Puertos

| Puerto | Para qué |
|---|---|
| **9001** | backend: API, bot de Telegram, planificador y la web |
| **9100** | agente de chat |
| 9002 / 9003 | solo si desarrollas la web / la PWA con `pnpm dev` |

Por defecto solo escuchan en tu equipo (`127.0.0.1`). Se pueden cambiar con `LAPLACE_PUERTO_BACKEND` y `LAPLACE_PUERTO_AGENTE`.

## 🔑 Cuentas y claves (todas opcionales)

Laplace arranca sin ninguna. Cada clave activa una parte; consíguelas en el sitio de cada proveedor (casi todos tienen plan gratis) y pégalas con **`configurar`** (`configurar.bat` / `./configurar.sh`): te muestra el enlace de cada una, **prueba la clave** contra el proveedor antes de guardarla y la deja en `.env` sin mostrarla.

| Qué quieres | Clave | Dónde se consigue |
|---|---|---|
| **Usar el bot de Telegram** | `TELEGRAM_BOT_TOKEN` | en Telegram, con [@BotFather](https://t.me/BotFather) |
| Un segundo bot para el agente | `AGENT_TELEGRAM_BOT_TOKEN` | otro bot de @BotFather |
| Ser administrador del bot | `SPORTS_ADMIN_IDS` | tu id numérico: te lo da el comando `/mi_id` del bot |
| **Cuotas del mercado** (el insumo del pronóstico) | `THE_ODDS_API_KEY` | [the-odds-api.com](https://the-odds-api.com) |
| Calendario y H2H | `SPORTS_API_KEY` | [api-football.com](https://www.api-football.com) |
| Cuotas de casas «sharp» (opcional) | `ODDSPAPI_SHARP_KEY` | [oddspapi.io](https://oddspapi.io) |
| Tablas de posiciones | `FOOTBALL_DATA_KEY` | [football-data.org](https://www.football-data.org) |
| Calendario del día | `LIVESCORE6_KEY` | LiveScore6 en [RapidAPI](https://rapidapi.com) |
| Predicciones externas | `BSD_API_KEY` | BSD (bzzoiro.com) |
| **IA que explica el pronóstico** | `OLLAMA_API_KEY` | [ollama.com/settings/keys](https://ollama.com/settings/keys) |
| IA de respaldo | `GROQ_API_KEY` · `GOOGLE_API_KEY` · `OPENROUTER_API_KEY` · `ANTHROPIC_API_KEY` | [console.groq.com](https://console.groq.com) · [aistudio.google.com](https://aistudio.google.com) · [openrouter.ai](https://openrouter.ai) · [console.anthropic.com](https://console.anthropic.com) |

> 💡 Un arranque cómodo: **token de Telegram + clave de The Odds API + una clave de IA**. Con eso tienes bot, pronósticos con cuotas y explicaciones. Cada proveedor tiene sus propios límites y términos: respétalos ([seguridad y datos](docs/seguridad-y-datos.md)).

## 🧩 Lo que este repositorio NO trae

Ni datos históricos ni modelos entrenados. Sin modelo propio el motor usa las cuotas; sin cuotas, el partido queda «sin pronóstico propio». Para entrenar el tuyo: [docs/motor-de-pronostico.md](docs/motor-de-pronostico.md).

## 🛠️ Solo si vas a desarrollar

| Para | Necesitas |
|---|---|
| Backend y pruebas | lo que instala el propio instalador (Python 3.13 en `runtime/venv`) + `requirements-dev.txt` |
| Web y PWA | **pnpm** (no npm). El instalador trae Node y pnpm con `-ConNode` / `--con-node` |
| Entrenar el modelo | `-ConML` / `--con-ml` (numpy, scipy y scikit-learn) y tus propios datos históricos |
| App Android | Android Studio o el SDK de Android (compileSdk 36, minSdk 24) y un JDK compatible con el Gradle del proyecto; propiedades en [docs/web-pwa-y-android.md](docs/web-pwa-y-android.md) |

¿Listo? Sigue la **[guía](guia.md)**.
