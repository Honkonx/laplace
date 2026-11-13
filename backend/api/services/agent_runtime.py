"""Runtime inicial del agente Laplace: reglas, memoria, conocimiento y proveedor IA.

Orquesta el turno (`procesar_mensaje`). Las piezas viven en módulos hermanos y se reexportan aquí porque
routers, bots y pruebas las consumen como `agent_runtime.<nombre>`; lo que las pruebas parchean
(`ejecutar_herramienta_deportiva`, `generar_texto_ia_con_meta`, `autorizacion_sports`, `_buscar_partido`)
se queda en este módulo para que el parche surta efecto.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.models.agent_runtime import AgentMemory, AgentMessage, AgentRun, AgentSession, AgentTask, AgentToolInvocation
from backend.api.models.predicciones import PrediccionVarianteAgente
from backend.api.services.agent_guard import LimiteExcedido, autorizacion_sports, estimar_tokens, registrar_tokens, tokens_disponibles
from backend.api.services.agent_knowledge import recuperar_conocimiento, seleccionar_conocimiento, sincronizar_conocimiento_json  # noqa: F401  (re-export para router/bot)
from backend.api.services.agent_intencion_conocimiento import consulta_conocimiento
from backend.api.services.agent_learning import politicas_activas, tema_bloqueado
from backend.api.services import agent_campeonato, agent_jerga, agent_modelo_equipo, agent_perfil, agent_guardia_chat, agent_ia_herramientas, agent_dialogo, agent_marcador, agent_privacidad, agent_seguimientos, agent_tools_extra
from backend.api.services import agent_sesiones
from backend.api.services.agent_sesiones import historial_reciente, resumen_para_retomar
from backend.api.services.agent_runtime_memoria import _ahora, _contexto, _extraer_memoria_espontanea, _una_linea  # noqa: F401
from backend.api.services.agent_runtime_partidos import _fecha_natural, _normalizar_fixture, _seleccionar_fixture, _similitud_equipo  # noqa: F401
from backend.api.services.agent_runtime_prompts import (  # noqa: F401
    _contexto_configuracion_laplace, _etiqueta_pick, _normalizar_respuesta_scout, _numeros, _politica_laplace,
    _prompt_agente, _prompt_prediccion_ia, _prompt_redaccion, _redaccion_fiel, _texto_hipotesis_ia, _texto_prediccion,
)
from backend.api.services.agent_runtime_reglas import (  # noqa: F401
    ALCANCES, _fuera_de_alcance, _normalizar_humano, _partido_desde_mensaje, _respuesta_reglas, _texto_fuera_de_alcance,
    _texto_normalizado,
)
from backend.api.services.agent_tools import consultar_capacidades_deportivas, ejecutar_herramienta_deportiva, resumir_prediccion
from backend.api.services.ai_client import AnalisisIAError, generar_texto_ia_con_meta
from backend.api.services.conocimiento_texto import linea_forma, oferta_perfiles

log = logging.getLogger("laplace.agent_runtime")
KNOWLEDGE_TOOLS = ("knowledge.team_profile", "knowledge.league_profile", "knowledge.glossary")
# Herramientas cuya respuesta es determinista: la IA nunca la reemplaza.
RESPUESTAS_DETERMINISTAS = {"agent.campeonato", "agent.perfil", "agent.seguimiento", "agent.simulate_league", "agent.search_history", "sports.recent_results", "knowledge.compare_teams", "agent.security_refusal", "agent.admin_only", "agent.policy_block", "agent.prediction_choice", "knowledge.team_profile", "knowledge.league_profile", "knowledge.glossary",
                          "agent.resume", "agent.no_apuestas", "agent.sin_datos_jugadores", "agent.tabla_no_disponible"}


def _sesion(db: Session, user_id: str, session_id: str | None, channel: str) -> AgentSession:
    if session_id:
        encontrada = db.get(AgentSession, session_id)
        if encontrada and encontrada.user_id == user_id:
            return encontrada
    ahora = _ahora()
    nueva = AgentSession(id=str(uuid.uuid4()), user_id=user_id, channel=channel, status="active", creado_en=ahora, actualizado_en=ahora)
    db.add(nueva)
    db.flush()
    return nueva


async def _respaldo_sin_bot(equipos: tuple[str, str], usar_ia: bool, es_admin: bool, motivo: str) -> dict:
    """Cadena de respaldo cuando el bot no puede dar el partido (caído, en pausa o sin ese partido en su calendario): 1) el modelo Laplace con solo los nombres (MA-11),
    2) si tampoco, una hipótesis de IA rotulada como NO calculada cuando la IA está permitida en este turno (MA-14), 3) si no, un aviso honesto. Nunca inventa una cifra."""
    try:
        r = await ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": equipos[0], "visitante": equipos[1], "league": ""}, es_admin=es_admin)
    except Exception:  # noqa: BLE001 — la caída del modelo es un resultado, no un error del turno
        log.warning("respaldo sin bot: el modelo no respondió", exc_info=True)
        r = {}
    if r.get("ok"):
        from backend.api.ml.laplace.servicio import resumen_para_consumidores

        modelo = resumen_para_consumidores(r)
        if modelo:
            partido = {"local": equipos[0], "visitante": equipos[1], "league": ""}
            resumen = {"pick": None, "bot_disponible": False, "modelo_laplace": modelo, "motivos_sin_pronostico": [motivo]}
            return {"respuesta": _texto_prediccion(partido, resumen), "resumen": resumen, "herramienta": "sports.predict", "solo_ia": False, "fallo": False}
    if usar_ia and settings.AGENT_IA_ACTIVA and settings.AGENT_IA_PURA_AUTOMATICA:
        return {"respuesta": "No pude consultar ni el bot ni el modelo. Preparo una hipótesis de IA (NO calculada por Laplace).", "resumen": None, "herramienta": "agent.ai_prediction", "solo_ia": True, "fallo": False}
    return {"respuesta": "No pude consultar el bot ni el modelo ahora y no invento un resultado. Si activas la IA te doy una hipótesis rotulada como no calculada, o inténtalo en un momento.",
            "resumen": None, "herramienta": "sports.predict", "solo_ia": False, "fallo": True}


def _eleccion_prediccion_pendiente(db: Session, sesion: AgentSession, mensaje: str) -> str | None:
    """Resuelve una elección breve tras una consulta `Equipo A vs Equipo B` ambigua."""
    choice = _texto_normalizado(mensaje).strip().strip(".")
    if choice not in {"bot", "prediccion bot", "ia", "solo ia", "prediccion ia", "prediccion solo ia"}:
        return None
    anterior = db.query(AgentMessage).filter(AgentMessage.session_id == sesion.id, AgentMessage.role == "user").order_by(AgentMessage.id.desc()).first()
    partido = _partido_desde_mensaje(anterior.content) if anterior is not None else None
    if partido is None:
        return None
    via = "solo IA" if "ia" in choice else "bot"
    fecha = " mañana" if re.search(r"mañana|manana", anterior.content, re.I) else ""
    return f"predicción {via} {partido[0]} vs {partido[1]}{fecha}"


async def _buscar_partido(equipos: tuple[str, str], mensaje: str, es_admin: bool) -> dict:
    fixtures = await ejecutar_herramienta_deportiva("sports.list_fixtures", {"date": _fecha_natural(mensaje), "limit": 200}, es_admin=es_admin)
    return _normalizar_fixture(_seleccionar_fixture(fixtures.get("fixtures", []), equipos[0], equipos[1]) or {})


async def procesar_mensaje(db: Session, user_id: str, mensaje: str, session_id: str | None, channel: str, usar_ia: bool, es_admin: bool, sports_authorization: str | None = None, incognito: bool = False) -> dict:
    if not mensaje.strip():
        raise ValueError("El mensaje no puede estar vacío")
    incognito = incognito or agent_privacidad.en_incognito(user_id)
    mensaje, _enmascarados = agent_privacidad.redactar(mensaje)  # MA-42: ni se guarda ni llega al proveedor de IA un secreto o dato personal
    sesion = _sesion(db, user_id, session_id, channel)
    ahora = _ahora()
    # Resolver antes de persistir la respuesta breve. Así `anterior` es inequívocamente el
    # partido que abrió la elección, sin depender del autoflush de SQLAlchemy.
    mensaje_enrutado = _eleccion_prediccion_pendiente(db, sesion, mensaje) or agent_dialogo.seguimiento(db, sesion, mensaje) or mensaje  # MA-31: «¿y mañana?» hereda el último partido
    mensaje_para_router = _normalizar_humano(mensaje_enrutado)
    historial = historial_reciente(db, sesion.id)  # antes de guardar el mensaje actual: son solo los turnos previos
    db.add(AgentMessage(session_id=sesion.id, user_id=user_id, role="user", content=mensaje, modo="entrada", creado_en=ahora))
    if not incognito:
        _extraer_memoria_espontanea(db, user_id, mensaje)
    politicas = politicas_activas(db, user_id)
    if tema_bloqueado(mensaje_para_router, politicas):
        respuesta, modo, herramienta = ("Esa consulta queda fuera de mi alcance según las políticas activas de Laplace.", "politica", "agent.policy_block")
    else:
        equipos_del_mensaje = _partido_desde_mensaje(mensaje_para_router)
        seguido = agent_seguimientos.alguno_seguido(db, user_id, equipos_del_mensaje) if equipos_del_mensaje else None  # MS-3: el partido de lo que sigues no pregunta la vía
        respuesta, modo, herramienta = _respuesta_reglas(mensaje_para_router, es_admin, seguido)
        seguimiento = agent_seguimientos.intentar(db, user_id, mensaje_para_router, incognito)  # MS-2: «sigue al Barcelona», «qué sigo», «deja de seguir…»
        if seguimiento is not None:
            respuesta, modo, herramienta = seguimiento, "reglas", "agent.seguimiento"
        else:
            perfil_dicho = agent_perfil.intentar(db, user_id, mensaje_para_router, incognito)  # MS-6: «estoy en Chile», «responde corto», «mi perfil»
            if perfil_dicho is not None:
                respuesta, modo, herramienta = perfil_dicho, "reglas", "agent.perfil"
    herramienta_inicial = herramienta
    raw_ia: str | None = None
    fallo_herramienta = False
    ia_degradada = False
    resumen_prediccion: dict | None = None
    liga_consulta = ""
    prediccion_solo_ia = herramienta == "agent.ai_prediction"
    if prediccion_solo_ia and not usar_ia:
        respuesta = "La predicción solo IA es experimental. Activa «Permitir IA en este turno» o pide «predicción bot Equipo A vs Equipo B» para usar el motor estadístico."
        modo = "reglas"
    elif prediccion_solo_ia:
        respuesta = "Prepararé una hipótesis experimental solo IA. No sustituye el análisis estadístico del bot y quedará identificada como IA."
    if herramienta == "sports.list_leagues":
        try:
            resultado = await ejecutar_herramienta_deportiva(herramienta, {}, es_admin=es_admin)
            respuesta = f"El bot deportivo tiene {len(resultado.get('leagues', []))} entradas de ligas configuradas. Puedes pedirme una liga concreta o sus partidos."
        except Exception:
            log.exception("Fallo sports.list_leagues")
            fallo_herramienta = True
            respuesta = "No pude consultar ahora el catálogo de ligas; el bot deportivo sigue siendo opcional."
    elif herramienta == "sports.list_playing_leagues":
        fecha = _fecha_natural(mensaje)
        try:
            resultado = await ejecutar_herramienta_deportiva("sports.list_fixtures", {"date": fecha, "limit": 200}, es_admin=es_admin)
            fixtures = resultado.get("fixtures", [])
            conteos: dict[str, int] = {}
            for fixture in fixtures:
                liga = str(fixture.get("liga", fixture.get("league", "Sin liga"))).strip() or "Sin liga"
                conteos[liga] = conteos.get(liga, 0) + 1
            if not conteos:
                respuesta = f"No encontré partidos disponibles para {fecha}. Puedo revisar otra fecha."
            else:
                listado = "; ".join(f"{liga} ({total})" for liga, total in sorted(conteos.items(), key=lambda item: (-item[1], item[0]))[:20])
                extra = "" if len(conteos) <= 20 else f"; y {len(conteos) - 20} ligas más"
                etiqueta_fecha = agent_jerga.etiqueta(datetime.strptime(fecha, "%Y%m%d").date())
                respuesta = f"Para {etiqueta_fecha} encontré {len(fixtures)} partidos en {len(conteos)} ligas: {listado}{extra}."
            herramienta = "sports.list_playing_leagues"
        except Exception:
            log.exception("Fallo sports.list_playing_leagues")
            fallo_herramienta = True
            respuesta = "No pude consultar las ligas con actividad ahora; el bot deportivo sigue siendo opcional."
    elif herramienta == "sports.list_fixtures":
        try:
            resultado = await ejecutar_herramienta_deportiva(herramienta, {"date": _fecha_natural(mensaje)}, es_admin=es_admin)  # MS-7: «mañana», «el sábado» o «este finde» piden ESA fecha (antes siempre salía hoy)
            respuesta = f"Encontré {len(resultado.get('fixtures', []))} partidos para la fecha {resultado.get('date', 'solicitada')}. Puedes pedirme una liga, equipo o partido concreto."
        except Exception:
            log.exception("Fallo sports.list_fixtures")
            fallo_herramienta = True
            respuesta = "No pude consultar los partidos ahora; el bot deportivo sigue siendo opcional."
    elif herramienta == "sports.list_top_picks":
        fecha = _fecha_natural(mensaje_enrutado)
        try:
            resultado = await ejecutar_herramienta_deportiva(herramienta, {"date": fecha}, es_admin=es_admin)
            picks = resultado.get("picks", [])
            if picks:
                resumen = "; ".join(f"{item.get('local', '?')} vs {item.get('visitante', '?')}: {item.get('pick_final', item.get('pick', 'sin pick'))}" for item in picks[:3])
                respuesta = f"Top Picks ya publicados para {fecha}: {resumen}."
            else:
                respuesta = f"Todavía no hay Top Picks publicados para {fecha}. El bot sólo publica cuando supera sus controles de calidad."
        except Exception:
            log.exception("Fallo sports.list_top_picks")
            fallo_herramienta = True
            respuesta = "No pude consultar los Top Picks publicados ahora."
    elif herramienta in {"sports.predict", "sports.get_odds"}:
        equipos = _partido_desde_mensaje(mensaje_enrutado)
        if not equipos:
            respuesta = "Indícame el partido con el formato equipo local vs equipo visitante para poder analizarlo."
            herramienta = "sports.match_required"
        else:
            try:
                partido = await _buscar_partido(equipos, mensaje_enrutado, es_admin)
                if not partido["match_id"]:
                    if herramienta == "sports.predict":
                        respaldo = await _respaldo_sin_bot(equipos, False, es_admin, f"ese partido no está en el calendario del bot para {_fecha_natural(mensaje_enrutado)}; esta es solo la lectura del modelo Laplace")
                        if respaldo["resumen"] is not None:
                            respuesta, resumen_prediccion = respaldo["respuesta"], respaldo["resumen"]
                    if resumen_prediccion is None:
                        respuesta = f"No encontré un partido disponible con {equipos[0]} vs {equipos[1]}. Puedo listar los partidos de otra fecha." + oferta_perfiles(list(equipos))
                        herramienta = "sports.match_not_found"
                else:
                    liga_consulta = partido["league"]
                    autorizacion = autorizacion_sports(user_id, sports_authorization)
                    resultado = await ejecutar_herramienta_deportiva(herramienta, {**partido, "date": _fecha_natural(mensaje_enrutado)}, es_admin=es_admin, authorization=autorizacion, usuario=user_id)
                    if herramienta == "sports.get_odds":
                        respuesta = f"Cuotas disponibles para {partido['local']} vs {partido['visitante']}: {resultado.get('odds', {}) or 'sin cuotas cargadas'}."
                    else:
                        resumen_prediccion = resultado.get("resumen") or resumir_prediccion(resultado.get("prediction", {}), partido)
                        resumen_prediccion = {**resumen_prediccion, "pick_equipo": _etiqueta_pick(resumen_prediccion.get("pick") or "", partido)}
                        formas = tuple(f for f in (linea_forma(partido["local"], partido["league"]), linea_forma(partido["visitante"], partido["league"])) if f)
                        respuesta = _texto_prediccion(partido, resumen_prediccion, formas)
                        if resumen_prediccion.get("modelo_laplace") and resumen_prediccion.get("pick"):
                            frase = agent_marcador.linea_de_partido(db, partido["league"], partido["local"], partido["visitante"])
                            respuesta = f"{respuesta}\n{frase}" if frase else respuesta
            except LimiteExcedido as exc:
                # Tope de predicciones por usuario: es un límite del servicio, no un fallo de la herramienta.
                respuesta = f"{exc}. Cada predicción consulta fuentes externas con cuota limitada; inténtalo más tarde."
                herramienta = "sports.rate_limited"
            except Exception:
                log.exception("Fallo %s", herramienta)
                if herramienta == "sports.predict":
                    respaldo = await _respaldo_sin_bot(equipos, usar_ia, es_admin, "el bot no respondió; esta es solo la lectura del modelo Laplace")
                    respuesta, resumen_prediccion, herramienta = respaldo["respuesta"], respaldo["resumen"], respaldo["herramienta"]
                    fallo_herramienta, prediccion_solo_ia = respaldo["fallo"], respaldo["solo_ia"]
                else:
                    fallo_herramienta = True
                    respuesta = "No pude completar el análisis del partido; el bot deportivo sigue siendo opcional y no invento un resultado."
    elif herramienta == "sports.route":
        sports = await consultar_capacidades_deportivas()
        if sports.get("available"):
            capabilities = sports.get("capabilities", {}).get("capabilities", ["fútbol"])
            respuesta = f"Conecté con el bot deportivo. Capacidades disponibles: {', '.join(str(item) for item in capabilities)}. El análisis específico se ejecuta en su backend y conserva sus propias reglas."
            herramienta = "sports.capabilities"
        else:
            respuesta = "El bot deportivo no está disponible ahora. El agente continúa funcionando con sus reglas y memoria, y volverá a detectarlo automáticamente."
            herramienta = "sports.route_unavailable"
    elif herramienta in KNOWLEDGE_TOOLS:
        consulta = consulta_conocimiento(_texto_normalizado(mensaje_para_router), hay_partido=bool(_partido_desde_mensaje(mensaje_para_router)))
        try:
            if consulta is None or consulta[0] != herramienta:
                raise ValueError("consulta de conocimiento sin argumentos")
            respuesta = (await ejecutar_herramienta_deportiva(herramienta, consulta[1], es_admin=es_admin))["texto"]
            if herramienta == "knowledge.team_profile":  # MP-4: lo que el modelo sabe del equipo (memoria compartida), con su origen y su fecha
                respuesta += agent_modelo_equipo.linea_de_equipo(db, str(consulta[1].get("team", "")))
        except ValueError:
            respuesta = "No pude entender qué equipo, liga o término consultar. Prueba con «perfil de Boca», «tasas base de la liga chilena» o «qué significa confianza media»."
    elif herramienta == "agent.campeonato":  # MS-5: tabla propia y última jornada de la liga que menciona o de las que sigue; la simulación solo para pro/max y administradores
        respuesta = agent_campeonato.resumen(db, user_id, _texto_normalizado(mensaje_para_router), es_admin)
    elif herramienta == "agent.simulate_league":
        from backend.api.db import usuarios_repo
        from backend.api.services import simulador_propio

        acceso = usuarios_repo.acceso_simulador(db, user_id)
        if not (acceso["permitido"] or es_admin):
            respuesta = f"🔒 {usuarios_repo.MENSAJE_SIMULADOR} Con tu plan actual puedo darte el pronóstico de un partido: «analiza A vs B»."
        else:
            slug = simulador_propio.liga_de_texto(_texto_normalizado(mensaje_para_router))
            resultado_sim = await asyncio.to_thread(simulador_propio.simular, slug) if slug else {"ok": False, "razon": "No reconocí la liga."}
            respuesta = simulador_propio.texto_resumen(resultado_sim)
    elif herramienta == "agent.search_history":
        tema = agent_sesiones.tema_de_busqueda(_texto_normalizado(mensaje_para_router)) or ""
        hallado = agent_sesiones.buscar_en_historial(db, user_id, tema)
        respuesta = ("Esto es lo que encontré en tus conversaciones:\n" + "\n".join(f"• {h['cuando']} ({'tú' if h['rol'] == 'user' else 'yo'}): {h['texto']}" for h in hallado)) if hallado else f"No encontré nada sobre «{tema}» en tus conversaciones guardadas."
    elif herramienta == "sports.recent_results":
        equipo = agent_tools_extra.equipo_de_resultados(_texto_normalizado(mensaje_para_router)) or ""
        respuesta = agent_tools_extra.resultados_recientes(db, equipo)["texto"]
    elif herramienta == "knowledge.compare_teams":
        par = agent_tools_extra.equipos_a_comparar(_texto_normalizado(mensaje_para_router))
        respuesta = agent_tools_extra.comparar_perfiles(*par)["texto"] if par else "Dime los dos equipos: «compara el perfil de Boca y River»."
    elif herramienta == "agent.resume":
        respuesta = resumen_para_retomar(db, user_id, sesion.id, mensaje)
    elif herramienta == "agent.tasks":
        tareas = db.query(AgentTask).filter(AgentTask.user_id == user_id).order_by(AgentTask.creado_en.desc()).limit(5).all()
        if tareas:
            resumen = "; ".join(f"{item.kind}: {item.status}" for item in tareas)
            respuesta = f"Tus últimas {len(tareas)} tareas: {resumen}."
        else:
            respuesta = "Todavía no tienes tareas persistidas. Puedes programar una desde la futura vista de tareas o pedir una acción compatible en el chat."
    elif herramienta == "agent.memory":
        recuerdos = db.query(AgentMemory).filter(AgentMemory.owner_id == user_id, AgentMemory.activo == 1, AgentMemory.sensibilidad == "normal").order_by(AgentMemory.actualizado_en.desc()).limit(5).all()
        if recuerdos:
            resumen = "; ".join(f"{item.topic_key}: {item.content[:80]}" for item in recuerdos)
            respuesta = f"Tus recuerdos recientes: {resumen}."
        else:
            respuesta = "Aún no tengo recuerdos personales guardados para esta cuenta. Los recuerdos se guardan solo dentro de tu perfil."
    # Las herramientas deportivas devuelven la fuente de verdad: la IA solo interviene (a) para
    # redactar una predicción sobre su JSON verificado o (b) en conversación libre. Ninguna otra
    # herramienta deportiva gasta una llamada al modelo cuyo resultado se descartaría.
    respuesta_verificada = respuesta
    es_herramienta_deportiva = bool(herramienta and herramienta.startswith("sports.")) and herramienta_inicial != "sports.route"
    ia_aplica = usar_ia and settings.AGENT_IA_ACTIVA and not _fuera_de_alcance(mensaje_enrutado) and herramienta_inicial not in RESPUESTAS_DETERMINISTAS and not fallo_herramienta
    if ia_aplica and not tokens_disponibles(user_id, es_admin=es_admin):  # MA-51: presupuesto diario de tokens agotado → se degrada a SIN IA
        ia_aplica = False
        respuesta = respuesta + "\n(Presupuesto diario de IA agotado: respondo sin IA.)"
    chat_libre = resumen_prediccion is None and not (prediccion_solo_ia and _partido_desde_mensaje(mensaje_enrutado))
    if ia_aplica and chat_libre and settings.AGENT_PERMISIVIDAD == "estricto":  # MA-35: en modo estricto la IA no conversa libremente
        ia_aplica = False
    if ia_aplica and (not es_herramienta_deportiva or resumen_prediccion is not None):
        equipos_ia = _partido_desde_mensaje(mensaje_enrutado) if prediccion_solo_ia else None
        if resumen_prediccion is not None:
            prompt = _prompt_redaccion(resumen_prediccion, respuesta_verificada)
        elif equipos_ia:
            prompt = _prompt_prediccion_ia(equipos_ia[0], equipos_ia[1], _fecha_natural(mensaje_enrutado))
        else:
            prompt = _prompt_agente(db, user_id, mensaje, liga_consulta, politicas, historial, settings.AGENT_PERMISIVIDAD == "abierto", agent_perfil.instantanea_para_ia(db, user_id))
        try:
            raw_ia = None
            if settings.AGENT_FUNCTION_CALLING and chat_libre:  # MA-34: con herramientas y cifras verificadas; si no sirve, el camino normal
                con_herramientas = await agent_ia_herramientas.responder(db, mensaje, prompt)
                if con_herramientas:
                    raw_ia, proveedor, modelo = con_herramientas["texto"], con_herramientas["proveedor"], con_herramientas["modelo"]
            if raw_ia is None:
                raw_ia, proveedor, modelo = await generar_texto_ia_con_meta(prompt, max_tokens=700, rol="agente")
            registrar_tokens(user_id, estimar_tokens(prompt, raw_ia))
            if prediccion_solo_ia and equipos_ia:
                normalizada = _normalizar_respuesta_scout(raw_ia)
                try:  # con el partido resuelto la hipótesis se puede evaluar luego; sin él (bot apagado o partido ausente) se guarda igual
                    partido = await _buscar_partido(equipos_ia, mensaje_enrutado, es_admin)
                except Exception as exc:  # noqa: BLE001 — resolver el partido es accesorio
                    log.warning("No se pudo resolver el partido de la hipótesis IA: %s", exc)
                    partido = {}
                db.add(PrediccionVarianteAgente(
                    user_id=user_id, session_id=sesion.id, partido_id=partido.get("match_id") or None, fecha=_fecha_natural(mensaje_enrutado),
                    liga=partido.get("league") or None, local=equipos_ia[0], visitante=equipos_ia[1], via="ai_scout",
                    pick=str(normalizada.get("pick") or "") or None,
                    marcador_probable=str(normalizada.get("marcador_probable") or "") or None,
                    confianza=str(normalizada.get("confianza") or "") or None,
                    proveedor=proveedor, modelo=modelo, prompt_version="ai-scout-v1",
                    respuesta_cruda=raw_ia, resultado_json=json.dumps(normalizada, ensure_ascii=False), creado_en=_ahora(),
                ))
                respuesta = _texto_hipotesis_ia(equipos_ia, normalizada, raw_ia)
                modo, herramienta = f"ia_experimental · {proveedor}/{modelo}", "agent.ai_prediction"
            elif resumen_prediccion is not None:
                # La redacción solo se acepta si no introduce cifras ajenas al JSON del motor.
                if _redaccion_fiel(raw_ia, resumen_prediccion, respuesta_verificada):
                    respuesta, modo = raw_ia.strip(), f"ia · {proveedor}/{modelo}"
                else:
                    log.warning("Redacción IA descartada por incluir cifras o pick ajenos al motor")
                    modo = f"reglas · ia_descartada {proveedor}/{modelo}"
            else:
                charla, reemplazada = agent_guardia_chat.sanear_charla(raw_ia, mensaje)  # H-008: la IA no inventa probabilidades ni marcadores
                if reemplazada:
                    log.warning("Charla libre de IA reemplazada: traía porcentajes, marcadores o promesas sin respaldo")
                respuesta = charla if reemplazada else f"{charla}\n\n(Respuesta de IA: no verificada por el modelo de Laplace.)"
                modo, herramienta = (f"reglas · charla_descartada {proveedor}/{modelo}" if reemplazada else f"ia · {proveedor}/{modelo}"), "llm.respond"
        except AnalisisIAError:
            ia_degradada = True
            respuesta = "La IA no está disponible ahora. Respondo con las reglas locales: " + respuesta
            modo = "reglas_fallback"
    if herramienta_inicial:  # auditoría de cada herramienta pedida desde el chat o Telegram (MA-06)
        ahora_audit = _ahora()
        db.add(AgentToolInvocation(id=str(uuid.uuid4()), user_id=user_id, tool_name=herramienta_inicial[:100], status="failed" if fallo_herramienta else "succeeded",
                                   input_json=json.dumps({"canal": channel, "sesion": sesion.id, "mensaje": mensaje[:200]}, ensure_ascii=False),
                                   output_json=json.dumps({"modo": modo[:60]}, ensure_ascii=False), creado_en=ahora_audit, terminado_en=ahora_audit))
    db.add(AgentMessage(session_id=sesion.id, user_id=user_id, role="assistant", content=respuesta, modo=modo[:32], herramienta=herramienta, creado_en=_ahora()))
    run_id = str(uuid.uuid4())
    estado = "failed" if fallo_herramienta else "partial" if ia_degradada else "succeeded"
    db.add(AgentRun(id=run_id, session_id=sesion.id, user_id=user_id, status=estado, input_json=json.dumps({"message": mensaje, "routed_message": mensaje_enrutado, "usar_ia": usar_ia}), output_json=json.dumps({"mode": modo, "tool": herramienta, "raw_ia": raw_ia, "tool_failed": fallo_herramienta}, ensure_ascii=False), creado_en=ahora, terminado_en=_ahora()))
    sesion.actualizado_en = _ahora()
    if not sesion.title:
        sesion.title = mensaje.strip()[:80]
    if incognito:  # MA-41: no se guarda el CONTENIDO (mensajes, ejecución, sesión, memoria); la auditoría de la herramienta sí, sin texto ni sesión (revisión de seguridad 2026-11-11)
        db.rollback()
        if herramienta_inicial:
            ahora_audit = _ahora()
            db.add(AgentToolInvocation(id=str(uuid.uuid4()), user_id=user_id, tool_name=herramienta_inicial[:100], status="failed" if fallo_herramienta else "succeeded",
                                       input_json=json.dumps({"canal": channel, "incognito": True}), output_json=json.dumps({"modo": modo[:60]}, ensure_ascii=False), creado_en=ahora_audit, terminado_en=ahora_audit))
            db.commit()
        return {"session_id": None, "run_id": None, "respuesta": respuesta, "modo": modo, "herramienta": herramienta, "incognito": True}
    db.commit()
    return {"session_id": sesion.id, "run_id": run_id, "respuesta": respuesta, "modo": modo, "herramienta": herramienta}
