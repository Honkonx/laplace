# Changelog

## 1.0.0 — primera versión pública
- Backend FastAPI con bot de Telegram, planificador y web en el mismo proceso (puerto 9001), y agente de chat independiente (puerto 9100).
- Motor de pronóstico: modelo histórico Dixon-Coles (sin datos ni modelos entrenados incluidos), cuotas sin margen, consenso ponderado con puerta de calidad y nivel de evidencia N4…N0.
- Tres scripts a la vista: `instalar`, `configurar` (detecta y prueba cada API, ✓/✗/⚠, clave por número, también desde el panel web) e `iniciar`.
- Instalación portable para Windows, Linux, macOS y WSL: Python propio (uv) y Node/pnpm opcionales, descargas verificadas por SHA-256, asistente de `.env`, `laplace doctor`.
- Web, PWA y app Android (Kotlin/Compose).
- Licencia AGPL-3.0.
