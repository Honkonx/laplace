"""services/agent_ia_herramientas.py — modo CON IA con llamada nativa a herramientas, con control de cifras en código (MA-34).

La IA recibe un catálogo CERRADO de herramientas de lectura (pronóstico del modelo propio, últimos resultados, comparación de perfiles), las llama en un bucle corto
(`ai_herramientas.MAX_VUELTAS`) y redacta con lo que devolvieron. La confianza no se le pide a la IA: en código se comprueba que cada cifra del texto final aparezca en lo que
devolvió alguna herramienta o en el propio mensaje del usuario; si hay una cifra ajena el texto se descarta y quien llama usa la respuesta sin herramientas.
Apagado por defecto (`AGENT_FUNCTION_CALLING`): necesita un proveedor con herramientas (Gemini, Groq u OpenRouter) y claves reales.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from backend.api.services import agent_tools_extra, ai_herramientas
from backend.api.services.ai_herramientas import Herramienta

log = logging.getLogger("laplace.agent.fc")

_NUMERO = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
NUMEROS_LIBRES = {"0", "1", "2", "3", "4", "5", "10"}  # conteos y marcadores chicos que la IA puede decir sin que sean una cifra del modelo (p. ej. «los 2 equipos»)


def _normalizar_numero(txt: str) -> str:
    n = txt.replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return n


def cifras_ajenas(texto: str, respaldos: list[str]) -> list[str]:
    """Números del texto que no aparecen en ninguno de los `respaldos` (JSON de herramientas o mensaje del usuario). Los porcentajes se comparan como proporción y como porcentaje."""
    permitidos: set[str] = set()
    for r in respaldos:
        for n in _NUMERO.findall(r):
            v = _normalizar_numero(n)
            permitidos.add(v)
            try:
                f = float(v)
                permitidos.update({_normalizar_numero(f"{f * 100:.1f}"), _normalizar_numero(f"{f * 100:.0f}")})
                if f > 1:
                    permitidos.add(_normalizar_numero(f"{f / 100:.3f}"))
            except ValueError:
                continue
    ajenas = []
    for n in _NUMERO.findall(texto):
        v = _normalizar_numero(n)
        if v in permitidos or v in NUMEROS_LIBRES:
            continue
        try:  # redondeos razonables: 45,2 se acepta si la herramienta dio 45,19
            if any(abs(float(v) - float(p)) <= 0.06 for p in permitidos if re.fullmatch(r"\d+(?:\.\d+)?", p)):
                continue
        except ValueError:
            pass
        ajenas.append(n)
    return ajenas


def catalogo(db: Session, registro: list[str]) -> list[Herramienta]:
    """Herramientas de lectura que la IA puede llamar; cada resultado se anota en `registro` para el control de cifras."""
    base = ai_herramientas.herramienta_modelo_laplace()

    def anotar(h: Herramienta) -> Herramienta:
        async def ejecutar(args: dict) -> dict:
            r = await h.ejecutar(args)
            registro.append(json.dumps(r, ensure_ascii=False, default=str))
            return r
        return Herramienta(h.nombre, h.descripcion, h.esquema, ejecutar)

    async def resultados(args: dict) -> dict:
        r = agent_tools_extra.resultados_recientes(db, str(args.get("equipo", "")), int(args.get("limite", 5) or 5))
        return {"estado": r["estado"], "resultados": r.get("data", [])}

    async def comparar(args: dict) -> dict:
        r = agent_tools_extra.comparar_perfiles(str(args.get("equipo_a", "")), str(args.get("equipo_b", "")))
        return {"estado": r["estado"], "texto": r["texto"]}

    extra = [
        Herramienta("resultados_recientes", "Últimos resultados terminados de un equipo (base local, máximo 10).",
                    {"type": "object", "properties": {"equipo": {"type": "string"}, "limite": {"type": "integer"}}, "required": ["equipo"], "additionalProperties": False}, resultados),
        Herramienta("comparar_perfiles", "Perfiles de dos equipos lado a lado; no pronostica.",
                    {"type": "object", "properties": {"equipo_a": {"type": "string"}, "equipo_b": {"type": "string"}}, "required": ["equipo_a", "equipo_b"], "additionalProperties": False}, comparar),
    ]
    return [anotar(base)] + [anotar(h) for h in extra]


async def responder(db: Session, mensaje: str, prompt: str, consultar: Callable[..., Awaitable[dict]] | None = None) -> dict | None:
    """Respuesta de la IA con herramientas y cifras verificadas, o None si no hubo herramienta usada, falló o inventó una cifra (quien llama usa su respaldo)."""
    registro: list[str] = []
    herramientas = catalogo(db, registro)
    try:
        r = await (consultar or ai_herramientas.consultar)(prompt, herramientas, rol="agente", max_tokens=700)
    except Exception as exc:  # noqa: BLE001 — sin proveedor con herramientas o error de red: se usa el camino sin herramientas
        log.warning("function calling no disponible: %s", type(exc).__name__)
        return None
    texto = (r.get("texto") or "").strip()
    if not texto or not registro:
        return None  # si no llamó a ninguna herramienta no hay nada que respalde sus cifras
    ajenas = cifras_ajenas(texto, registro + [mensaje])
    if ajenas:
        log.warning("respuesta con herramientas descartada por cifras ajenas: %s", ajenas[:3])
        return None
    return {"texto": texto, "proveedor": r.get("proveedor"), "modelo": r.get("modelo"), "herramientas_usadas": r.get("herramientas_usadas", [])}
