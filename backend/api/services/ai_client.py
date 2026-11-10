"""services/ai_client.py — Cliente de IA con cascada multi-proveedor y enrutamiento por rol.

Proveedores (todos vía `httpx` REST directo, sin SDK propio de cada uno): `gemini`, `groq`,
`openrouter`, `ollama_cloud` y `claude`. Cada uno se describe con un
`_Proveedor` (cómo saber si está configurado, cómo armar la petición, cómo extraer el texto); el
try/except, las métricas (`ai_metrics`) y el log son un único helper (`_intentar`) — antes eran
4 copias casi idénticas.

Orden de la cascada según el ROL del caller (`rol` en `generar_texto_ia*`): "bot" (análisis de
partido Telegram/app), "canal" (top picks), "agente" (`agent_runtime`) y "laboratorio"
(`ia_simple_laboratorio`). Cada rol tiene un default en `ROUTING_DEFAULT` que se puede cambiar por
entorno con `AI_ROUTING_<ROL>` (lista separada por comas, ver `core/config.py`). Los proveedores
sin key o sin modelo configurado se saltan solos; un nombre desconocido en la lista se ignora con
un warning; una lista vacía o sin ningún nombre válido cae al default.

Modelos free-tier fijados EMPÍRICAMENTE (una llamada real de prueba a cada uno, no por
catálogo/documentación — ver `.claude/rules/empirical-verification-before-fix.md`):
  - **Groq** `openai/gpt-oss-120b`: el más rápido en la prueba real (~0.08s), sin rate limit visible.
  - **Google** `gemini-flash-lite-latest`: alias que Google mantiene apuntando al último
    flash-lite (evita fijar una versión que se deprecia) — free tier generoso.
  - **OpenRouter** `nvidia/nemotron-3-super-120b-a12b:free`: el primer modelo `:free` probado
    (`z-ai/glm-5.2:free`) devolvió HTTP 429 del pool compartido — los `:free` de OpenRouter son la
    fuente menos confiable, por eso va después de Groq/Ollama cloud en los defaults.

Ollama (agregado 2026-09-29 por orden explícita del usuario; antes se había descartado por
YAGNI, ver el registro de decisiones del proyecto):
  - **ollama_cloud** — `POST https://ollama.com/api/chat` con `Authorization: Bearer
    OLLAMA_API_KEY`, modelo `OLLAMA_CLOUD_MODEL` (default `gpt-oss:120b`, listado en
    https://ollama.com/api/tags el 2026-09-29). Solo participa si hay key.
  - Modelos "thinking": Ollama devuelve el razonamiento en `message.thinking` y la respuesta en
    `message.content`; solo se usa `content` (si viene vacío se pasa al siguiente proveedor).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.api.core.config import settings
from backend.api.core.exceptions import LaplaceError
from backend.api.services import ai_metrics

log = logging.getLogger("laplace.ai_client")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL_TPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OLLAMA_CLOUD_URL = "https://ollama.com/api/chat"

# Catálogo inicial solicitado para el plan Free de Ollama Cloud. Es una ayuda de interfaz, no
# una allowlist: el administrador puede ingresar cualquier modelo habilitado por su cuenta.
OLLAMA_CLOUD_FREE_MODELS = (
    "gemma4:31b", "gpt-oss:120b", "gpt-oss:20b", "nemotron-3-nano:30b",
    "nemotron-3-super", "nemotron-3-ultra",
)

ROL_DEFAULT = "bot"

_ORDEN_GENERAL = ("gemini", "groq", "ollama_cloud", "openrouter", "claude")
ROUTING_DEFAULT: dict[str, tuple[str, ...]] = {
    "bot": _ORDEN_GENERAL,
    "canal": _ORDEN_GENERAL,
    "laboratorio": _ORDEN_GENERAL,
    "agente": ("ollama_cloud", "groq", "gemini", "openrouter", "claude"),
}


class AnalisisIAError(LaplaceError):
    """Los proveedores de IA disponibles fallaron o ninguno tiene API key configurada — el
    caller (`analisis_completo.py`, `top_picks.py`) degrada a solo estadístico."""


@dataclass(frozen=True)
class _Proveedor:
    nombre: str
    configurado: Callable[[], bool]
    modelo: Callable[[], str]
    # (prompt, max_tokens, temperature) -> kwargs de `client.post` (sin `timeout`)
    peticion: Callable[[str, int, float], dict]
    url: Callable[[], str]
    extraer: Callable[[httpx.Response], str]
    timeout: float = 20


def _mensajes(prompt: str) -> list[dict]:
    return [{"role": "user", "content": prompt}]


def _peticion_openai(api_key: Callable[[], str], modelo: Callable[[], str]) -> Callable[[str, int, float], dict]:
    """Groq y OpenRouter comparten el formato chat-completions de OpenAI."""

    def construir(prompt: str, max_tokens: int, temperature: float) -> dict:
        return {
            "headers": {"Authorization": f"Bearer {api_key()}"},
            "json": {"model": modelo(), "messages": _mensajes(prompt), "max_tokens": max_tokens,
                     "temperature": temperature},
        }

    return construir


def _extraer_openai(r: httpx.Response) -> str:
    return r.json()["choices"][0]["message"]["content"].strip()


def _peticion_gemini(prompt: str, max_tokens: int, temperature: float) -> dict:
    return {
        "params": {"key": settings.GOOGLE_API_KEY},
        "json": {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max(max_tokens, 128),
                "temperature": temperature,
                "thinkingConfig": {"thinkingBudget": settings.GEMINI_THINKING_BUDGET},
            },
        },
    }


def _extraer_gemini(r: httpx.Response) -> str:
    payload = r.json()
    candidates = payload.get("candidates") or []
    partes = (candidates[0].get("content") or {}).get("parts") if candidates else None
    if not partes:
        motivo = (
            candidates[0].get("finishReason", "sin candidato de texto")
            if candidates else payload.get("promptFeedback", "sin candidato")
        )
        raise ValueError(f"Gemini no devolvio texto final: {motivo}")
    return "".join(p.get("text", "") for p in partes if not p.get("thought", False)).strip()


def _peticion_claude(prompt: str, max_tokens: int, temperature: float) -> dict:
    return {
        "headers": {"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        "json": {"model": settings.CLAUDE_MODEL, "max_tokens": max_tokens, "temperature": temperature,
                 "messages": _mensajes(prompt)},
    }


def _extraer_claude(r: httpx.Response) -> str:
    bloques = r.json().get("content", [])
    return "\n".join(b["text"] for b in bloques if b.get("type") == "text").strip()


# Los modelos "thinking" de Ollama (gpt-oss, deepseek, glm…) gastan parte de `num_predict` en su
# razonamiento antes de escribir `content`; con un tope bajo (ej. 100 tokens de un resumen corto)
# el razonamiento agota el presupuesto y la respuesta llega vacía. Piso de tokens para Ollama.
OLLAMA_NUM_PREDICT_MINIMO = 1024


def _peticion_ollama(modelo: Callable[[], str], api_key: Callable[[], str] | None = None) -> Callable[[str, int, float], dict]:
    def construir(prompt: str, max_tokens: int, temperature: float) -> dict:
        peticion: dict = {
            "json": {"model": modelo(), "messages": _mensajes(prompt), "stream": False,
                     "options": {"temperature": temperature,
                                    "num_predict": max(max_tokens, OLLAMA_NUM_PREDICT_MINIMO)}},
        }
        if api_key is not None:
            peticion["headers"] = {"Authorization": f"Bearer {api_key()}"}
        return peticion

    return construir


def _extraer_ollama(r: httpx.Response) -> str:
    # Solo `content`: `message.thinking` es el razonamiento interno de los modelos "thinking".
    return (r.json().get("message") or {}).get("content", "").strip()


_PROVEEDORES: dict[str, _Proveedor] = {
    p.nombre: p
    for p in (
        _Proveedor(
            "gemini", lambda: bool(settings.GOOGLE_API_KEY), lambda: settings.GEMINI_MODEL,
            _peticion_gemini, lambda: GEMINI_URL_TPL.format(model=settings.GEMINI_MODEL), _extraer_gemini,
        ),
        _Proveedor(
            "groq", lambda: bool(settings.GROQ_API_KEY), lambda: settings.GROQ_MODEL,
            _peticion_openai(lambda: settings.GROQ_API_KEY, lambda: settings.GROQ_MODEL),
            lambda: GROQ_URL, _extraer_openai,
        ),
        _Proveedor(
            "openrouter", lambda: bool(settings.OPENROUTER_API_KEY), lambda: settings.OPENROUTER_MODEL,
            _peticion_openai(lambda: settings.OPENROUTER_API_KEY, lambda: settings.OPENROUTER_MODEL),
            lambda: OPENROUTER_URL, _extraer_openai,
        ),
        _Proveedor(
            "ollama_cloud", lambda: bool(settings.OLLAMA_API_KEY), lambda: settings.OLLAMA_CLOUD_MODEL,
            _peticion_ollama(lambda: settings.OLLAMA_CLOUD_MODEL, lambda: settings.OLLAMA_API_KEY),
            lambda: OLLAMA_CLOUD_URL, _extraer_ollama, timeout=30,
        ),
        _Proveedor(
            "claude", lambda: bool(settings.ANTHROPIC_API_KEY), lambda: settings.CLAUDE_MODEL,
            _peticion_claude, lambda: ANTHROPIC_URL, _extraer_claude, timeout=30,
        ),
    )
}


def orden_proveedores(rol: str = ROL_DEFAULT) -> tuple[str, ...]:
    """Orden de la cascada para `rol`: `AI_ROUTING_<ROL>` si tiene al menos un proveedor válido,
    si no el default del rol (rol desconocido → default de "bot")."""
    rol_normalizado = (rol or ROL_DEFAULT).strip().lower()
    default = ROUTING_DEFAULT.get(rol_normalizado)
    if default is None:
        log.warning("Rol de IA desconocido %r — se usa el orden del rol %r", rol, ROL_DEFAULT)
        rol_normalizado, default = ROL_DEFAULT, ROUTING_DEFAULT[ROL_DEFAULT]

    configurado = getattr(settings, f"AI_ROUTING_{rol_normalizado.upper()}", "") or ""
    orden: list[str] = []
    for nombre in (n.strip().lower() for n in configurado.split(",")):
        if not nombre:
            continue
        if nombre not in _PROVEEDORES:
            log.warning("AI_ROUTING_%s: proveedor de IA desconocido %r — ignorado", rol_normalizado.upper(), nombre)
        elif nombre not in orden:
            orden.append(nombre)
    return tuple(orden) if orden else default


# Presupuesto total de una llamada a `generar_texto_ia_con_meta` (toda la cascada) y reintento
# único ante 429/5xx por proveedor: sin tope, 5 proveedores x 20-30 s podían bloquear una
# petición del usuario más de 2 minutos.
PRESUPUESTO_TOTAL_SEGUNDOS = 45.0
REINTENTOS_POR_PROVEEDOR = 1
BACKOFF_REINTENTO_SEGUNDOS = 0.6
_MARGEN_MINIMO_SEGUNDOS = 1.0


def _es_reintentable(error: Exception) -> bool:
    return isinstance(error, httpx.HTTPStatusError) and (
        error.response.status_code == 429 or error.response.status_code >= 500
    )


async def _intentar(
    client: httpx.AsyncClient, proveedor: _Proveedor, prompt: str, max_tokens: int, temperature: float,
    limite: float | None = None,
) -> str | None:
    """Un intento a `proveedor` (con 1 reintento corto ante 429/5xx): texto no vacío, o None si no
    está configurado, falló o devolvió vacío. `limite` es el instante (`time.monotonic`) en que se
    agota el presupuesto total. Registra la métrica (éxito o fallo) y nunca propaga una excepción
    del proveedor."""
    if not proveedor.configurado():
        return None
    modelo = proveedor.modelo()
    inicio = time.perf_counter()
    for intento in range(REINTENTOS_POR_PROVEEDOR + 1):
        timeout = proveedor.timeout
        if limite is not None:
            timeout = min(timeout, limite - time.monotonic())
            if timeout < _MARGEN_MINIMO_SEGUNDOS:
                log.warning("%s omitido: presupuesto de tiempo de IA agotado", proveedor.nombre)
                return None
        try:
            r = await client.post(
                proveedor.url(), timeout=timeout, **proveedor.peticion(prompt, max_tokens, temperature)
            )
            r.raise_for_status()
            texto = proveedor.extraer(r)
            ai_metrics.registrar_intento(
                proveedor.nombre, exitoso=True, latencia_ms=ai_metrics.ms_desde(inicio), modelo=modelo
            )
            return texto or None
        except Exception as e:
            if intento < REINTENTOS_POR_PROVEEDOR and _es_reintentable(e):
                await asyncio.sleep(BACKOFF_REINTENTO_SEGUNDOS)
                continue
            ai_metrics.registrar_intento(
                proveedor.nombre, exitoso=False, latencia_ms=ai_metrics.ms_desde(inicio),
                modelo=modelo, error=ai_metrics.sanitizar_error(str(e)),
            )
            log.warning("%s falló, probando siguiente proveedor de IA (%s)", proveedor.nombre, type(e).__name__)
            return None
    return None


async def generar_texto_ia_con_meta(
    prompt: str, max_tokens: int = 1024, temperature: float | None = None, rol: str = ROL_DEFAULT
) -> tuple[str, str, str]:
    """Punto de entrada único — prueba cada proveedor en el orden de `rol` y devuelve
    `(texto, proveedor, modelo)` del primero con texto no vacío. Lanza `AnalisisIAError` solo si
    todos fallan (o ninguno está configurado) o si se agota `PRESUPUESTO_TOTAL_SEGUNDOS`.

    `temperature=None` usa `settings.AI_TEMPERATURE` (0.4, ver `core/config.py`); se acepta un
    override explícito para tests y para un caller que necesite más/menos variabilidad."""
    temp = settings.AI_TEMPERATURE if temperature is None else temperature
    limite = time.monotonic() + PRESUPUESTO_TOTAL_SEGUNDOS
    async with httpx.AsyncClient() as client:
        for nombre in orden_proveedores(rol):
            proveedor = _PROVEEDORES[nombre]
            texto = await _intentar(client, proveedor, prompt, max_tokens, temp, limite)
            if texto:
                return texto, nombre, proveedor.modelo()
    raise AnalisisIAError("Los proveedores de IA configurados fallaron o no hay ninguna API key seteada")


async def generar_texto_ia(
    prompt: str, max_tokens: int = 1024, temperature: float | None = None, rol: str = ROL_DEFAULT
) -> str:
    """Compatibilidad para consumidores que solo requieren texto."""
    texto, _, _ = await generar_texto_ia_con_meta(prompt, max_tokens, temperature, rol)
    return texto
