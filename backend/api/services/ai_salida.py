"""services/ai_salida.py — Salida estructurada (JSON) del análisis con IA, validada en Python, y su conversión al texto de siempre.

Por qué: pedir un formato de emojis y sacar el pick con regex falla en silencio cuando cambia el modelo o el proveedor (`bot/02` §5.2, defecto P4/P7). Ahora el prompt pide un JSON
(`analisis.v1`), se valida (tipos, largos, el pick debe ser UNO de los tres posibles) y se renderiza al mismo texto con la línea `⚖️ Balance y PICK:`, de modo que
`consenso_ia.combinar_con_claude`, el control de cifras y los mensajes no cambian. Si la IA devuelve el formato antiguo (texto), se acepta tal cual (degradación); si
devuelve algo que parece JSON pero no cumple el esquema, se rechaza (`SalidaInvalida`) y el análisis cae al modo solo estadístico: nunca se publica un pick inventado.
Los nombres de campos se toman como datos: todo texto se sanea y se escapa para HTML (Telegram usa parse_mode HTML).
"""
from __future__ import annotations

import html
import json
import re

from backend.api.services.ai_prompts import sanear_texto

VERSION_ESQUEMA = "analisis.v1"
LIMITE_DATO, LIMITE_LECTURA = 140, 280

# JSON Schema del contrato (documentación y, más adelante, `output_config.format`/`response_schema` de los proveedores que lo admiten).
ESQUEMA_ANALISIS_V1 = {
    "type": "object", "additionalProperties": False, "required": ["version", "dato_local", "dato_visitante", "lectura", "pick"],
    "properties": {
        "version": {"type": "string", "enum": [VERSION_ESQUEMA]},
        "dato_local": {"type": "string"}, "dato_visitante": {"type": "string"}, "lectura": {"type": "string"},
        "pick": {"type": "string", "description": "Exactamente el nombre del equipo local, el del visitante o la palabra Empate"},
    },
}


class SalidaInvalida(ValueError):
    """La respuesta de la IA parece JSON pero no cumple el esquema."""


_CERCADO = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S | re.I)


def extraer_json(texto: str) -> str | None:
    """Fragmento JSON del texto (con o sin cercado ```), o None si no hay llaves."""
    t = (texto or "").strip()
    m = _CERCADO.search(t)
    if m:
        return m.group(1)
    if t.startswith("{"):
        return t[: t.rfind("}") + 1] if "}" in t else t  # un JSON truncado también cuenta como JSON (y se rechaza al validarlo)
    return None


def _pick_valido(pick: str, local: str, visitante: str) -> str:
    from backend.api.services.consenso_ia import _mapear_pick, _normalizar_pick

    categoria = _normalizar_pick(pick, local, visitante)
    if categoria == "indeterminado":
        raise SalidaInvalida(f"pick no reconocido: {sanear_texto(pick, 40)!r}")
    return _mapear_pick(categoria, local, visitante)


def validar_analisis(obj: object, local: str, visitante: str) -> dict:
    if not isinstance(obj, dict):
        raise SalidaInvalida("la salida no es un objeto JSON")
    faltan = [k for k in ESQUEMA_ANALISIS_V1["required"] if k not in obj]
    if faltan:
        raise SalidaInvalida(f"faltan campos: {', '.join(faltan)}")
    extra = set(obj) - set(ESQUEMA_ANALISIS_V1["properties"])
    if extra:
        raise SalidaInvalida(f"campos no permitidos: {', '.join(sorted(extra))}")
    if obj["version"] != VERSION_ESQUEMA:
        raise SalidaInvalida(f"versión de esquema desconocida: {sanear_texto(obj['version'], 20)!r}")
    for clave in ("dato_local", "dato_visitante", "lectura", "pick"):
        if not isinstance(obj[clave], str) or not obj[clave].strip():
            raise SalidaInvalida(f"campo vacío o con tipo erróneo: {clave}")
    return {
        "dato_local": sanear_texto(obj["dato_local"], LIMITE_DATO), "dato_visitante": sanear_texto(obj["dato_visitante"], LIMITE_DATO),
        "lectura": sanear_texto(obj["lectura"], LIMITE_LECTURA), "pick": _pick_valido(obj["pick"], local, visitante),
    }


def a_texto(salida: dict, d: dict) -> str:
    """Texto con el formato de siempre. H2H y cuotas las pone el sistema desde los datos, no la IA (menos riesgo de que las copie mal)."""
    esc = lambda v: html.escape(str(v), quote=False)  # noqa: E731
    local = sanear_texto(d.get("local", "Local")) or "Local"
    visitante = sanear_texto(d.get("visitante", "Visitante")) or "Visitante"
    partido = sanear_texto(d.get("partido")) or f"{local} vs {visitante}"
    h2h = sanear_texto(d.get("h2h_resumen", "Sin historial directo disponible."), 600, True)
    odds = sanear_texto(d.get("odds_info", "Sin odds disponibles — análisis estadístico puro."), 300)
    return (
        f"🏆 {esc(partido)}\n📍 {esc(sanear_texto(d.get('liga', '')))}\n\nDATOS\n\n"
        f"📈 {esc(local)}: {esc(salida['dato_local'])}\n📈 {esc(visitante)}: {esc(salida['dato_visitante'])}\n\n"
        f"📜 H2H:\n{esc(h2h)}\n\n💰 Odds: {esc(odds)}\n\n🧠 Lectura: {esc(salida['lectura'])}\n\n"
        f"⚖️ Balance y PICK: {esc(salida['pick'])}"
    )


def normalizar_salida_analisis(texto_ia: str, d: dict) -> tuple[str, str]:
    """(texto con formato de siempre, «json» o «texto»). Lanza `SalidaInvalida` si parece JSON y no cumple el esquema."""
    fragmento = extraer_json(texto_ia)
    if fragmento is None:
        return texto_ia, "texto"
    try:
        obj = json.loads(fragmento)
    except ValueError as exc:
        raise SalidaInvalida("JSON mal formado") from exc
    local = sanear_texto(d.get("local", "Local")) or "Local"
    visitante = sanear_texto(d.get("visitante", "Visitante")) or "Visitante"
    return a_texto(validar_analisis(obj, local, visitante), d), "json"
