"""Conjunto dorado del agente, tercera tanda: jerga futbolera (apodos, giros, fechas relativas), errores de tecleo, mayúsculas, sin tildes, con y sin «¿?», seguimientos y frases ajenas al fútbol.
El esperado lo fijó el criterio de qué debería hacer un buen agente, no lo que respondía el código; lo que hoy difiere está en BRECHAS (xfail estricto: al corregirlo, el xfail falla y avisa que se mueva a la lista normal)."""
import pytest

from backend.tests._requisitos import requiere_conocimiento_equipos

from backend.api.services import agent_seguimientos
from backend.api.services.agent_runtime_reglas import _normalizar_humano, _respuesta_reglas

DORADO3 = [
    ('quien se lleva el Colo Colo vs la U', 'agent.prediction_choice'),
    ('como pinta el Boca vs River', 'agent.prediction_choice'),
    ('a quien le das el Flamengo vs Palmeiras', 'agent.prediction_choice'),
    ('quien la gana Real Madrid vs Barcelona', 'agent.prediction_choice'),
    ('va a ganar el Liverpool contra el Everton', 'agent.prediction_choice'),
    ('QUIEN GANA EL AMERICA VS CHIVAS', 'agent.prediction_choice'),
    ('quien se lleva el clasico Madrid vs Atletico', 'agent.prediction_choice'),
    ('¿quién gana Bayern vs Dortmund?', 'agent.prediction_choice'),
    ('qien gana Napoli vs Roma', 'agent.prediction_choice'),
    ('q opinas de Inter vs Milan', 'agent.prediction_choice'),
    ('como pinta el Santos vs Corinthians?', 'agent.prediction_choice'),
    ('a quien le das Lazio vs Roma', 'agent.prediction_choice'),
    ('quien la gana Peñarol vs Nacional', 'agent.prediction_choice'),
    ('quien se lleva el Newcastle vs Chelsea', 'agent.prediction_choice'),
    ('pronostico Sevilla vs Betis', 'agent.prediction_choice'),
    ('analiza el Cruz Azul vs Pumas', 'agent.prediction_choice'),
    ('predice Tigres vs Monterrey por favor', 'agent.prediction_choice'),
    ('dame tu pronostico para Independiente vs Racing', 'agent.prediction_choice'),
    ('quien crees que gana Ajax vs Feyenoord', 'agent.prediction_choice'),
    ('prediccion bot Porto vs Benfica', 'sports.predict'),
    ('analiza Valencia vs Villarreal solo ia', 'agent.ai_prediction'),
    ('cuota de Boca vs River', 'sports.get_odds'),
    ('odds del Madrid vs Barcelona', 'sports.get_odds'),
    ('como ves el Lyon vs Marsella', 'agent.prediction_choice'),
    ('quien gana Atlas vs Leon?', 'agent.prediction_choice'),
    ('analiza Palmeiras vs Sao Paulo', 'agent.prediction_choice'),
    ('pronostico del Bolivar vs The Strongest', 'agent.prediction_choice'),
    ('quien la gana: Cobreloa o Colo Colo', 'agent.prediction_choice'),
    ('va a ganar el Madrid contra el Barça', 'agent.prediction_choice'),
    ('ambos marcan en Betis vs Sevilla', 'agent.prediction_choice'),
    ('como pinta el barça contra los merengues', 'agent.prediction_choice'),
    ('quien gana los citizens vs los gunners', 'agent.prediction_choice'),
    ('quien se lleva el Juve vs los nerazzurri', 'agent.prediction_choice'),
    ('a quien le das los xeneizes contra River', 'agent.prediction_choice'),
    ('quien gana los colchoneros contra los cules', 'agent.prediction_choice'),
    ('los red devils contra los spurs quien gana', 'agent.prediction_choice'),
    ('pronostico los rossoneri vs los giallorossi', 'agent.prediction_choice'),
    ('como pinta el cacique contra Universidad Catolica', 'agent.prediction_choice'),
    ('que opinas del atleti contra los blaugranas', 'agent.prediction_choice'),
    ('como viene el barça', 'knowledge.team_profile'),
    ('como viene el atleti', 'knowledge.team_profile'),
    ('como viene la vecchia signora', 'knowledge.team_profile'),
    ('racha de los merengues', 'knowledge.team_profile'),
    ('perfil de los gunners', 'knowledge.team_profile'),
    ('estadisticas de los citizens', 'knowledge.team_profile'),
    ('como vienen los bianconeri', 'knowledge.team_profile'),
    ('partidos del sabado', 'sports.list_fixtures'),
    ('partidos de este finde', 'sports.list_fixtures'),
    ('que partidos hay pasado mañana', 'sports.list_fixtures'),
    ('partidos de ayer', 'sports.list_fixtures'),
    ('juegos del domingo', 'sports.list_fixtures'),
    ('partidos del viernes', 'sports.list_fixtures'),
    ('hay partidos el martes', 'sports.list_fixtures'),
    ('partidos de anteayer', 'sports.list_fixtures'),
    ('que partidos hay el fin de semana', 'sports.list_fixtures'),
    ('partidos de mañana por favor', 'sports.list_fixtures'),
    ('PARTIDOS DE HOY', 'sports.list_fixtures'),
    ('partidos de manana', 'sports.list_fixtures'),
    ('q partidos hay oy', 'sports.list_fixtures'),
    ('que juegos hay el miercoles', 'sports.list_fixtures'),
    ('partidos del jueves en la champions', 'sports.list_fixtures'),
    ('que juega el madrid hoy', 'sports.list_fixtures'),
    ('cuando juega el barcelona', 'sports.list_fixtures'),
    ('a que hora juega boca', 'sports.list_fixtures'),
    ('donde juega el river', 'sports.list_fixtures'),
    ('partidos de la premier el sabado', 'sports.list_fixtures'),
    ('fixture del finde', 'sports.list_fixtures'),
    ('juegos de pasado manana', 'sports.list_fixtures'),
    ('que partidos hay mañana', 'sports.list_fixtures'),
    ('ligas que juegan hoy', 'sports.list_playing_leagues'),
    ('que ligas juegan mañana', 'sports.list_playing_leagues'),
    ('ligas con partidos este finde', 'sports.list_playing_leagues'),
    ('que ligas tienen juegos el sabado', 'sports.list_playing_leagues'),
    ('cuales ligas juegan pasado mañana', 'sports.list_playing_leagues'),
    ('lista de ligas por favor', 'sports.list_leagues'),
    ('cuales son las ligas que cubres', 'sports.list_leagues'),
    ('QUE LIGAS MANEJAS', 'sports.list_leagues'),
    ('que competiciones tienes', 'sports.list_leagues'),
    ('cuanto es 2+2', None),
    ('dame una receta de lasaña', None),
    ('quien gano las elecciones', None),
    ('como esta el clima en lima', None),
    ('cuentame un chiste', None),
    ('escribe un poema de amor', None),
    ('que hora es en tokio', None),
    ('traduce hello al español', None),
    ('quien es el presidente de argentina', None),
    ('hablame de politica', None),
    ('como hago un pastel de chocolate', None),
    ('escribe un script en javascript', None),
    ('que es la fotosintesis', None),
    ('cual es la capital de francia', None),
    ('recomiendame una pelicula', None),
    ('quien gano el oscar', None),
    ('cuanto cuesta un iphone', None),
    ('como se baila la salsa', None),
    ('dime el horoscopo de hoy', None),
    ('quien paso por mi casa ayer', None),
    ('como pinta mi dia', None),
    ('a quien le das las gracias', None),
    ('que opinas de la nueva serie de netflix', None),
    ('resumen de la revolucion francesa', None),
    ('explicame la teoria de la relatividad', None),
    ('temperatura en santiago', None),
    ('cuanto vale el bitcoin', None),
    ('qien se lleva el Gremio vs Inter de Porto Alegre', 'agent.prediction_choice'),
    ('kien gana Tigres vs America', 'agent.prediction_choice'),
    ('pronosticame el Liverpool vs City', 'agent.prediction_choice'),
    ('vamos q pronostico para Benfica vs Sporting', 'agent.prediction_choice'),
    ('que partidos hay manana en la liga mx', 'sports.list_fixtures'),
    ('partidos del sabado en españa', 'sports.list_fixtures'),
    ('QUE LIGAS JUEGAN HOY', 'sports.list_playing_leagues'),
    ('ligas q juegan oy', 'sports.list_playing_leagues'),
    ('quien paso la semana pasada en el trabajo', None),
    ('dime como cocinar arroz', None),
    ('analiza mi declaracion de impuestos', None),
    ('pasame el codigo de un login en python', None),
    ('sabes cantar', None),
    ('forma del cacique', 'knowledge.team_profile'),
    ('QUE TAL VIENE EL JUVE', 'knowledge.team_profile'),
    ('como llegan los xeneizes', 'knowledge.team_profile'),
    ('que se juega el lunes', 'sports.list_fixtures'),
    ('resultados de ayer', 'sports.recent_results'),
    ('que ligas hay', 'sports.list_leagues'),
    ('necesito ayuda con mi tarea de matematicas', None),
    ('a ver, quien la gana: Girona vs Getafe?', 'agent.prediction_choice'),
    ('¡¡quien gana Bayern vs Leverkusen!!', 'agent.prediction_choice'),
]

# (frase, esperado, real hoy): el esperado es el comportamiento que debería tener un buen agente
BRECHAS = [
]  # vacía: las 9 brechas que halló el subagente se corrigieron el 2026-11-13 y pasaron a DORADO3 («resultados de ayer» se aceptó como `sports.recent_results`: es lo que pide la frase)

SEGUIMIENTOS = [
    ('sigue al Madrid', 'seguir_equipo'),
    ('sigue a Colo Colo', 'seguir_equipo'),
    ('quiero seguir al River', 'seguir_equipo'),
    ('seguir la Premier League', 'seguir_liga'),
    ('sigue la liga chilena', 'seguir_liga'),
    ('deja de seguir al Madrid', 'dejar'),
    ('que equipos sigo', 'listar'),
    ('dejar de seguir la Champions', 'dejar'),
    ('SIGUE AL BARÇA', 'seguir_equipo'),
    ('sigue lloviendo en santiago', None),
    ('sigue donde quedamos', None),
    ('acepto', 'aceptar'),
    ('siguelo al barcelona', 'seguir_equipo'),
    ('ya no sigas al Boca', 'dejar'),
    ('a quien sigo', 'listar'),
]

# (frase, acción esperada, acción real hoy)
BRECHAS_SEGUIMIENTO = []  # vacía: las 3 se corrigieron el 2026-11-13 y pasaron a SEGUIMIENTOS


def _caso(frase, esperada):
    marcas = [requiere_conocimiento_equipos] if esperada == "knowledge.team_profile" else []  # el perfil de un equipo necesita el conocimiento por equipo (no se publica)
    return pytest.param(frase, esperada, marks=marcas)


def _ruta(frase):
    return _respuesta_reglas(_normalizar_humano(frase), False)[2]


def _accion(frase):
    interpretado = agent_seguimientos.interpretar(frase)
    return interpretado[0] if interpretado else None


@pytest.mark.parametrize("frase,esperada", [_caso(f, e) for f, e in DORADO3])
def test_la_frase_va_a_la_herramienta_esperada(frase, esperada):
    assert _ruta(frase) == esperada


@pytest.mark.parametrize("frase,esperada,real", [pytest.param(f, e, r, marks=pytest.mark.xfail(strict=True, reason=f"esperaba {e}, hoy da {r}")) for f, e, r in BRECHAS])
def test_brechas_de_enrutamiento(frase, esperada, real):
    assert _ruta(frase) == esperada


@pytest.mark.parametrize("frase,esperada", SEGUIMIENTOS)
def test_seguimientos(frase, esperada):
    assert _accion(frase) == esperada


@pytest.mark.parametrize("frase,esperada,real", [pytest.param(f, e, r, marks=pytest.mark.xfail(strict=True, reason=f"esperaba {e}, hoy da {r}")) for f, e, r in BRECHAS_SEGUIMIENTO])
def test_brechas_de_seguimiento(frase, esperada, real):
    assert _accion(frase) == esperada


def test_lo_ajeno_al_futbol_nunca_dispara_una_herramienta_deportiva():
    for frase, esperada in DORADO3:
        if esperada is None:
            assert (_ruta(frase) or "").split(".")[0] != "sports", frase
