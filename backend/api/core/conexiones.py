"""core/conexiones.py — registro ÚNICO de las conexiones externas de Laplace (APIs de datos, IA y Telegram).

Una sola lista de la que leen: el script `configurar` (install/comun/configurar.py), el panel web «Conexiones» (routers/admin.py), `doctor`, las listas de
proveedores de IA y de fuentes del panel, y los tests que comprueban que `.env.example` y `requisitos.md` no se desalinean. Antes la lista estaba repetida en 7 sitios
y ya se había desalineado (INVENTARIO_APIS_Y_CLAVES_2026-11-09.md).

Solo librería estándar y sin importar la configuración: lo usan scripts que corren antes de que el backend exista. Cada conexión dice cómo se prueba una clave **sin gastar
cuota** (probado con claves reales el 2026-11-09); las dos excepciones (LiveScore6 cobra cada llamada; Ollama Cloud cuesta ≈ 1 token) se marcan y solo se prueban si el usuario lo pide.
Regla de validez: respuesta 2xx **y** sin `errors` en el cuerpo cuando el proveedor los usa (api-football devuelve HTTP 200 con `errors` si la clave es inválida).
"""
from __future__ import annotations

import logging
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

log = logging.getLogger("laplace.conexiones")

ESTADO_OK, ESTADO_FALLA, ESTADO_AVISO = "ok", "bad", "warn"
# Misma expresión que `services/admin_env.py`: un valor así no puede abrir una línea nueva en `.env`.
_FORMATO_CLAVE = re.compile(r"^[A-Za-z0-9._~+/=:@-]{8,512}$")
_MARCADORES = ("your_", "replace_with", "changeme", "tu_", "comma,separated", "<")
# Cloudflare (delante de Groq y otros) bloquea el User-Agent por defecto de urllib con «error code: 1010»: sin esto una clave válida salía como inválida (2026-11-09).
USER_AGENT = "Laplace-configurar/1.0 (+comprobacion-de-clave)"


@dataclass(frozen=True)
class Prueba:
    """Cómo comprobar una clave contra el host oficial. `{clave}` se sustituye en URL, cabeceras y consulta."""

    url: str
    metodo: str = "GET"
    cabeceras: tuple[tuple[str, str], ...] = ()
    consulta: tuple[tuple[str, str], ...] = ()
    cuerpo_json: dict | None = None
    invalida_si: tuple[int, ...] = (400, 401, 403)
    errores_en_cuerpo: bool = False          # api-football: HTTP 200 + `errors` no vacío = clave inválida
    ok_json: tuple[str, object] | None = None  # Telegram: el cuerpo debe traer {"ok": true}
    lectura: tuple[str, str] | None = None     # cabecera que informa de la cuota, y su formato («{} créditos»)
    cobra_por_llamada: bool = False          # LiveScore6: cada llamada gasta cuota → solo si el usuario lo pide
    cuesta: str | None = None                # Ollama Cloud: «≈ 1 token» → solo si el usuario lo acepta


@dataclass(frozen=True)
class Conexion:
    id: str
    numero: int
    grupo: str
    nombre: str
    variable: str
    sirve: str
    plan: str
    enlace: str
    host: str
    prueba: Prueba
    destacada: bool = False
    ia: str | None = None                    # id del proveedor en `ai_client` / `AI_ROUTING_*`
    modelo_variable: str | None = None
    modelo_defecto: str | None = None
    rol_panel: str = ""                      # texto corto del rol para el panel de fuentes


@dataclass(frozen=True)
class Grupo:
    id: str
    titulo: str
    nota: str = ""


@dataclass
class Resultado:
    estado: str
    detalle: str
    http: int | None = None
    extra: str = ""


GRUPOS: tuple[Grupo, ...] = (
    Grupo("partidos", "PARTIDOS Y CALENDARIO", "gana el primero que responda: BD → LiveScore6 → BSD → api-football (orden fijo hoy)"),
    Grupo("cuotas", "CUOTAS DEL MERCADO", "el insumo principal del pronóstico si no tienes modelo propio"),
    Grupo("tablas", "TABLAS DE POSICIONES"),
    Grupo("ia", "IA (explica, nunca calcula probabilidades)", "orden configurable: se usa la primera que responda"),
    Grupo("telegram", "TELEGRAM"),
)

_BEARER = (("Authorization", "Bearer {clave}"),)

CONEXIONES: tuple[Conexion, ...] = (
    Conexion("livescore6", 1, "partidos", "LiveScore6 (RapidAPI)", "LIVESCORE6_KEY", "calendario principal del día", "cuota de tu plan en RapidAPI",
             "https://rapidapi.com", "livescore6.p.rapidapi.com",
             Prueba("https://livescore6.p.rapidapi.com/matches/v2/list-by-date", cabeceras=(("x-rapidapi-key", "{clave}"), ("x-rapidapi-host", "livescore6.p.rapidapi.com")),
                    consulta=(("Category", "soccer"), ("Date", "{hoy}")), invalida_si=(401, 403), cobra_por_llamada=True),
             rol_panel="fixtures primarios"),
    Conexion("bsd", 2, "partidos", "BSD", "BSD_API_KEY", "calendario alterno, xG, lesionados y predicción externa", "según plan", "https://sports.bzzoiro.com",
             "sports.bzzoiro.com", Prueba("https://sports.bzzoiro.com/api/v2/events/", cabeceras=(("Authorization", "Token {clave}"),), consulta=(("limit", "1"),)),
             rol_panel="xG, lesionados, H2H y predicción externa"),
    Conexion("api-football", 3, "partidos", "api-football", "SPORTS_API_KEY", "calendario de respaldo, H2H, estadísticas y resultados", "100 peticiones al día y 10 por minuto",
             "https://www.api-football.com", "v3.football.api-sports.io",
             Prueba("https://v3.football.api-sports.io/status", cabeceras=(("x-apisports-key", "{clave}"),), errores_en_cuerpo=True,
                    lectura=("x-ratelimit-requests-remaining", "{} restantes hoy")),
             rol_panel="fixtures fallback, odds, H2H, estadísticas y resultados"),
    Conexion("the-odds-api", 4, "cuotas", "The Odds API", "THE_ODDS_API_KEY", "cuotas 1X2 y totales: el insumo principal del pronóstico", "≈ 500 créditos al mes",
             "https://the-odds-api.com", "api.the-odds-api.com",
             Prueba("https://api.the-odds-api.com/v4/sports/", consulta=(("apiKey", "{clave}"),), lectura=("x-requests-remaining", "{} créditos")),
             destacada=True, rol_panel="odds 1X2 y totales"),
    Conexion("oddspapi", 5, "cuotas", "OddsPapi (sharp)", "ODDSPAPI_SHARP_KEY", "mercado «sharp» y value (opcional)", "según plan", "https://oddspapi.io",
             "api.oddspapi.io", Prueba("https://api.oddspapi.io/v4/account", consulta=(("apiKey", "{clave}"),)), rol_panel="mercado sharp y value"),
    Conexion("football-data", 6, "tablas", "football-data.org", "FOOTBALL_DATA_KEY", "tablas de posiciones", "plan gratis del proveedor", "https://www.football-data.org",
             "api.football-data.org", Prueba("https://api.football-data.org/v4/competitions/PD", cabeceras=(("X-Auth-Token", "{clave}"),)),
             rol_panel="tablas y forma para ligas cubiertas"),
    Conexion("ollama_cloud", 7, "ia", "Ollama Cloud", "OLLAMA_API_KEY", "IA principal (modelo gpt-oss:120b)", "plan gratis con modelos en la nube", "https://ollama.com/settings/keys",
             "ollama.com",
             Prueba("https://ollama.com/api/chat", metodo="POST", cabeceras=_BEARER,
                    cuerpo_json={"model": "gpt-oss:120b", "messages": [{"role": "user", "content": "hola"}], "stream": False, "options": {"num_predict": 1}}, cuesta="≈ 1 token"),
             ia="ollama_cloud", modelo_variable="OLLAMA_CLOUD_MODEL", modelo_defecto="gpt-oss:120b"),
    Conexion("groq", 8, "ia", "Groq", "GROQ_API_KEY", "IA de respaldo", "plan gratis", "https://console.groq.com", "api.groq.com",
             Prueba("https://api.groq.com/openai/v1/models", cabeceras=_BEARER), ia="groq", modelo_variable="GROQ_MODEL", modelo_defecto="openai/gpt-oss-120b"),
    Conexion("gemini", 9, "ia", "Google Gemini", "GOOGLE_API_KEY", "IA de respaldo", "plan gratis", "https://aistudio.google.com", "generativelanguage.googleapis.com",
             Prueba("https://generativelanguage.googleapis.com/v1beta/models", consulta=(("key", "{clave}"),)), ia="gemini", modelo_variable="GEMINI_MODEL",
             modelo_defecto="gemini-flash-lite-latest"),
    Conexion("openrouter", 10, "ia", "OpenRouter", "OPENROUTER_API_KEY", "IA de respaldo (modelos :free)", "plan gratis", "https://openrouter.ai/keys", "openrouter.ai",
             Prueba("https://openrouter.ai/api/v1/auth/key", cabeceras=_BEARER), ia="openrouter", modelo_variable="OPENROUTER_MODEL",
             modelo_defecto="nvidia/nemotron-3-super-120b-a12b:free"),
    Conexion("claude", 11, "ia", "Claude (Anthropic)", "ANTHROPIC_API_KEY", "IA de último recurso", "de pago", "https://console.anthropic.com", "api.anthropic.com",
             Prueba("https://api.anthropic.com/v1/models", cabeceras=(("x-api-key", "{clave}"), ("anthropic-version", "2023-06-01"))), ia="claude",
             modelo_variable="CLAUDE_MODEL", modelo_defecto="claude-sonnet-4-6"),
    Conexion("telegram", 12, "telegram", "Bot principal", "TELEGRAM_BOT_TOKEN", "el bot de Telegram (sin él no arranca)", "gratis", "https://t.me/BotFather",
             "api.telegram.org", Prueba("https://api.telegram.org/bot{clave}/getMe", ok_json=("ok", True), invalida_si=(400, 401, 403, 404))),
    Conexion("telegram-agente", 13, "telegram", "Bot del agente", "AGENT_TELEGRAM_BOT_TOKEN", "el agente de chat por Telegram (opcional)", "gratis", "https://t.me/BotFather",
             "api.telegram.org", Prueba("https://api.telegram.org/bot{clave}/getMe", ok_json=("ok", True), invalida_si=(400, 401, 403, 404))),
)

# Variables que no son claves de un proveedor pero se configuran desde el script (letra `a` y `c` de la lista).
VARIABLE_ADMIN_TELEGRAM = "SPORTS_ADMIN_IDS"
VARIABLES_COMUNIDAD = ("TELEGRAM_CANAL_ID", "TELEGRAM_GRUPO_URL", "TELEGRAM_GRUPO_NOMBRE")
ROLES_IA = ("AI_ROUTING_BOT", "AI_ROUTING_CANAL", "AI_ROUTING_AGENTE", "AI_ROUTING_LABORATORIO")
CALENDARIO = ("livescore6", "bsd", "api-football")
CUOTAS_PRINCIPAL = "the-odds-api"


def por_id(identificador: str) -> Conexion | None:
    return next((c for c in CONEXIONES if c.id == identificador), None)


def por_numero(numero: int) -> Conexion | None:
    return next((c for c in CONEXIONES if c.numero == numero), None)


def por_variable(variable: str) -> Conexion | None:
    return next((c for c in CONEXIONES if c.variable == variable), None)


def variables_de_claves() -> tuple[str, ...]:
    return tuple(c.variable for c in CONEXIONES)


def proveedores_ia() -> tuple[Conexion, ...]:
    return tuple(c for c in CONEXIONES if c.ia)


def variables_declaradas() -> set[str]:
    """Todas las variables de `.env` que este registro conoce (para los tests de alineación)."""
    extra = {VARIABLE_ADMIN_TELEGRAM, *VARIABLES_COMUNIDAD, *ROLES_IA}
    return {c.variable for c in CONEXIONES} | {c.modelo_variable for c in CONEXIONES if c.modelo_variable} | extra


def valor_definido(valor: str | None) -> bool:
    """Una clave cuenta como puesta si no está vacía ni es un marcador de lugar del ejemplo."""
    texto = (valor or "").strip()
    return bool(texto) and not texto.lower().startswith(_MARCADORES)


def formato_invalido(valor: str) -> str | None:
    """Motivo por el que un valor NO puede guardarse en `.env` como clave, o None si el formato es válido."""
    if any(ord(c) < 32 or ord(c) == 127 for c in valor):
        return "la clave no puede contener saltos de línea ni caracteres de control"
    if not _FORMATO_CLAVE.fullmatch(valor.strip()):
        return "la clave debe tener entre 8 y 512 caracteres, sin espacios, comillas ni símbolos especiales (¿la copiaste completa?)"
    return None


def faltantes_para_pronosticar(definidas: set[str]) -> list[str]:
    """Qué falta para tener pronósticos (sin red): cuotas del mercado y al menos un calendario. `definidas` = ids de conexiones con clave."""
    faltan = []
    if CUOTAS_PRINCIPAL not in definidas:
        faltan.append("sin clave de cuotas (The Odds API): sin modelo propio no habrá pronósticos")
    if not any(c in definidas for c in CALENDARIO):
        faltan.append("sin ningún calendario (LiveScore6, BSD o api-football): no se verán partidos")
    return faltan


def _sustituir(texto: str, clave: str, hoy: str) -> str:
    return texto.replace("{clave}", clave).replace("{hoy}", hoy)


def armar_peticion(conexion: Conexion, clave: str, hoy: str | None = None) -> tuple[str, str, dict[str, str], bytes | None]:
    """(método, url, cabeceras, cuerpo) listos para enviar al host oficial de la conexión."""
    hoy = hoy or datetime.now().strftime("%Y%m%d")
    p = conexion.prueba
    url = _sustituir(p.url, clave, hoy)
    if p.consulta:
        from urllib.parse import urlencode

        url += "?" + urlencode([(k, _sustituir(v, clave, hoy)) for k, v in p.consulta])
    cabeceras = {k: _sustituir(v, clave, hoy) for k, v in p.cabeceras}
    cabeceras.setdefault("User-Agent", USER_AGENT)
    cuerpo = None
    if p.cuerpo_json is not None:
        cuerpo = json.dumps(p.cuerpo_json).encode("utf-8")
        cabeceras["Content-Type"] = "application/json"
    return p.metodo, url, cabeceras, cuerpo


def _limpiar(texto: str, clave: str) -> str:
    """Nunca devolver la clave, ni en un mensaje de error."""
    for fragmento in {clave, clave.strip()}:
        if fragmento:
            texto = texto.replace(fragmento, "***")
    return texto


def evaluar(conexion: Conexion, estado_http: int, cabeceras: dict[str, str], cuerpo: str) -> Resultado:
    """Interpreta la respuesta de la prueba según la regla de validez (2xx y sin `errors`)."""
    p = conexion.prueba
    minusculas = {k.lower(): v for k, v in cabeceras.items()}
    if estado_http == 403 and re.search(r"error code:?\s*1010|cloudflare", cuerpo or "", re.IGNORECASE):
        return Resultado(ESTADO_AVISO, "el proveedor bloqueó la comprobación (Cloudflare 1010): no es un problema de tu clave", estado_http)
    if estado_http in p.invalida_si:
        return Resultado(ESTADO_FALLA, f"clave inválida (HTTP {estado_http})", estado_http)
    if estado_http == 429:
        return Resultado(ESTADO_AVISO, "límite de uso alcanzado (HTTP 429): la clave puede estar bien", estado_http)
    if estado_http >= 500:
        return Resultado(ESTADO_AVISO, f"el proveedor no respondió bien (HTTP {estado_http})", estado_http)
    if not 200 <= estado_http < 300:
        return Resultado(ESTADO_AVISO, f"respuesta inesperada (HTTP {estado_http})", estado_http)
    datos = None
    if p.errores_en_cuerpo or p.ok_json:
        try:
            datos = json.loads(cuerpo) if cuerpo else {}
        except ValueError:
            datos = {}
    if p.errores_en_cuerpo and isinstance(datos, dict) and datos.get("errors"):
        errores = datos["errors"]
        motivo = next(iter(errores.values())) if isinstance(errores, dict) else (errores[0] if errores else "")
        return Resultado(ESTADO_FALLA, f"clave inválida (el proveedor responde: {str(motivo)[:70]})", estado_http)
    if p.ok_json and (not isinstance(datos, dict) or datos.get(p.ok_json[0]) != p.ok_json[1]):
        return Resultado(ESTADO_FALLA, "el proveedor no aceptó la clave", estado_http)
    extra = ""
    if p.lectura and minusculas.get(p.lectura[0].lower()):
        extra = p.lectura[1].format(minusculas[p.lectura[0].lower()])
    return Resultado(ESTADO_OK, "válida" + (f" · {extra}" if extra else ""), estado_http, extra)


def probar(conexion: Conexion, clave: str, abrir: Callable | None = None, timeout: float = 12.0, hoy: str | None = None) -> Resultado:
    """Prueba una clave contra el host oficial. `abrir` se inyecta en los tests (mismo contrato que `urllib.request.urlopen`)."""
    metodo, url, cabeceras, cuerpo = armar_peticion(conexion, clave, hoy)
    peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    abrir = abrir or urllib.request.urlopen
    try:
        with abrir(peticion, timeout=timeout) as respuesta:
            estado = getattr(respuesta, "status", None) or respuesta.getcode()
            return evaluar(conexion, estado, dict(respuesta.headers.items()), respuesta.read(200_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        try:
            cuerpo_error = error.read(20_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            log.debug("conexiones: no se pudo leer el cuerpo del error HTTP", exc_info=True)
            cuerpo_error = ""
        return evaluar(conexion, error.code, dict(error.headers.items()) if error.headers else {}, cuerpo_error)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Resultado(ESTADO_AVISO, "sin respuesta del proveedor (¿hay internet?): " + _limpiar(type(error).__name__, clave))
