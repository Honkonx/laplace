"""ai_herramientas.py — llamadas a herramientas NATIVAS del proveedor de IA (Gemini y los de formato OpenAI: Groq y OpenRouter), con el mismo enrutamiento y métricas de `ai_client`.

La IA decide si necesita una herramienta (p. ej. `laplace_pronosticar`), el servidor la ejecuta —solo las que el llamador registró, con argumentos acotados y resultado truncado— y le devuelve el
resultado para que redacte la respuesta. La IA NUNCA inventa probabilidades: o las cita de la herramienta o no las da. Si ningún proveedor admite herramientas o fallan, `consultar` lanza
`AnalisisIAError` y el llamador cae al camino de texto de siempre (`ai_client.generar_texto_ia`). Ejecutar es siempre del servidor; la IA solo pide.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from backend.api.services import ai_client, ai_metrics

log = logging.getLogger("laplace.ai_herramientas")

PROVEEDORES_CON_HERRAMIENTAS = ("gemini", "groq", "openrouter")
MAX_VUELTAS = 3
MAX_ARGS_CHARS = 2000
MAX_RESULTADO_CHARS = 6000
PLAZO_HERRAMIENTA_SEGUNDOS = 15.0


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    esquema: dict  # JSON Schema de los argumentos
    ejecutar: Callable[[dict], Awaitable[dict]]


def _truncar(valor: dict) -> str:
    from backend.api.services.agent_saneo import sanear_valor  # noqa: PLC0415 — MS-9: el resultado de una herramienta viene de fuentes de terceros; sus textos se sanean antes de llegar a la IA

    texto = json.dumps(sanear_valor(valor, 300), ensure_ascii=False, default=str)
    return texto if len(texto) <= MAX_RESULTADO_CHARS else texto[:MAX_RESULTADO_CHARS] + '…"'


async def _ejecutar(herramientas: dict[str, Herramienta], nombre: str, args: dict) -> dict:
    """Ejecuta una herramienta registrada; cualquier otra cosa que pida la IA es un error devuelto a la IA (no una ejecución)."""
    h = herramientas.get(nombre)
    if h is None:
        return {"error": f"herramienta desconocida: {nombre}"}
    if len(json.dumps(args, default=str)) > MAX_ARGS_CHARS:
        return {"error": "argumentos demasiado largos"}
    try:
        import asyncio

        return await asyncio.wait_for(h.ejecutar(args), PLAZO_HERRAMIENTA_SEGUNDOS)
    except Exception as exc:  # noqa: BLE001 — el fallo de una herramienta se le cuenta a la IA, no tumba la consulta
        log.warning("herramienta %s falló: %s", nombre, type(exc).__name__)
        return {"error": f"la herramienta falló ({type(exc).__name__})"}


# ---------- adaptadores por proveedor ----------
class _Gemini:
    nombre = "gemini"

    @staticmethod
    def iniciar(prompt: str) -> list:
        return [{"role": "user", "parts": [{"text": prompt}]}]

    @staticmethod
    def pedir(prov, historial: list, herramientas: dict[str, Herramienta], max_tokens: int, temperatura: float) -> dict:
        base = prov.peticion("", max_tokens, temperatura)
        base["json"]["contents"] = historial
        base["json"]["tools"] = [{"functionDeclarations": [{"name": h.nombre, "description": h.descripcion, "parameters": h.esquema} for h in herramientas.values()]}]
        return base

    @staticmethod
    def leer(r: httpx.Response, historial: list) -> tuple[str | None, list[dict]]:
        cand = (r.json().get("candidates") or [{}])[0]
        partes = (cand.get("content") or {}).get("parts") or []
        llamadas = [{"id": p["functionCall"]["name"], "nombre": p["functionCall"]["name"], "args": p["functionCall"].get("args") or {}} for p in partes if "functionCall" in p]
        if llamadas:
            historial.append({"role": "model", "parts": [p for p in partes if "functionCall" in p]})
            return None, llamadas
        return "".join(p.get("text", "") for p in partes if not p.get("thought", False)).strip(), []

    @staticmethod
    def responder(historial: list, llamadas: list[dict], resultados: list[dict]) -> None:
        historial.append({"role": "user", "parts": [{"functionResponse": {"name": c["nombre"], "response": {"resultado": _truncar(res)}}} for c, res in zip(llamadas, resultados)]})


class _OpenAI:
    def __init__(self, nombre: str):
        self.nombre = nombre

    @staticmethod
    def iniciar(prompt: str) -> list:
        return [{"role": "user", "content": prompt}]

    @staticmethod
    def pedir(prov, historial: list, herramientas: dict[str, Herramienta], max_tokens: int, temperatura: float) -> dict:
        base = prov.peticion("", max_tokens, temperatura)
        base["json"]["messages"] = historial
        base["json"]["tools"] = [{"type": "function", "function": {"name": h.nombre, "description": h.descripcion, "parameters": h.esquema}} for h in herramientas.values()]
        return base

    @staticmethod
    def leer(r: httpx.Response, historial: list) -> tuple[str | None, list[dict]]:
        msg = r.json()["choices"][0]["message"]
        pedidas = msg.get("tool_calls") or []
        if pedidas:
            historial.append({"role": "assistant", "content": msg.get("content"), "tool_calls": pedidas})
            llamadas = []
            for t in pedidas:
                try:
                    args = json.loads(t["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                llamadas.append({"id": t["id"], "nombre": t["function"]["name"], "args": args if isinstance(args, dict) else {}})
            return None, llamadas
        return (msg.get("content") or "").strip(), []

    @staticmethod
    def responder(historial: list, llamadas: list[dict], resultados: list[dict]) -> None:
        for c, res in zip(llamadas, resultados):
            historial.append({"role": "tool", "tool_call_id": c["id"], "content": _truncar(res)})


def _adaptador(nombre: str):
    return _Gemini() if nombre == "gemini" else _OpenAI(nombre)


async def _con_proveedor(client: httpx.AsyncClient, nombre: str, prompt: str, herramientas: dict[str, Herramienta], max_tokens: int, temperatura: float,
                         limite: float) -> dict | None:
    prov = ai_client._PROVEEDORES[nombre]  # noqa: SLF001 — mismo registro, claves y modelos que el camino de texto
    if not prov.configurado():
        return None
    ad = _adaptador(nombre)
    historial = ad.iniciar(prompt)
    llamadas_hechas: list[dict] = []
    inicio = time.perf_counter()
    try:
        for _ in range(MAX_VUELTAS + 1):
            plazo = min(prov.timeout, limite - time.monotonic())
            if plazo < 1.0:
                raise TimeoutError("presupuesto de tiempo agotado")
            r = await client.post(prov.url(), timeout=plazo, **ad.pedir(prov, historial, herramientas, max_tokens, temperatura))
            r.raise_for_status()
            texto, llamadas = ad.leer(r, historial)
            if texto is not None:
                ai_metrics.registrar_intento(nombre, exitoso=True, latencia_ms=ai_metrics.ms_desde(inicio), modelo=prov.modelo())
                if not texto:
                    return None
                return {"texto": texto, "proveedor": nombre, "modelo": prov.modelo(), "herramientas_usadas": llamadas_hechas}
            resultados = [await _ejecutar(herramientas, c["nombre"], c["args"]) for c in llamadas]
            llamadas_hechas += [{"nombre": c["nombre"], "ok": "error" not in res} for c, res in zip(llamadas, resultados)]
            ad.responder(historial, llamadas, resultados)
        raise RuntimeError("la IA siguió pidiendo herramientas sin responder")
    except Exception as exc:  # noqa: BLE001
        ai_metrics.registrar_intento(nombre, exitoso=False, latencia_ms=ai_metrics.ms_desde(inicio), modelo=prov.modelo(), error=ai_metrics.sanitizar_error(str(exc)))
        log.warning("%s con herramientas falló (%s)", nombre, type(exc).__name__)
        return None


async def consultar(prompt: str, herramientas: list[Herramienta], rol: str = "agente", max_tokens: int = 1024, temperatura: float | None = None) -> dict:
    """Pregunta a la IA dándole `herramientas`. Devuelve `{texto, proveedor, modelo, herramientas_usadas}`; lanza `AnalisisIAError` si ningún proveedor lo logra."""
    registro = {h.nombre: h for h in herramientas}
    temp = ai_client.settings.AI_TEMPERATURE if temperatura is None else temperatura
    limite = time.monotonic() + ai_client.PRESUPUESTO_TOTAL_SEGUNDOS
    async with httpx.AsyncClient() as client:
        for nombre in ai_client.orden_proveedores(rol):
            if nombre not in PROVEEDORES_CON_HERRAMIENTAS:
                continue
            salida = await _con_proveedor(client, nombre, prompt, registro, max_tokens, temp, limite)
            if salida:
                return salida
    raise ai_client.AnalisisIAError("ningún proveedor de IA con herramientas respondió")


def herramienta_modelo_laplace() -> Herramienta:
    """La herramienta `laplace_pronosticar`: pronóstico del modelo propio (solo números validados), sin publicar nada."""
    from backend.api.ml.laplace import servicio
    from backend.api.routers.ml_modelo import DEFINICION_HERRAMIENTA as d

    async def ejecutar(args: dict) -> dict:
        salida = servicio.pronosticar_partido(None, {"local": args.get("local"), "visitante": args.get("visitante"), "liga": args.get("liga") or ""}, canal="http")
        return servicio.resumen_para_consumidores(salida) or {"error": salida.get("motivo", "sin pronóstico")}

    return Herramienta(d["name"], d["description"], d["input_schema"], ejecutar)
