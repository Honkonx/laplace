"""services/agent_jerga.py — la jerga del fútbol y las fechas como las dice la gente (MS-7 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Solo reglas, sin IA y sin red: un diccionario de apodos que apunta a UN equipo (los ambiguos como «millonarios» o «azules» no entran: nombran a varios) y fechas relativas («el sábado», «este finde»,
«pasado mañana», «ayer»). Primero va el diccionario y la IA queda de respaldo: el enrutador de reglas ve nombres canónicos y fechas resueltas.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

# apodo (sin acentos, en minúsculas) → nombre con el que el resto del sistema reconoce al equipo. Solo apodos que designan a un único equipo.
APODOS: dict[str, str] = {
    "barca": "Barcelona", "cules": "Barcelona", "blaugrana": "Barcelona", "blaugranas": "Barcelona",
    "merengues": "Real Madrid", "madridistas": "Real Madrid", "la casa blanca": "Real Madrid",
    "atleti": "Atlético de Madrid", "colchoneros": "Atlético de Madrid",
    "citizens": "Manchester City", "red devils": "Manchester United", "diablos rojos": "Manchester United", "gunners": "Arsenal", "spurs": "Tottenham", "toffees": "Everton",
    "juve": "Juventus", "la vecchia signora": "Juventus", "bianconeri": "Juventus", "nerazzurri": "Inter", "rossoneri": "Milan", "giallorossi": "Roma",
    "xeneizes": "Boca Juniors", "cacique": "Colo-Colo", "bavaros": "Bayern Munich",
}
_DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
_NOMBRE_DIA = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo"}
_DIA = re.compile(r"\b(?:el\s+|este\s+|proximo\s+)?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b")
# el artículo que acompaña al apodo («los merengues», «el barça») se va con él: el nombre del equipo queda sin «los» ni «el»
_APODOS_RE = re.compile(r"(?:\b(el|la|los|las|del|al)\s+)?\b(" + "|".join(re.escape(a) for a in sorted(APODOS, key=len, reverse=True)) + r")\b")
REQUIERE_ARTICULO = {"cacique"}  # apodos que sueltos son una palabra común: solo valen con «el», «del», «al»…
_CONTRACCION = {"del": "de ", "al": "a "}  # «forma del cacique» → «forma de Colo-Colo»
# Las palabras que marcan una fecha en una frase (para que el enrutador de reglas reconozca «partidos del domingo» como una consulta de fixtures).
DIAS_Y_FECHAS = r"\b(?:hoy|manana|pasado manana|ayer|anteayer|fecha|finde|fin de semana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)"  # con \b delante: «Bayern» no es «ayer»


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).casefold()


def normalizar_apodos(mensaje: str) -> str:
    """Cambia cada apodo conocido por el nombre del equipo, respetando el resto del mensaje. «quien gana el barça y los merengues» → «quien gana el Barcelona y los Real Madrid»."""
    plano = _plano(mensaje)
    if len(plano) != len(mensaje):  # la normalización cambió el largo: no se pueden mapear posiciones, el mensaje queda como está
        return mensaje
    salida, cursor = [], 0
    for m in _APODOS_RE.finditer(plano):
        if m.group(2) in REQUIERE_ARTICULO and not m.group(1):
            continue
        salida += [mensaje[cursor:m.start()], _CONTRACCION.get(m.group(1) or "", "") + APODOS[m.group(2)]]
        cursor = m.end()
    return "".join(salida) + mensaje[cursor:]


def fecha(mensaje: str, hoy: date | None = None) -> date:
    """La fecha a la que se refiere el mensaje; hoy si no dice ninguna. Un día de la semana es el próximo (o hoy si es ese mismo día); «este finde» es el próximo sábado (o hoy si ya es fin de semana)."""
    hoy = hoy or date.today()
    texto = _plano(mensaje)
    if re.search(r"\bpasado\s+manana\b", texto):
        return hoy + timedelta(days=2)
    if re.search(r"\banteayer\b", texto):
        return hoy - timedelta(days=2)
    if re.search(r"\bayer\b", texto):
        return hoy - timedelta(days=1)
    if re.search(r"\bmanana\b", texto):
        return hoy + timedelta(days=1)
    if re.search(r"\bhoy\b", texto):
        return hoy
    if re.search(r"\b(?:finde|fin\s+de\s+semana)\b", texto):
        return hoy + timedelta(days=max(0, 5 - hoy.weekday())) if hoy.weekday() <= 5 else hoy
    m = _DIA.search(texto)
    if m:
        return hoy + timedelta(days=(_DIAS[m.group(1)] - hoy.weekday()) % 7)
    return hoy


def etiqueta(dia: date, hoy: date | None = None) -> str:
    """Cómo se nombra ese día ante quien lee: hoy, mañana, ayer, pasado mañana o «el sábado 15/11»."""
    hoy = hoy or date.today()
    delta = (dia - hoy).days
    if delta in (-1, 0, 1, 2):
        return {-1: "ayer", 0: "hoy", 1: "mañana", 2: "pasado mañana"}[delta]
    return f"el {_NOMBRE_DIA[dia.weekday()]} {dia:%d/%m}"
