"""Barreras de seguridad del agente: presupuesto de IA, confianza de destino y tokens de servicio.

Todo es configuración por entorno (sin tocar `core/config.py`, que es de otro frente):

- `AGENT_IA_MAX_POR_MINUTO` (def. 5) y `AGENT_IA_MAX_POR_DIA` (def. 60; admin x5): tope de
  llamadas con `usar_ia=true` por usuario. Contadores en memoria del proceso (un solo proceso
  por componente; si API y worker corren separados cada uno lleva su cuenta, el tope efectivo es
  como máximo el doble).
- `AGENT_MAX_TAREAS_ACTIVAS` (def. 10): tareas queued/running simultáneas por usuario.
- `AGENT_SPORTS_TRUSTED_HOSTS`: hosts extra (coma) a los que se permite enviar un Bearer. Loopback
  siempre es confiable.
- `AGENT_APPROVAL_TTL_SECONDS` (def. 3600): vigencia de una aprobación pendiente.
- `AGENT_TELEGRAM_ALLOWED_IDS`, `AGENT_TELEGRAM_BLOCKED_IDS`, `AGENT_TELEGRAM_RATE_PER_MIN` (def. 10) y
  `AGENT_PREDICCIONES_MAX_POR_DIA`/`_POR_MINUTO` (def. 15/3): ver el bot.
"""
from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import jwt

from backend.api.core.config import settings


def entero_env(nombre: str, defecto: int) -> int:
    """Lee un entero de `settings` o del entorno; cualquier valor inválido usa el defecto."""
    crudo = getattr(settings, nombre, None)
    if crudo is None:
        crudo = os.environ.get(nombre)
    try:
        valor = int(crudo) if crudo not in (None, "") else defecto
    except (TypeError, ValueError):
        return defecto
    return valor if valor > 0 else defecto


def lista_env(nombre: str) -> set[str]:
    crudo = getattr(settings, nombre, None)
    if crudo is None:
        crudo = os.environ.get(nombre, "")
    return {parte.strip() for parte in str(crudo or "").replace(";", ",").split(",") if parte.strip()}


class LimiteExcedido(Exception):
    """El usuario superó su tope de uso; el router la traduce a HTTP 429."""

    def __init__(self, motivo: str, reintentar_en: int = 60) -> None:
        super().__init__(motivo)
        self.reintentar_en = reintentar_en


_LOCK = threading.Lock()
_VENTANA_MINUTO: dict[str, list[float]] = {}
_USO_DIA: dict[tuple[str, str], int] = {}


def resetear_contadores() -> None:
    with _LOCK:
        _VENTANA_MINUTO.clear()
        _USO_DIA.clear()


def consumir_ia(usuario: str, *, es_admin: bool = False, cantidad: int = 1) -> None:
    """Reserva `cantidad` llamadas de IA para el usuario o lanza `LimiteExcedido`."""
    por_minuto = entero_env("AGENT_IA_MAX_POR_MINUTO", 5)
    por_dia = entero_env("AGENT_IA_MAX_POR_DIA", 60) * (5 if es_admin else 1)
    ahora = time.monotonic()
    hoy = date.today().isoformat()
    with _LOCK:
        ventana = [t for t in _VENTANA_MINUTO.get(usuario, []) if ahora - t < 60]
        if len(ventana) + cantidad > por_minuto:
            _VENTANA_MINUTO[usuario] = ventana
            raise LimiteExcedido("Demasiadas solicitudes con IA en poco tiempo", 60)
        if _USO_DIA.get((usuario, hoy), 0) + cantidad > por_dia:
            raise LimiteExcedido("Presupuesto diario de IA agotado", 3600)
        ventana.extend([ahora] * cantidad)
        _VENTANA_MINUTO[usuario] = ventana
        for clave in [k for k in _USO_DIA if k[1] != hoy]:
            del _USO_DIA[clave]
        _USO_DIA[(usuario, hoy)] = _USO_DIA.get((usuario, hoy), 0) + cantidad


def consumir_prediccion(usuario: str, *, cantidad: int = 1) -> None:
    """Tope de predicciones por usuario (el administrador no lo usa). Cada predicción consulta APIs
    externas con cuota compartida con el bot, así que un bot abierto a todos necesita un límite propio:
    `AGENT_PREDICCIONES_MAX_POR_DIA` (def. 15) y `AGENT_PREDICCIONES_MAX_POR_MINUTO` (def. 3)."""
    por_minuto = entero_env("AGENT_PREDICCIONES_MAX_POR_MINUTO", 3)
    por_dia = entero_env("AGENT_PREDICCIONES_MAX_POR_DIA", 15)
    clave = f"{usuario}:pred"
    ahora = time.monotonic()
    hoy = date.today().isoformat()
    with _LOCK:
        ventana = [t for t in _VENTANA_MINUTO.get(clave, []) if ahora - t < 60]
        if len(ventana) + cantidad > por_minuto:
            _VENTANA_MINUTO[clave] = ventana
            raise LimiteExcedido("Demasiadas predicciones seguidas", 60)
        if _USO_DIA.get((clave, hoy), 0) + cantidad > por_dia:
            raise LimiteExcedido("Alcanzaste el máximo de predicciones de hoy", 3600)
        ventana.extend([ahora] * cantidad)
        _VENTANA_MINUTO[clave] = ventana
        _USO_DIA[(clave, hoy)] = _USO_DIA.get((clave, hoy), 0) + cantidad


def consultar_uso_ia(usuario: str) -> tuple[list[float], int]:
    """Solo lectura: (instantes monotónicos de las llamadas de IA del último minuto, ordenados; usadas hoy).
    API pública para mostrar el cupo restante (`agent_capacidades`) sin acceder a los contadores privados
    ni gastar cupo."""
    ahora = time.monotonic()
    hoy = date.today().isoformat()
    with _LOCK:
        ventana = sorted(t for t in _VENTANA_MINUTO.get(usuario, []) if ahora - t < 60)
        usadas_dia = _USO_DIA.get((usuario, hoy), 0)
    return ventana, usadas_dia


_VENTANA_CHAT: dict[str, list[float]] = {}


def consumir_mensaje_chat(clave: str, por_minuto: int | None = None) -> bool:
    """Rate limit simple por chat (Telegram). Devuelve False si se superó el tope."""
    tope = por_minuto or entero_env("AGENT_TELEGRAM_RATE_PER_MIN", 10)
    ahora = time.monotonic()
    with _LOCK:
        ventana = [t for t in _VENTANA_CHAT.get(clave, []) if ahora - t < 60]
        if len(ventana) >= tope:
            _VENTANA_CHAT[clave] = ventana
            return False
        ventana.append(ahora)
        _VENTANA_CHAT[clave] = ventana
        return True


def host_confiable(url: str) -> bool:
    """Solo se reenvían credenciales a loopback o a hosts listados explícitamente."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        pass
    return host in {h.lower() for h in lista_env("AGENT_SPORTS_TRUSTED_HOSTS")}


def token_servicio(user_id: str, *, admin: bool = False, segundos: int = 120) -> str:
    """JWT interno de vida corta para que tareas y Telegram llamen al backend deportivo.

    Mismo secreto y formato que la sesión web, pero con rol `user` salvo que el llamador ya haya
    verificado al administrador (aprobaciones). Marca `svc=agent` para poder auditarlo."""
    ahora = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "rol": "admin" if admin else "user", "svc": "agent", "iat": ahora, "exp": ahora + timedelta(seconds=segundos)},
        settings.WEB_JWT_SECRET,
        algorithm="HS256",
    )


def autorizacion_sports(user_id: str, bearer: str | None = None, *, admin: bool = False) -> str | None:
    """Cabecera `Authorization` para el backend deportivo, o None si el destino no es confiable.

    Prefiere el Bearer real del usuario (web/Android); sin él (tareas, Telegram) emite un token
    de servicio acotado al mismo usuario."""
    if not host_confiable(settings.SPORTS_BACKEND_URL):
        return None
    if bearer:
        return bearer
    return f"Bearer {token_servicio(user_id, admin=admin)}"


# --- Higiene de memoria ----------------------------------------------------------------------

_PATRONES_SECRETO = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|AIzaSy[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|gsk_[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{16,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"
    r"|(?:api[_ -]?key|token|contrase(?:ñ|n)a|password|secret|clave)\s*(?:es|=|:)\s*\S{6,}",
    re.I,
)
_PATRONES_PII = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"  # correo
    r"|\b(?:\d[ -]?){13,19}\b"  # tarjeta
    r"|\+?\d[\d ()-]{8,}\d",  # teléfono
)


def clasificar_memoria(contenido: str) -> tuple[str, str | None]:
    """Devuelve (sensibilidad, contenido_a_guardar).

    - secreto evidente: no se guarda (contenido None) para no persistir credenciales;
    - PII (correo, teléfono, tarjeta): se guarda `sensible`, así nunca se inyecta ni exporta;
    - resto: `normal`."""
    if _PATRONES_SECRETO.search(contenido):
        return "privada", None
    if _PATRONES_PII.search(contenido):
        return "sensible", contenido
    return "normal", contenido
