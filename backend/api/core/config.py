"""
core/config.py — Configuración vía Pydantic Settings.

Reemplaza el patrón viejo de paths.py (if/elif KAIROS_ENV en cascada, sin
autodetección) y utils.py:cargar_env() (parser manual de .env). Una sola
fuente de configuración vía variables de entorno / .env, estándar para FastAPI.

DATABASE_URL decide el dialecto — mismo patrón que db/session.py del proyecto de
referencia (PAGINA1): si contiene "sqlite" usa SQLite (dev/local, cero infraestructura),
si no, se asume Postgres (prod/VPS). No hay una rama "Termux" especial — Termux corre lo
mismo que cualquier otro entorno Linux una vez que hay un venv con estas dependencias.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("laplace.config")


_RAIZ_PROYECTO = Path(__file__).resolve().parents[3]  # backend/api/core/config.py -> raíz del proyecto


class Settings(BaseSettings):
    # El `.env` y la base SQLite se buscan respecto a la RAÍZ DEL PROYECTO, no al directorio desde el que se lanza el proceso
    # (el instalador portable arranca el backend desde cualquier lugar: un servicio, una tarea programada, un acceso directo).
    model_config = SettingsConfigDict(env_file=_RAIZ_PROYECTO / ".env", extra="ignore")

    # Base de datos — SQLite por default (cero setup); Postgres cuando exista un VPS real.
    # Ruta relativa a la raíz del repo (backend/db/bot_deportivo.db), consistente con
    # DEPLOY_ENV.md "PC local (desarrollo)".
    DATABASE_URL: str = "sqlite:///./backend/db/bot_deportivo.db"

    # Auth simple compartida con la app/web — mismo mecanismo que ya usa WF-A2 hoy
    # (header x-kairos-key), no se introduce JWT en esta parte de la migración.
    KAIROS_AUTH_SECRET: str = "changeme-set-in-env"

    # IDs de administrador (Telegram), lista separada por comas — mismo formato que
    # SPORTS_ADMIN_ID en db_query.py.
    SPORTS_ADMIN_IDS: str = ""

    # APIs externas — mismas variables que ya usan los workflows n8n hoy
    TELEGRAM_BOT_TOKEN: str = ""
    AGENT_TELEGRAM_BOT_TOKEN: str = ""
    SPORTS_API_KEY: str = ""       # api-football / api-sports
    FOOTBALL_DATA_KEY: str = ""    # football-data.org
    # Credenciales de cuotas. Son proveedores distintos y una clave no es intercambiable.
    # `ODDSPAPI_KEY` se conserva solo como compatibilidad temporal para The Odds API: moverla a
    # `THE_ODDS_API_KEY` en el siguiente ajuste de .env. Nunca se reutiliza para OddsPapi sharp.
    THE_ODDS_API_KEY: str = ""
    ODDSPAPI_SHARP_KEY: str = ""
    ODDSPAPI_KEY: str = ""         # legado: fallback exclusivo de The Odds API
    THESTATSAPI_KEY: str = ""      # fuente experimental: prueba de 7 dias, no es dependencia activa
    LIVESCORE6_KEY: str = ""       # LiveScore6 vía RapidAPI (cascada de fixtures)
    BSD_API_KEY: str = ""          # BSD API (bzzoiro.com)
    ANTHROPIC_API_KEY: str = ""    # Claude — último recurso de la cascada de IA (sin créditos hoy)
    CLAUDE_MODEL: str = "claude-sonnet-4-6"  # mismo modelId que usaban los nodos n8n

    # Cascada de IA free-tier (agregada 2026-09-05, sin créditos de Anthropic disponibles) —
    # ver services/ai_client.py. Orden de la cascada: Gemini → Groq → OpenRouter → Claude.
    # Modelos fijados EMPÍRICAMENTE (una llamada real de prueba cada uno, no por catálogo/doc),
    # ver docs/humano/ de esta ronda para el detalle de las pruebas.
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"           # el más rápido de los 3 en la prueba real (~0.08s)
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-flash-lite-latest"
    GEMINI_THINKING_BUDGET: int = 0    # alias siempre-vigente de Google al último flash-lite
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-super-120b-a12b:free"  # el primer :free probado (glm-5.2) dio 429 del pool compartido

    # Ollama Cloud: proveedor remoto con API key; Laplace no utiliza Ollama local en runtime.
    #  - ollama_cloud: modelos grandes hospedados en ollama.com (misma API /api/chat, Bearer key).
    #    Modelo por defecto verificado en https://ollama.com/api/tags el 2026-09-29.
    # Las dos variables locales se conservan solo para que un .env antiguo siga cargando; el
    # enrutador las ignora deliberadamente.
    OLLAMA_API_KEY: str = ""
    OLLAMA_CLOUD_MODEL: str = "gpt-oss:120b"
    OLLAMA_LOCAL_URL: str = "http://localhost:11434"
    OLLAMA_LOCAL_MODEL: str = ""

    # Orden de la cascada de IA por rol (lista de proveedores separada por comas). Roles: bot
    # (análisis de partido Telegram/app), canal (top picks), agente (agent_runtime) y laboratorio
    # (ia_simple_laboratorio). Proveedores válidos: gemini, groq, openrouter, ollama_cloud,
    # claude. Los sin key/modelo configurado se saltan solos; nombres desconocidos
    # se ignoran con warning; vacío → default de `services/ai_client.py::ROUTING_DEFAULT`.
    AI_ROUTING_BOT: str = ""
    AI_ROUTING_CANAL: str = ""
    AI_ROUTING_AGENTE: str = ""
    AI_ROUTING_LABORATORIO: str = ""

    # Temperatura para los 4 proveedores de la cascada de IA (2026-09-10). El default de la
    # mayoría de proveedores (~1.0) es demasiado alto para esta tarea: el pick final debe ser
    # consistente si se reanaliza el mismo partido con los mismos datos (ver
    # `services/consenso_ia.py::combinar_con_claude`, que compara el pick de IA contra el
    # consenso estadístico — un pick que cambia entre corridas por puro ruido del muestreo del
    # modelo degrada esa comparación). 0.4 deja margen para que la prosa de las líneas 📈/H2H/
    # BTTS no sea mecánica, sin la variabilidad alta que tendría el pick con temperatura default.
    AI_TEMPERATURE: float = 0.4

    # Telegram — canal/grupo/admin usados por WF-A/WF-B/WF-D/WF-E (antes hardcodeados en n8n)
    TELEGRAM_CANAL_ID: str = ""
    TELEGRAM_GRUPO_URL: str = ""
    TELEGRAM_GRUPO_NOMBRE: str = "Grupo de la comunidad"
    SPORTS_ADMIN_ID: str = ""      # chat_id único del admin para notificaciones (distinto de admin_ids/lista de acceso)

    # Login usuario+clave (app/web, sin correo) — agregado 2026-09-07. Distinto de
    # KAIROS_AUTH_SECRET (ese es el secreto compartido app→backend, este firma el JWT
    # de sesión por-usuario que devuelve /api/v1/auth/login).
    WEB_JWT_SECRET: str = "changeme-set-in-env"
    WEB_JWT_EXPIRA_HORAS: int = 720  # 30 días

    # Entorno — informativo, ya no condiciona rutas (a diferencia de paths.py viejo)
    ENV: str = "local"

    # Interruptor del ciclo diario de auto-evaluación de laplace-agents (2026-09-10) — hasta
    # ahora no existía forma de apagarlo sin comentar código (`main.py::_job_laplace_agents`,
    # cron 8am Chile). Default `True` para no cambiar el comportamiento actual; se desactiva
    # explícito en `.env` (ej. mientras se depura un bug del ciclo sin gastar cuota de APIs
    # externas en cada corrida de las 8am).
    LAPLACE_AGENTS_ACTIVO: bool = True

    # Runtime del agente general. False conserva un comportamiento determinista sin llamadas
    # externas; el usuario puede solicitar IA por turno cuando este flag está activo.
    AGENT_IA_ACTIVA: bool = True

    # Comparador IA simple: limitado y siempre en sombra. No participa en el consenso ni se
    # ejecuta para cada consulta de usuario; Top Picks lo usa como muestra diaria acotada.
    LAB_IA_SIMPLE_ACTIVA: bool = True
    LAB_IA_SIMPLE_MAX_PARTIDOS: int = 5

    # Procesos independientes en Windows/VPS. Cada componente puede continuar sin el otro.
    AGENT_URL: str = "http://127.0.0.1:9100"
    SPORTS_BACKEND_URL: str = "http://127.0.0.1:9001"
    AGENT_LOCAL_EXECUTOR: bool = True
    ALERTS_ACTIVAS: bool = False
    ALERT_WEBHOOK_URL: str = ""

    # CORS — orígenes permitidos para llamadas desde navegador (ej. `frontend/` en Vercel o
    # `astro dev` local, si algún endpoint se termina llamando directo desde el navegador en
    # vez de vía proxy Astro server-side). Lista separada por comas, ej:
    # "https://mi-sitio.example,http://localhost:9002". Default vacío =
    # restrictivo (CORSMiddleware con allow_origins=[] no agrega el header para ningún
    # origen) — nunca "*" junto con allow_credentials=True: eso permitiría a CUALQUIER sitio
    # leer respuestas autenticadas del usuario vía JS (agujero real, no teórico).
    CORS_ORIGINS: str = ""

    @property
    def admin_ids(self) -> list[str]:
        return [v.strip() for v in self.SPORTS_ADMIN_IDS.split(",") if v.strip()]

    @property
    def the_odds_api_key(self) -> str:
        """Clave de The Odds API con transición segura desde el nombre legado."""
        return self.THE_ODDS_API_KEY or self.ODDSPAPI_KEY

    @property
    def oddspapi_sharp_key(self) -> str:
        """Clave específica de OddsPapi para mercado sharp; no usa el legado."""
        return self.ODDSPAPI_SHARP_KEY

    @field_validator("DATABASE_URL")
    @classmethod
    def _sqlite_relativa_a_la_raiz(cls, valor: str) -> str:
        """`sqlite:///./x.db` es relativa al directorio de trabajo: se ancla a la raíz del proyecto (absolutas y :memory: no cambian)."""
        prefijo = "sqlite:///"
        if valor.startswith(prefijo):
            ruta = valor[len(prefijo):]
            if ruta and ruta != ":memory:" and not ruta.startswith("/") and not Path(ruta).is_absolute():
                return prefijo + (_RAIZ_PROYECTO / ruta).resolve().as_posix()
        return valor

    @property
    def cors_origins_list(self) -> list[str]:
        return [v.strip() for v in self.CORS_ORIGINS.split(",") if v.strip()]

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    @property
    def repo_root(self) -> Path:
        # backend/api/core/config.py -> backend/api/core -> backend/api -> backend -> raíz
        return Path(__file__).resolve().parents[3]


SECRETO_PLACEHOLDER = "changeme-set-in-env"
SECRETO_LARGO_MINIMO = 32


def _secreto_inseguro(valor: str) -> bool:
    return not valor or valor == SECRETO_PLACEHOLDER or len(valor) < SECRETO_LARGO_MINIMO


def validar_secretos_arranque(cfg: Settings) -> list[str]:
    """Chequea que `KAIROS_AUTH_SECRET` y `WEB_JWT_SECRET` no sigan en su valor por defecto
    (`changeme-set-in-env`), vacíos ni cortos (< 32 caracteres).

    Con `ENV != "local"` lanza `RuntimeError` (un JWT firmado con un secreto público permite
    forjar sesiones de admin). Con `ENV == "local"` solo loguea un warning. Nunca incluye el
    valor del secreto en el mensaje ni en el log — solo el NOMBRE de la variable. Devuelve los
    nombres inseguros (útil para tests)."""
    inseguros = [
        nombre
        for nombre, valor in (("KAIROS_AUTH_SECRET", cfg.KAIROS_AUTH_SECRET), ("WEB_JWT_SECRET", cfg.WEB_JWT_SECRET))
        if _secreto_inseguro(valor)
    ]
    if not inseguros:
        return []
    detalle = ", ".join(inseguros)
    if cfg.ENV != "local":
        raise RuntimeError(
            f"Secretos inseguros con ENV={cfg.ENV!r}: {detalle} siguen en el valor por defecto, "
            f"vacíos o con menos de {SECRETO_LARGO_MINIMO} caracteres. Definirlos en .env con un "
            "valor aleatorio largo antes de arrancar."
        )
    log.warning(
        "Secretos con valor por defecto/corto en ENV=local: %s (aceptable solo en desarrollo)", detalle
    )
    return inseguros


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
