"""Herramientas tipadas que el agente puede invocar sobre el bot deportivo.

El agente no importa el runtime del bot ni comparte su proceso. Las consultas pasan por
HTTP para conservar la independencia entre ambos componentes. Las acciones que pueden
generar costo, modificar datos o publicar en Telegram exigen administrador y confirmación.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import time
from typing import Any

import httpx

from backend.api.core.config import settings
from backend.api.services import agent_piezas, conocimiento_equipos, conocimiento_referencia, conocimiento_texto, pronostico_conjunto
from backend.api.services.agent_guard import consumir_prediccion, host_confiable
from backend.api.services.ligas import LIGAS


@dataclass(frozen=True)
class SportsTool:
    name: str
    description: str
    read_only: bool
    admin_only: bool
    requires_confirmation: bool = False


SPORTS_TOOLS = (
    SportsTool("sports.list_leagues", "Lista ligas de fútbol configuradas y su cobertura.", True, False),
    SportsTool("sports.list_fixtures", "Lista partidos y permite filtrar por fecha, liga y equipo.", True, False),
    SportsTool("sports.list_top_picks", "Consulta los Top Picks ya publicados para una fecha.", True, False),
    SportsTool("sports.get_match", "Obtiene un partido concreto por id o por equipos.", True, False),
    SportsTool("sports.predict", "Solicita el análisis estadístico completo de un partido.", True, False),
    SportsTool("sports.get_odds", "Devuelve las cuotas disponibles dentro de los datos del partido.", True, False),
    SportsTool("knowledge.team_profile", "Perfil de un equipo calculado del histórico: forma, goles, local/visitante y frescura del dato.", True, False),
    SportsTool("knowledge.league_profile", "Tasas base, cobertura y frescura de una liga.", True, False),
    SportsTool("knowledge.glossary", "Definición de un término, guía o pregunta frecuente del producto.", True, False),
    SportsTool("sports.recent_results", "Últimos resultados terminados de un equipo según la base local (solo lectura, máximo 10).", True, False),
    SportsTool("knowledge.compare_teams", "Perfiles de dos equipos lado a lado (forma, goles, local/visitante); no pronostica.", True, False),
    SportsTool("modelo.pronosticar", "Pronóstico del modelo Laplace (1X2, goles esperados, marcadores, ambos marcan, más/menos). Solo pronostica: publicar es decisión del agente.", True, False),
    SportsTool("sports.results", "Verifica resultados pendientes del bot.", False, True, True),
    SportsTool("sports.top_picks", "Genera Top Picks y opcionalmente prepara su publicación.", False, True, True),
    SportsTool("sports.publish", "Publica Top Picks en el canal de Telegram.", False, True, True),
)

PLAZO_MODELO_SEGUNDOS = 8.0  # plazo propio del modelo dentro de la consulta en paralelo
PLAZO_BOT_SEGUNDOS = 60.0  # el bot ya limita sus propias consultas externas (hasta ~45 s)
_READ_CACHE: dict[str, tuple[float, dict]] = {}
_REQUEST_WINDOW: list[float] = []
_CACHE_TTL_SECONDS = 15.0
_MAX_REQUESTS_PER_MINUTE = 60


def _politica_publicacion(resultado: dict) -> dict:
    """Decisión de `agent_politica_publicacion` sobre la vista previa de Top Picks. Nunca rompe la herramienta: ante un fallo devuelve el caso conservador."""
    import os

    from backend.api.services import agent_politica_publicacion as politica

    try:
        from sqlalchemy import func

        from backend.api.db.session import SessionLocal
        from backend.api.models.predicciones import PronosticoExperimental as Obs

        with SessionLocal() as db:
            evidencia = int(db.query(func.count(Obs.id)).filter(Obs.variante == "python_baseline", Obs.log_loss.is_not(None)).scalar() or 0)
    except Exception:  # noqa: BLE001
        evidencia = 0
    habilitado = os.getenv("AGENTE_PUBLICA_SOLO", "0").strip().lower() in {"1", "true", "si", "sí", "on"}
    return politica.evaluar((resultado.get("resultado") or resultado) if isinstance(resultado, dict) else {}, evidencia, habilitado)


def _controlar_limite() -> None:
    now = time.monotonic()
    _REQUEST_WINDOW[:] = [stamp for stamp in _REQUEST_WINDOW if now - stamp < 60]
    if len(_REQUEST_WINDOW) >= _MAX_REQUESTS_PER_MINUTE:
        raise RuntimeError("Límite temporal de herramientas deportivas alcanzado")
    _REQUEST_WINDOW.append(now)


def listar_herramientas_deportivas(*, es_admin: bool = True) -> list[dict[str, Any]]:
    """Catálogo de herramientas; sin `es_admin` oculta las exclusivas de administrador."""
    return [asdict(tool) for tool in SPORTS_TOOLS if es_admin or not tool.admin_only]


def _texto_argumento(argumentos: dict[str, Any], *claves: str, requerido: bool = True) -> str | None:
    """Primer argumento de texto presente entre `claves`; valida tipo y largo (≤ 200)."""
    for clave in claves:
        valor = argumentos.get(clave)
        if valor is None or valor == "":
            continue
        if not isinstance(valor, str):
            raise ValueError(f"{clave} debe ser texto")
        valor = valor.strip()
        if len(valor) > 200:
            raise ValueError(f"{clave} es demasiado largo (máximo 200 caracteres)")
        if valor:
            return valor
    if requerido:
        raise ValueError(f"Falta el argumento {claves[0]}")
    return None


def _ejecutar_conocimiento(nombre: str, argumentos: dict[str, Any]) -> dict:
    """Herramientas `knowledge.*`: respuesta determinista desde `knowledge/`, sin red ni IA.

    Devuelve `data` (estructura para pintar), `texto` (mensaje listo para chat) y `estado`."""
    if nombre == "knowledge.compare_teams":
        from backend.api.services import agent_tools_extra

        return agent_tools_extra.comparar_perfiles(_texto_argumento(argumentos, "team_a") or "", _texto_argumento(argumentos, "team_b") or "")
    if nombre == "knowledge.team_profile":
        data = conocimiento_equipos.perfil_equipo(_texto_argumento(argumentos, "team", "equipo") or "", _texto_argumento(argumentos, "league", "liga", requerido=False))
        texto = conocimiento_texto.texto_equipo(data)
    elif nombre == "knowledge.league_profile":
        data = conocimiento_referencia.perfil_liga(_texto_argumento(argumentos, "league", "liga") or "")
        texto = conocimiento_texto.texto_liga(data)
    else:
        data = conocimiento_referencia.buscar_glosario(_texto_argumento(argumentos, "term", "termino") or "")
        texto = conocimiento_texto.texto_glosario(data)
    return {"ok": True, "tool": nombre, "estado": data["estado"], "data": data, "texto": texto}


def _fecha(valor: str | None) -> str:
    raw = (valor or "").strip()
    if not raw:
        return date.today().strftime("%Y%m%d")
    if len(raw) == 8 and raw.isdigit():
        return raw
    try:
        return date.fromisoformat(raw).strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError("La fecha debe usar YYYY-MM-DD o YYYYMMDD") from exc


def _filtrar_partidos(data: dict, args: dict[str, Any]) -> list[dict]:
    partidos = data.get("partidos", data.get("fixtures", []))
    if not partidos and isinstance(data.get("Stages"), list):
        partidos = []
        for stage in data["Stages"]:
            if not isinstance(stage, dict):
                continue
            liga = stage.get("Snm") or stage.get("CompN") or ""
            for event in stage.get("Events", []):
                if not isinstance(event, dict):
                    continue
                local = (event.get("T1") or [{}])[0]
                visitante = (event.get("T2") or [{}])[0]
                partidos.append({"match_id": str(event.get("Eid", "")), "local": local.get("Nm", ""), "visitante": visitante.get("Nm", ""), "liga": liga, "fecha": event.get("Esd"), "status": event.get("Eps"), "raw": event})
    if not isinstance(partidos, list):
        return []
    liga = str(args.get("league", args.get("liga", ""))).strip().casefold()
    equipo = str(args.get("team", args.get("equipo", ""))).strip().casefold()
    resultado = []
    for partido in partidos:
        if not isinstance(partido, dict):
            continue
        texto_liga = str(partido.get("liga", partido.get("league", ""))).casefold()
        texto_equipos = " ".join(str(partido.get(key, "")) for key in ("local", "visitante", "home", "away")).casefold()
        if liga and liga not in texto_liga:
            continue
        if equipo and equipo not in texto_equipos:
            continue
        resultado.append(partido)
    limit = min(max(int(args.get("limit", 50)), 1), 200)
    return resultado[:limit]


class PiezaEnPausa(RuntimeError):
    """La pieza (bot o modelo) falló varias veces seguidas y está en pausa unos segundos: no se la llama para no esperar su plazo completo en cada mensaje."""


def _pieza_de(path: str) -> str:
    return "modelo" if path.startswith("/api/v1/ml/") else "bot"


def registro_de_piezas() -> agent_piezas.RegistroPiezas:
    """Registro de piezas del proceso, con el bot, el modelo y la IA dados de alta la primera vez."""
    registro = agent_piezas.registro_global()
    if not registro.registrada("bot"):
        async def comprobar_bot():
            r = await consultar_capacidades_deportivas()
            return {"ok": bool(r.get("available")), "motivo": r.get("reason", "")}

        async def comprobar_modelo():
            if settings.AGENT_MODELO_EN_PROCESO and _modelo_en_proceso_disponible():
                return {"ok": True}
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"{settings.SPORTS_BACKEND_URL.rstrip('/')}/api/v1/ml/health")
                    r.raise_for_status()
                    return {"ok": bool(r.json().get("modelo_activo")), "motivo": "sin modelo activo" if not r.json().get("modelo_activo") else ""}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "motivo": type(exc).__name__}

        async def comprobar_ia():
            from backend.api.services import ai_client

            return {"ok": any(ai_client._PROVEEDORES[n].configurado() for n in ai_client.orden_proveedores("agente")), "motivo": "sin proveedor de IA configurado"}  # noqa: SLF001

        registro.registrar("bot", "bot", comprobar_bot)
        registro.registrar("modelo", "modelo", comprobar_modelo)
        registro.registrar("ia", "ia", comprobar_ia)
    return registro


async def estado_de_piezas() -> list[dict]:
    """Comprueba ahora cada pieza (con plazo) y devuelve su resumen para `/estado`."""
    registro = registro_de_piezas()
    await registro.comprobar_todas()
    return registro.resumen()


async def _con_pieza(pieza: str, llamada):
    """Llama a una pieza respetando su circuit breaker. Un 4xx o un permiso denegado no es una falla de la pieza (ella respondió)."""
    registro = registro_de_piezas()
    if not registro.permitir(pieza):
        raise PiezaEnPausa(f"{pieza} en pausa por fallos recientes")
    inicio = time.monotonic()
    try:
        valor = await llamada()
    except PermissionError:
        registro.exito(pieza, (time.monotonic() - inicio) * 1000)
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500:
            registro.exito(pieza, (time.monotonic() - inicio) * 1000)
        else:
            registro.fallo(pieza, f"HTTP {exc.response.status_code}")
        raise
    except Exception as exc:
        registro.fallo(pieza, type(exc).__name__)
        raise
    registro.exito(pieza, (time.monotonic() - inicio) * 1000)
    return valor


async def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    return await _con_pieza(_pieza_de(path), lambda: _get_http(path, params))


async def _get_http(path: str, params: dict[str, Any] | None = None) -> dict:
    url = f"{settings.SPORTS_BACKEND_URL.rstrip('/')}{path}"
    cache_key = f"{url}?{sorted((params or {}).items())}"
    cached = _READ_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    _controlar_limite()
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, params=params or {})
                response.raise_for_status()
                data = response.json()
                _READ_CACHE[cache_key] = (time.monotonic(), data)
                return data
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
    raise RuntimeError(f"El bot deportivo no respondió después de 3 intentos: {type(last_error).__name__}")


async def _post(path: str, payload: dict[str, Any], params: dict[str, Any] | None = None, authorization: str | None = None) -> dict:
    return await _con_pieza(_pieza_de(path), lambda: _post_http(path, payload, params, authorization))


async def _post_http(path: str, payload: dict[str, Any], params: dict[str, Any] | None = None, authorization: str | None = None) -> dict:
    url = f"{settings.SPORTS_BACKEND_URL.rstrip('/')}{path}"
    if authorization and not host_confiable(url):
        # Nunca se reenvía una credencial a un destino que no sea loopback o esté en la lista.
        raise PermissionError("El destino del bot deportivo no es de confianza para reenviar credenciales")
    _controlar_limite()
    last_error: Exception | None = None
    # Un análisis completo encadena varias consultas externas (hasta ~45 s con las esperas del límite de api-football):
    # reintentarlo tras un timeout triplicaba la espera (hasta 90 s) y repetía trabajo que el backend sigue haciendo.
    # Solo se reintenta una vez ante un corte de red o un 5xx; un timeout se informa de inmediato (auditoría 2026-10-09).
    async with httpx.AsyncClient(timeout=45.0) as client:
        for attempt in range(2):
            try:
                headers = {"Authorization": authorization} if authorization else None
                response = await client.post(url, json=payload, params=params or {}, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                raise RuntimeError("El análisis tardó demasiado: el backend sigue trabajando, vuelve a consultar en un momento") from exc
            except (httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
    raise RuntimeError(f"El bot deportivo no respondió después de 2 intentos: {type(last_error).__name__}")


def _porcentajes(probabilidades: Any) -> dict[str, float] | None:
    if not isinstance(probabilidades, dict):
        return None
    try:
        return {clave: round(float(probabilidades[clave]) * 100, 1) for clave in ("local", "empate", "visitante")}
    except (KeyError, TypeError, ValueError):
        return None


def _tasa_base(partido: dict[str, Any]) -> dict | None:
    """Tasas históricas reales de la liga (solo si ambos equipos están cubiertos); nunca inventa."""
    try:
        from backend.api.services import modelo_historico

        meta = modelo_historico.tasas_base_liga(partido)
    except Exception:
        return None
    if not meta:
        return None
    return {
        "liga_codigo": meta.get("liga_codigo"), "partidos": meta.get("partidos"), "temporadas": meta.get("temporadas"),
        "pct_local": meta.get("pct_local"), "pct_empate": meta.get("pct_empate"), "pct_visitante": meta.get("pct_visitante"),
        "goles_por_partido": meta.get("goles_por_partido"), "fuente": "football-data.co.uk (histórico medido)",
    }


def resumir_prediccion(data: dict, partido: dict[str, Any]) -> dict:
    """Extrae del análisis completo solo hechos verificables: probabilidades que deciden el pick,
    tasa base de la liga, módulos usados, nivel/confianza y procedencia. Es la ÚNICA fuente de
    cifras que el agente (o un LLM redactor) puede citar."""
    consenso = data.get("consenso", {}) if isinstance(data, dict) else {}
    consenso = consenso if isinstance(consenso, dict) else {}
    modulos = [str(m) for m in consenso.get("modulos_en_consenso", [])] + [str(m) for m in consenso.get("modulos_disidentes", [])]
    sin_pronostico = str(consenso.get("pick_final", "")).startswith("Sin pronóstico") or not consenso.get("pick_final")
    return {
        "pick": None if sin_pronostico else consenso.get("pick_final"),
        "confianza": consenso.get("confianza_final"),
        "nivel": consenso.get("nivel"),
        "prob_ponderada_pct": _porcentajes(consenso.get("prob_ponderada")),
        "modulos_usados": modulos,
        "modulos_a_favor": len(consenso.get("modulos_en_consenso", [])),
        "total_modulos": consenso.get("total_modulos", len(modulos)),
        "tasa_base_liga": _tasa_base(partido),
        # Con "sin pronóstico": por qué y la frecuencia histórica como REFERENCIA (nunca un pick). Los calcula el backend.
        "motivos_sin_pronostico": [str(m) for m in (data.get("motivos_sin_pronostico") or [])][:3] if isinstance(data, dict) else [],
        "referencia_tasa_base": data.get("referencia_tasa_base") if isinstance(data, dict) else None,
        "procedencia": "Consenso ponderado de modelos estadísticos del bot; estimación, no certeza. "
        f"Criterio del pick: {consenso.get('criterio_pick', 'no informado')}.",
    }


async def consultar_capacidades_deportivas() -> dict:
    """Consulta el bot con timeout corto; un fallo nunca rompe el agente."""
    url = f"{settings.SPORTS_BACKEND_URL.rstrip('/')}/capabilities"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return {"available": True, "url": url, "capabilities": response.json()}
    except Exception as exc:
        return {"available": False, "url": url, "reason": type(exc).__name__}


async def _resumen_modelo(argumentos: dict[str, Any]) -> dict | None:
    """Pronóstico compacto del modelo Laplace para acompañar al del bot; None si el modelo no responde o no cubre el partido (el agente sigue con el bot)."""
    from backend.api.ml.laplace.servicio import resumen_para_consumidores

    r = await _pronosticar_con_modelo({"local": argumentos.get("local"), "visitante": argumentos.get("visitante"), "league": argumentos.get("league")})
    return resumen_para_consumidores(r) if r.get("ok") else None  # el plazo lo pone el orquestador


def _modelo_en_proceso_disponible() -> bool:
    try:
        from backend.api.ml.laplace import registro

        return registro.cargar_vigente_archivo()[1] is not None
    except Exception:  # noqa: BLE001
        return False


def _modelo_en_proceso(local: str, visitante: str, liga: str) -> tuple[dict | None, str | None]:
    """(pronóstico, motivo): el modelo Laplace calculado AQUÍ (Python puro, sin red ni base), con la salida de `servicio.publico`.
    `motivo` distingue «no_disponible» (no hay modelo cargado o falló: ESO es una falla de la pieza) de «sin_cobertura» (el modelo está sano pero no conoce ese partido: lo decide la
    entrada del usuario y NO debe contar contra el circuit breaker, o cualquiera podría abrirlo pidiendo equipos inventados)."""
    try:
        from backend.api.ml.laplace import servicio

        _info, art, _motivo = servicio._modelo_vigente(None)  # noqa: SLF001
        if art is None:
            return None, "no_disponible"
        r = servicio.pronosticar_partido(None, {"local": local, "visitante": visitante, "liga": liga}, canal="http")
        return (servicio.publico(r), None) if r.get("ok") else (None, "sin_cobertura")
    except Exception:  # noqa: BLE001 — el modelo es una pieza independiente: si falla se intenta por HTTP
        return None, "no_disponible"


async def _pronosticar_con_modelo(argumentos: dict[str, Any]) -> dict:
    """Pide el pronóstico al modelo Laplace por HTTP. Si el modelo no responde NO falla el agente: devuelve `degradado` y el agente sigue con el consenso del bot."""
    local = _texto_argumento(argumentos, "local", "home")
    visitante = _texto_argumento(argumentos, "visitante", "away")
    liga = _texto_argumento(argumentos, "league", "liga", requerido=False) or ""
    if settings.AGENT_MODELO_EN_PROCESO:
        registro = registro_de_piezas()
        if registro.permitir("modelo"):
            inicio = time.monotonic()
            local_r, motivo_local = _modelo_en_proceso(local, visitante, liga)
            if local_r is not None:
                registro.exito("modelo", (time.monotonic() - inicio) * 1000)
                return {"tool": "modelo.pronosticar", **local_r, "via": "proceso"}
            if motivo_local == "sin_cobertura":  # el modelo respondió sano: que no conozca el partido no es una falla suya
                registro.exito("modelo", (time.monotonic() - inicio) * 1000)
                return {"tool": "modelo.pronosticar", "ok": False, "degradado": True, "motivo": "el modelo Laplace no cubre este partido", "alternativa": "sports.predict", "via": "proceso"}
            registro.fallo("modelo", "modelo no cargado en el proceso del agente")
    try:
        data = await _post("/api/v1/ml/predict", {"local": local, "visitante": visitante, "liga": liga})
    except Exception as exc:  # noqa: BLE001 — el modelo es una pieza independiente: su caída se informa, no se propaga
        return {"ok": False, "tool": "modelo.pronosticar", "degradado": True, "motivo": f"el modelo Laplace no respondió ({type(exc).__name__})", "alternativa": "sports.predict"}
    return {"tool": "modelo.pronosticar", **data}


async def ejecutar_herramienta_deportiva(nombre: str, argumentos: dict[str, Any], *, es_admin: bool = False, authorization: str | None = None, aprobado: bool = False, usuario: str | None = None) -> dict:
    """Ejecuta una herramienta del catálogo con validaciones comunes.

    Las acciones con efectos externos solo corren con `aprobado=True`, que únicamente fija el
    flujo de aprobaciones (`agent_approvals`) tras la decisión de un administrador. Cualquier
    `confirm` dentro de `argumentos` se ignora: el cliente no puede autoconfirmarse. La
    publicación exige además `publish=true` explícito.
    """
    definicion = next((item for item in SPORTS_TOOLS if item.name == nombre), None)
    if definicion is None:
        raise ValueError(f"Herramienta deportiva no registrada: {nombre}")
    if definicion.admin_only and not es_admin:
        raise PermissionError("Esta herramienta requiere administrador global")
    if definicion.requires_confirmation and not aprobado:
        return {"ok": False, "requires_confirmation": True, "tool": nombre}
    # Presupuesto de predicciones en el PUNTO COMÚN de todos los caminos (comando /predecir de Telegram, texto
    # libre del agente, herramienta HTTP): cada predicción consulta APIs externas con cuota compartida con el
    # bot. Antes solo lo aplicaba el comando de Telegram y las demás rutas lo esquivaban (revisión de seguridad
    # 2026-10-07). El administrador no tiene tope; sin `usuario` (llamadas internas) no se cuenta.
    if nombre in {"sports.predict", "sports.get_odds"} and usuario and not es_admin:
        consumir_prediccion(usuario)

    if nombre.startswith("knowledge."):
        return _ejecutar_conocimiento(nombre, argumentos)

    if nombre == "modelo.pronosticar":
        return await _pronosticar_con_modelo(argumentos)

    if nombre == "sports.list_leagues":
        return {
            "ok": True,
            "tool": nombre,
            "leagues": [
                {"slug": slug, "avg_goals": info.avg_goles, "standings": info.tabla, "odds": info.odds}
                for slug, info in sorted(LIGAS.items())
            ],
        }

    if nombre == "sports.list_fixtures":
        data = await _get("/api/v1/partidos", {"fecha": _fecha(argumentos.get("date"))})
        return {"ok": True, "tool": nombre, "date": _fecha(argumentos.get("date")), "fixtures": _filtrar_partidos(data, argumentos)}

    if nombre == "sports.list_top_picks":
        fecha = _fecha(argumentos.get("date"))
        data = await _get("/api/v1/web/top-picks", {"date": fecha})
        return {"ok": True, "tool": nombre, "date": fecha, "picks": data.get("picks", [])}

    if nombre == "sports.get_match":
        match_id = str(argumentos.get("match_id", "")).strip()
        if not match_id:
            raise ValueError("sports.get_match requiere match_id")
        data = await _get("/api/v1/partidos", {"fecha": _fecha(argumentos.get("date"))})
        matches = [item for item in _filtrar_partidos(data, {"limit": 200}) if str(item.get("match_id", item.get("fixture_id", item.get("id", "")))) == match_id]
        return {"ok": True, "tool": nombre, "match": matches[0] if matches else None}

    if nombre in {"sports.predict", "sports.get_odds"}:
        required = ("match_id", "local", "visitante", "league")
        missing = [key for key in required if not str(argumentos.get(key, "")).strip()]
        if missing:
            raise ValueError(f"{nombre} requiere: {', '.join(missing)}")
        if not authorization:
            raise PermissionError("La predicción del bot requiere una sesión de usuario válida")
        solicitud_bot = {
            "match_id": str(argumentos["match_id"]),
            "local": str(argumentos["local"]),
            "visitante": str(argumentos["visitante"]),
            "liga": str(argumentos["league"]),
            "fecha": _fecha(argumentos.get("date")),
        }
        if nombre == "sports.get_odds":
            data = await _post("/api/v1/prediccion-web", solicitud_bot, authorization=authorization)
            return {"ok": True, "tool": nombre, "match_id": argumentos["match_id"], "odds": data.get("odds_info", {})}
        # EN PARALELO (orquestador `pronostico_conjunto`): el bot y el modelo Laplace no se esperan ni dependen uno del otro; cada uno con su plazo y su fallo es solo suyo.
        conjunto = await pronostico_conjunto.ejecutar(
            {"bot": lambda: _post("/api/v1/prediccion-web", solicitud_bot, authorization=authorization), "modelo": lambda: _resumen_modelo(argumentos)},
            plazos={"bot": PLAZO_BOT_SEGUNDOS, "modelo": PLAZO_MODELO_SEGUNDOS})
        modelo, bot = conjunto.valor("modelo"), conjunto.paralelas["bot"]
        if not bot.ok:
            if modelo is None:
                raise bot.error  # no respondió ninguna de las dos piezas: se informa el error del bot, como siempre
            resumen = {"pick": None, "bot_disponible": False, "modelo_laplace": modelo,
                       "motivos_sin_pronostico": ["el bot no respondió; esta es solo la lectura del modelo Laplace"]}
            return {"ok": True, "tool": nombre, "prediction": None, "resumen": resumen, "piezas": conjunto.resumen()}
        resumen = resumir_prediccion(bot.valor, {"liga": argumentos["league"], "local": argumentos["local"], "visitante": argumentos["visitante"]})
        resumen["modelo_laplace"] = modelo
        return {"ok": True, "tool": nombre, "prediction": bot.valor, "resumen": resumen, "piezas": conjunto.resumen()}

    if nombre == "sports.results":
        return {"ok": True, "tool": nombre, "result": await _post("/api/v1/resultados/verificar", {"fixture_ids": argumentos.get("fixture_ids", []), "fecha": argumentos.get("date", "")}, authorization=authorization)}

    if nombre in {"sports.top_picks", "sports.publish"}:
        publicar = nombre == "sports.publish" and argumentos.get("publish") is True
        if nombre == "sports.publish" and not publicar:
            raise ValueError("sports.publish requiere publish=true")
        resultado = await _post("/api/v1/scheduler/top-picks", {}, {"publicar": publicar}, authorization=authorization)
        salida = {"ok": True, "tool": nombre, "result": resultado}
        if not publicar:
            salida["politica_publicacion"] = _politica_publicacion(resultado)  # recomendación del agente: el modelo y el bot solo pronostican
        return salida

    raise ValueError(f"Herramienta no implementada: {nombre}")
