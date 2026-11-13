"""services/agent_runtime_reglas.py — normalización del mensaje, detección de intención y enrutado por reglas.

Texto puro: no toca la BD ni herramientas. Lo reexporta `agent_runtime`.
"""
from __future__ import annotations

import re
import unicodedata

from backend.api.core.config import settings
from backend.api.services.agent_intencion_conocimiento import consulta_conocimiento
from backend.api.services import agent_jerga, agent_tools_extra

ALCANCES = ("deportivo", "laplace", "agente", "apuestas", "futbol", "usuario", "admin")


_EQ = r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 .'’-]{1,40}?"
_FIN_EQ = r"(?:\?|!|$|[,;]|\s+(?:hoy|manana|mañana|este|esta)\b)"
_PISTA_PARTIDO = r"(?:quien\s+gana|qui[eé]n\s+gana|quien\s+se\s+lleva|quien\s+la\s+gana|como\s+pinta|a\s+quien\s+le\s+das|quien\s+crees\s+que\s+gana|who\s+wins|who\s+will\s+win|como\s+sale|c[oó]mo\s+sale|que\s+pasa\s+en|qu[eé]\s+pasa\s+en|predic\w*|pronost\w*|analiz\w*|compar\w*|cuotas?|odds|over|under|btts|ambos\s+marcan)"
# Cabeceras que no son parte del nombre del equipo (se quitan del local, repetidamente).
_CABECERA_LOCAL = re.compile(
    r"^(?:(?:predicción|prediccion|pronóstico|pronostico)(?:\s+(?:solo\s+)?ia|\s+bot)?|(?:quien|quién|qien)\s+(?:(?:gana)|(?:cre(?:e|es)?\s+que\s+gana))|(?:dime|dame)\s+(?:quien|quién|qien)\s+gana"
    r"|(?:quien|quién)\s+(?:se\s+lleva|la\s+gana|pasa)|como\s+pinta|a\s+quien\s+le\s+das|va\s+a\s+ganar|who\s+(?:wins|will\s+win)|c[oó]mo\s+sale|que\s+pasa\s+en|qu[eé]\s+pasa\s+en|compar\w*|(?:over|under)\s+\d(?:[.,]\d)?\s+(?:en|de)|(?:ambos\s+marcan|btts)\s+(?:en|de)|partido\s+(?:de|entre)|\d+(?:[.,]\d+)?\s+(?:en|de)|en|entre|del|de\s+la|de\s+el|de|el|la|e)\s+",
    flags=re.I)


def _limpiar_equipo_local(local: str) -> str:
    local = local.strip(" .,-¿?¡!")
    anterior = None
    while anterior != local:
        anterior = local
        local = _CABECERA_LOCAL.sub("", local).strip(" .,-")
    local = re.sub(r"^.*?\b(?:para|entre|del partido|partido)\s+", "", local, flags=re.I)
    return local


def _partido_desde_mensaje(mensaje: str) -> tuple[str, str] | None:
    """(local, visitante) del mensaje, o None. Acepta «vs / versus / contra / ante», guion («Madrid-Barça» tras una pista), «A o B, ¿quién gana?» y «compara A y B»; ignora ¿ ¡."""
    mensaje = _normalizar_humano(mensaje)
    directo = re.search(r"(?:predic\w*|pronost\w*|analiz\w*)\s+(?:bot\s+|solo\s+ia\s+)?(.+?)\s+(?:vs\.?|versus|contra|ante)\s+(.+?)(?:\?|$|\s+(?:hoy|manana|mañana))", mensaje, re.I)
    if directo:
        return directo.group(1).strip(" .,-"), directo.group(2).strip(" .,-")
    encontrado = re.search(rf"(?:predic\w*|pronost\w*|analiz\w*|cuotas?|odds|over|under|btts|ambos\s+marcan).{{0,35}}?({_EQ})\s+(?:vs\.?|versus|contra|ante)\s+({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:
        encontrado = re.search(rf"(?:^|\b(?:entre|de|partido)\s+)({_EQ})\s+(?:vs\.?|versus|contra|ante)\s+({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:
        # «¿quién gana el Madrid-Barça?»: guion sin espacios solo detrás de una pista de partido, para no romper nombres como Colo-Colo.
        encontrado = re.search(rf"{_PISTA_PARTIDO}\s+(?:el\s+|la\s+|del\s+|entre\s+)?(?:partido\s+|clasico\s+)?({_EQ})\s*[-–—/]\s*({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:  # «¿quién la gana: Girona vs Getafe?», también con muletillas delante («a ver, …»)
        encontrado = re.search(rf"{_PISTA_PARTIDO}\s*[:,]?\s*(?:el\s+|la\s+|del\s+|entre\s+)?({_EQ})\s+(?:vs\.?|versus|contra|ante)\s+(?:el\s+|la\s+)?({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:
        encontrado = re.search(rf"(?:quien|qui[eé]n)\s+(?:gana|la\s+gana|se\s+lleva|pasa)\s*[:,]?\s*(?:entre\s+)?({_EQ})\s+(?:o|y)\s+({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:
        encontrado = re.search(rf"({_EQ})\s+o\s+({_EQ})\s*[,;]?\s*(?:quien|qui[eé]n|cual|cu[aá]l)\s+(?:gana|crees|se\s+lleva|la\s+gana)", mensaje, re.I)
    if not encontrado:
        encontrado = re.search(rf"compar\w*\s+(?:a\s+)?(?:el\s+|la\s+)?({_EQ})\s+(?:con|y|vs\.?|contra)\s+(?:el\s+|la\s+)?({_EQ}){_FIN_EQ}", mensaje, re.I)
    if not encontrado:
        return None
    local = _limpiar_equipo_local(encontrado.group(1))
    visitante = encontrado.group(2).strip(" .,-¿?¡!")
    visitante = re.sub(r"^(?:el|la)\s+", "", visitante, flags=re.I)
    visitante = re.sub(r"\s+(?:hoy|mañana|manana)$", "", visitante, flags=re.I)
    return (local, visitante) if local and visitante and local.casefold() != visitante.casefold() else None


def _normalizar_humano(mensaje: str) -> str:
    """Corrige abreviaciones frecuentes sin modificar nombres propios."""
    texto = re.sub(r"[¿¡]", "", mensaje)  # en español la pregunta abre con ¿: no debe romper las expresiones regulares
    texto = re.sub(r"\bq\b", "que", texto, flags=re.I)
    reemplazos = {r"\boy\b": "hoy", r"\bmanana\b": "mañana", r"\bqien\b": "quien", r"\bganra\b": "gana", r"\bke\b": "que", r"\bk\b": "que"}
    for origen, destino in reemplazos.items():
        texto = re.sub(origen, destino, texto, flags=re.I)
    return agent_jerga.normalizar_apodos(texto)  # MS-7: «el Barça» y «los merengues» llegan al router con el nombre del equipo


def _texto_normalizado(mensaje: str) -> str:
    """Normaliza acentos para que el routing soporte escritura humana."""
    return "".join(
        caracter for caracter in unicodedata.normalize("NFKD", mensaje)
        if not unicodedata.combining(caracter)
    ).casefold()


_DOMINIO = re.compile(
    r"futbol|partido|partidos|liga|ligas|competicion|juego|juegos|fixture|fixtures|cuota|odds|apuesta|apuestas|apostar|resultado|bot deportivo|quien gana\b|quien crees|\b(vs|versus|contra|ante)\b"
    r"|\b(?:tabla|posiciones|clasificacion|equipo|equipos|jugador|jugadores|gol|goles|goleador|goleadores|lesion|lesionad\w*|entrenador|plantel|plantilla|temporada|jornada|descenso|ascenso|campeon|copa|mundial|champions|libertadores|pronostic\w*|prediccion|predic\w*|compar\w*|clasico|picks?)\b"
    r"|\b(?:que|cuando|a que hora|donde) juega\b"
    r"|\b(?:como|que tal) (?:viene|vienen|llega|llegan|pinta|pintan)\b|\bque se juega\b|quien se lleva|quien la gana|va a ganar el|a quien le das|\b(?:finde|fin de semana|pasado manana|ayer)\b|sigue donde quedamos|retomar|continuemos|resume\w* (?:nuestra|la) conversacion")
_PARTIDO = re.compile(r"(?:predic|pronost|analiz|cuota|odds).{0,80}(?:vs|versus|contra)")
# "quien ganara las elecciones" y similares no son deportivos aunque contengan "quien gana".
_TEMAS_PROHIBIDOS = re.compile(r"(^|\s)(2\s*\+\s*2|clima|tiempo en|temperatura|receta|politica|elecciones?|president[ea]s?|congreso)(\s|$)")


# MS-8, nivel «abierto»: cultura de fútbol que el nivel normal deja fuera (no es charla libre: lo ajeno al fútbol sigue fuera de alcance).
_DOMINIO_ABIERTO = re.compile(r"\b(?:arbitro|arbitros|var|fuera de juego|offside|penal|penales|tanda de penales|tarjeta|fichaje|fichajes|mercado de pases|seleccion|selecciones|eliminatorias|estadio|estadios|hinchada|barra|dt|tecnico|tactica|formacion|balon de oro|historia del futbol|record|records|goleador historico|clasico|derbi|derby|supercopa|recopa|cantera|canterano|capitan|mundial de clubes)\b")


def _texto_fuera_de_alcance(texto: str, abierto: bool = False) -> bool:
    """`texto` ya viene normalizado (sin acentos, en minúsculas). Con `abierto` también cuenta la cultura de fútbol en general; los temas prohibidos siguen fuera."""
    if _TEMAS_PROHIBIDOS.search(texto):
        return True
    if abierto and _DOMINIO_ABIERTO.search(texto):
        return False
    return not (_DOMINIO.search(texto) or _PARTIDO.search(texto) or any(re.search(p, texto) for p in ALCANCES))


def _respuesta_reglas(mensaje: str, es_admin: bool, seguido: str | None = None) -> tuple[str, str, str | None]:
    """Router local tolerante a acentos y variantes de lenguaje del usuario."""
    texto = _texto_normalizado(mensaje)
    # La base, memorias de otros usuarios, claves, prompts internos, reglas y resultados de
    # herramientas son datos internos. Esta barrera ocurre antes de routing o IA para que una
    # petición deportiva disfrazada de extracción no pueda cambiar el alcance.
    if re.search(r"base de datos|datos de usuarios|lista de usuarios|contrase(n|ñ)as|api[_ -]?key|token|prompt interno|system prompt|prompt del sistema|ignora.*instruccion|revela.*(?:memoria|regla|skill)|claves? (?:del|de la) (?:backend|servidor|api|sistema|bot)|usuarios registrados|memorias? de otros|acceso (?:de|como) administrador|rm -rf", texto):
        return ("No puedo revelar datos internos, credenciales, memorias ajenas, instrucciones ni información de usuarios. Puedo analizar el partido con datos deportivos autorizados.", "seguridad", "agent.security_refusal")
    comandos = {
        "/ayuda": ("Comandos del agente: /nuevo, /tareas, /subagentes, /memoria, /estado, /prediccion y /ayuda. Los comandos de Telegram pertenecen al bot y no se usan aquí.", "agent.help"),
        "/nuevo": ("Preparé una sesión nueva. Puedes pedir una tarea, una predicción con bot o una predicción experimental solo IA.", "agent.new_session"),
        "/tareas": ("Consultaré tus tareas recientes.", "agent.tasks"),
        "/subagentes": ("Subagentes actuales: Laplace Chat (contexto, memoria e IA), Puente deportivo (fixtures, predicciones y cuotas) y QA de contratos (salud e independencia). Cada tarea se ejecuta desde un registro cerrado y auditable.", "agent.subagents"),
        "/memoria": ("Consultaré tus recuerdos personales recientes.", "agent.memory"),
        "/estado": ("El agente y el bot se mantienen independientes. Puedo consultar el bot cuando está disponible y seguir con reglas y memoria cuando no lo está.", "agent.status"),
        "/prediccion": ("Indica «predicción bot Barcelona vs PSG» para el motor estadístico, o «predicción solo IA Barcelona vs PSG» para una hipótesis experimental identificada como IA.", "agent.prediction_help"),
    }
    if texto.strip() == "/prediccion-usuarios":
        if not es_admin:
            return ("Ese comando es exclusivo del administrador global porque registra referencias humanas en el laboratorio interno.", "seguridad", "agent.admin_only")
        return ("Modo administrador: abre el formulario de referencias humanas, elige un partido ya cargado para hoy o mañana, indica el alias, pick, marcador opcional y razón. Se guardará como evidencia de sombra y nunca alterará el consenso público.", "reglas", "agent.human_prediction_form")
    if texto.strip() in comandos:
        response, tool = comandos[texto.strip()]
        return response, "reglas", tool
    if texto.strip() == "/top":
        return ("Consultaré los Top Picks que ya fueron publicados para hoy.", "reglas", "sports.list_top_picks")
    if re.fullmatch(r"(?:hola|buenas|buenos dias|buenas tardes|buenas noches|hey|hola laplace)[!. ]*", texto):
        return ("Hola, soy Laplace, tu agente de análisis deportivo. Puedo mostrar los partidos y ligas de hoy, revisar un equipo o preparar un análisis. [Sin IA]", "reglas", "agent.greeting")
    if re.fullmatch(r"(?:necesito |quiero )?(?:ayuda|ayudame|me ayudas)(?: por favor)?[.!? ]*", texto) or re.search(r"que puedes|que haces|cuales son tus capacidades|capacidades", texto):  # «ayuda con mi tarea de matemáticas» no es ayuda del agente
        extra = " Como administrador global tambien puedes consultar configuracion y operacion." if es_admin else ""
        return ("Puedo conversar sobre Laplace, futbol, ligas, partidos, predicciones, memoria y tareas." + extra, "reglas", "agent.help")
    from backend.api.services import simulador_propio

    if re.search(r"\bsimul\w+|\bcampe(?:on|ones)\b|\bdescens\w+|\bclasific\w+ a (?:la |el )?(?:champions|copa|europa)", texto) and simulador_propio.liga_de_texto(texto):
        return ("Simularé esa liga con los datos propios.", "reglas", "agent.simulate_league")
    from backend.api.services.agent_sesiones import tema_de_busqueda  # import local: agent_sesiones importa este módulo

    if tema_de_busqueda(texto):
        return ("Buscaré en tus conversaciones anteriores.", "reglas", "agent.search_history")
    if agent_tools_extra.equipos_a_comparar(texto):
        return ("Compararé los perfiles de los dos equipos.", "reglas", "knowledge.compare_teams")
    if agent_tools_extra.equipo_de_resultados(texto):
        return ("Consultaré los últimos resultados guardados de ese equipo.", "reglas", "sports.recent_results")
    # Apostar (9): se dice antes que la base de conocimiento, que de otro modo toma «cuánto debo apostar» por una definición.
    if re.search(r"\bapost(?:ar|ado|emos)\b|\bapuestas?\s+(?:segura|combinada|fija)s?\b|\bdonde apuesto\b|\bcuanto (?:apuesto|debo apostar)\b|\bquiero apostar\b", texto):
        return ("Laplace no es una casa de apuestas: no recibe dinero ni recomienda cuánto apostar. Solo muestra pronósticos y su análisis; lo que hagas con ellos es decisión tuya. Puedo darte el pronóstico de un partido si me dices cuál.", "reglas", "agent.no_apuestas")
    if re.fullmatch(r"(?:los |las )?(?:top\s*)?picks?|top\s*picks?", texto.strip(" ?!.")):
        return ("Consultaré los Top Picks ya publicados; no generaré ni publicaré nada desde esta conversación.", "reglas", "sports.list_top_picks")
    if re.search(r"\bpartidos?\b.{0,40}\b(?:hoy|manana)\b", texto) and not re.search(r"\bligas?\b.{0,25}\bpartidos?\b|por partido", texto):
        return ("Consultare los partidos disponibles y aplicare tus filtros.", "reglas", "sports.list_fixtures")
    conocimiento = consulta_conocimiento(texto, hay_partido=bool(_partido_desde_mensaje(mensaje)))
    if conocimiento:
        return ("Consultaré la base de conocimiento de Laplace.", "reglas", conocimiento[0])
    # Lenguaje natural para lo PROPIO del usuario (antes solo respondían los comandos /tareas y /memoria y «mis tareas» caía en «fuera de alcance», aunque la ayuda
    # dice que el agente conversa sobre memoria y tareas). Las herramientas devuelven solo lo del propio usuario; lo ajeno lo frena la barrera de seguridad de arriba.
    if re.search(r"\bmis\s+tareas\b|\bmi\s+tarea(?!\s+de\b)\b|\btareas\s+recientes\b|\bque\s+tareas\s+tengo\b", texto):
        return ("Consultaré tus tareas recientes.", "reglas", "agent.tasks")
    if re.search(r"\b(?:mis|mi)\s+(?:recuerdos?|memorias?)\b|\bque\s+(?:recuerdas|sabes)\s+de\s+mi\b", texto):
        return ("Consultaré tus recuerdos personales recientes.", "reglas", "agent.memory")
    if re.search(r"top\s*pick|mejor(?:es)?\s+(?:partido|pick)|mas\s+fuerte|recomend|recomiend\w*\s+(?:un\s+|algun\s+)?(?:partido|pick)|recomiend\w*\s+para\s+(?:hoy|manana)|pronostic\w*\s+(?:de|para)\s+(?:hoy|manana)|picks?\s+(?:de|para)\s+(?:hoy|manana)", texto):
        return ("Consultaré los Top Picks ya publicados; no generaré ni publicaré nada desde esta conversación.", "reglas", "sports.list_top_picks")
    # Retomar la conversación (MA-02): se resume lo último de la sesión anterior del propio usuario.
    if re.search(r"sigue donde quedamos|seguimos donde|retomar|retoma(?:r|mos)? |retomemos|continuemos|resume\w* (?:nuestra|la) (?:conversacion|sesion)|que (?:hablamos|vimos)", texto):
        return ("Retomaré lo último de tu conversación anterior.", "reglas", "agent.resume")
    # Apostar: respuesta explícita de producto (nunca acepta dinero ni recomienda montos).
    if re.search(r"\bapost(?:ar|ado|emos)\b|\bcuanto (?:apuesto|apostar)\b|\bquiero apostar\b", texto):
        return ("Laplace no es una casa de apuestas: no recibe dinero ni recomienda cuánto apostar. Solo muestra pronósticos y su análisis; lo que hagas con ellos es decisión tuya. Puedo darte el pronóstico de un partido si me dices cuál.", "reglas", "agent.no_apuestas")
    # Datos que todavía no existen (jugadores, lesiones, goleadores, tablas): se dice con honestidad en vez de «fuera de alcance» (MA-02).
    if not _partido_desde_mensaje(mensaje) and re.search(r"\b(?:jugador|jugadores|goleador|goleadores|lesion\w*|lesionad\w*|entrenador|plantel|plantilla|haaland|messi|mbappe|cristiano)\b|como viene [a-z]+ (?:de|en) (?:goles|forma)", texto):
        return ("Todavía no tengo datos de jugadores, lesiones ni goleadores. Sí puedo darte el perfil de un equipo, los partidos de hoy o el pronóstico de un partido («analiza Equipo A vs Equipo B»).", "reglas", "agent.sin_datos_jugadores")
    from backend.api.services import agent_campeonato  # noqa: PLC0415

    if re.search(r"\b(?:como (?:van|va) (?:mis ligas|mi liga)|mis ligas|resumen de (?:mi|mis) ligas?|resumen de la jornada)\b", texto) or (
            not _partido_desde_mensaje(mensaje) and re.search(r"\b(?:tabla|posiciones|clasificacion|lidera|puntero)\b", texto) and agent_campeonato.liga_explicita(texto)):
        return ("Armaré la tabla y la jornada con los resultados propios.", "reglas", "agent.campeonato")  # MS-5
    if not _partido_desde_mensaje(mensaje) and re.search(r"\b(?:tabla|posiciones|clasificacion|lidera|puntero|descenso)\b", texto):
        return ("Todavía no consulto la tabla de posiciones desde el chat. Puedo mostrarte el perfil de la liga (tasas base) o los partidos de hoy; dime la liga.", "reglas", "agent.tabla_no_disponible")
    if _texto_fuera_de_alcance(texto):
        if settings.AGENT_PERMISIVIDAD == "abierto" and not _texto_fuera_de_alcance(texto, True):  # cultura de fútbol: sin IA el agente no la responde y lo dice, en vez de rechazarla
            return ("Eso es cultura de fútbol: lo respondo con IA, que está apagada en este turno. Actívala o pídeme un partido, un equipo o una liga. [Sin IA]", "reglas", None)
        return ("Puedo ayudarte dentro de Laplace: agente, memoria, usuarios, planes y analisis deportivo de futbol. Esa consulta queda fuera de mis skills activas.", "reglas", None)
    if re.search(r"\bcomo pinta\s+(?:el\s+|este\s+)?(?:finde|fin de semana|hoy|manana)\b", texto):  # «¿cómo pinta el finde?»: los partidos de ese día
        return ("Consultare los partidos disponibles y aplicare tus filtros.", "reglas", "sports.list_fixtures")
    # «¿qué juega el Madrid hoy?», «¿cuándo juega el Barcelona?»: partidos de un equipo (se filtran por fecha y equipo).
    if re.search(r"\b(?:que|cuando|a que hora|donde)\s+juega\b", texto):
        return ("Consultaré los partidos de esa fecha y los filtraré por el equipo que indicas.", "reglas", "sports.list_fixtures")
    # Una pregunta por las ligas de hoy es una consulta de fixtures, no del catálogo estático.
    # Este caso debe evaluarse antes de la lista de ligas configuradas.
    if re.search(rf"(liga|ligas|competicion).{{0,35}}({agent_jerga.DIAS_Y_FECHAS})|({agent_jerga.DIAS_Y_FECHAS}).{{0,35}}(liga|ligas|competicion)", texto):
        return ("Consultaré las ligas que tienen partidos en la fecha solicitada.", "reglas", "sports.list_playing_leagues")
    if re.search(r"(que|cuales|lista|listar).{0,30}(liga|ligas|competicion)", texto):
        return ("Consultaré las ligas configuradas del bot deportivo.", "reglas", "sports.list_leagues")
    if re.search(rf"(partido|partidos|juego|juegos|fixture|fixtures|que se juega).{{0,40}}({agent_jerga.DIAS_Y_FECHAS}|liga|equipo)|({agent_jerga.DIAS_Y_FECHAS}).{{0,30}}(partido|juego|fixture)", texto):
        return ("Consultare los partidos disponibles y aplicare tus filtros.", "reglas", "sports.list_fixtures")
    if re.search(r"\b(?:cuotas?|odds|mercado)\b", texto) and _partido_desde_mensaje(mensaje):
        return ("Buscaré el partido indicado y consultaré sus cuotas disponibles.", "reglas", "sports.get_odds")
    if _partido_desde_mensaje(mensaje) and (re.search(r"(?:predic|pronost|analiz|compar|quien gana\b|quien crees|quien se lleva|quien la gana|va a ganar|ganara|como pinta|a quien le das|quien pasa|\bover\b|\bunder\b|\bbtts\b|ambos marcan|who wins)", texto) or re.search(r"\b(vs|versus|contra|ante)\b", texto)):
        if re.search(r"solo\s+ia|ia\s+sola|solo\s+inteligencia artificial", texto):
            return ("Prepararé una hipótesis experimental solo IA.", "reglas", "agent.ai_prediction")
        if re.search(r"\bbot\b", texto):
            return ("Buscaré el partido indicado y ejecutaré el análisis estadístico del bot.", "reglas", "sports.predict")
        if seguido:  # MS-3: el usuario sigue a uno de los equipos: no hace falta preguntarle la vía
            return (f"Sigues a {seguido}: buscaré el partido y ejecutaré el análisis.", "reglas", "sports.predict")
        if not settings.AGENT_PREGUNTAR_VIA:  # el agente decide: modelo y bot, sin preguntar (la IA sola solo si la piden con «solo IA»)
            return ("Buscaré el partido indicado y ejecutaré el análisis.", "reglas", "sports.predict")
        return ("¿Qué vía prefieres para esta predicción? Responde «bot» para el análisis estadístico con datos o «IA» para una hipótesis conversacional experimental.", "reglas", "agent.prediction_choice")
    if re.search(r"(cuota|odds|mercado).{0,80}(vs|versus|contra|partido)", texto):
        return ("Buscare el partido indicado y consultare sus cuotas disponibles.", "reglas", "sports.get_odds")
    if re.search(r"futbol|partido|partidos|liga|equipo|predic|cuota|apuesta|fixture|resultado|bot deportivo", texto):
        return ("Puedo consultar al bot deportivo y responder con datos verificables. Dime una fecha, liga, equipo o partido; la IA es opcional para explicaciones, no para inventar datos.", "reglas", "sports.route")
    if es_admin and re.search(r"admin|usuarios|planes|configuracion|proveedor", texto):
        return ("Consulta reconocida como operacion de administrador global. La vista administrativa y sus permisos se aplican desde el backend.", "reglas", "admin.route")
    return ("Puedo ayudarte con Laplace y análisis deportivo de fútbol. Por ejemplo: «partidos de hoy», «ligas que juegan hoy» o «analiza Equipo A vs Equipo B». [Sin IA]", "reglas", None)


def _fuera_de_alcance(mensaje: str) -> bool:
    return _texto_fuera_de_alcance(_texto_normalizado(mensaje), settings.AGENT_PERMISIVIDAD == "abierto")
