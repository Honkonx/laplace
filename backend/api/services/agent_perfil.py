"""services/agent_perfil.py — memoria TIPADA del usuario (MS-6 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Tres campos con tope duro (nunca se trunca en silencio) y solo con el consentimiento de siempre: la zona horaria, el estilo de respuesta (corto, normal, técnico) y los mercados que mira (hasta 4).
Se dice con palabras («estoy en Chile», «responde corto», «me interesan goles y ambos marcan»), se ve con «mi perfil» y se borra con «borra mi perfil» o con `/olvidame`.
Para la IA va una instantánea al construir cada respuesta; para los avisos, la zona horaria decide la hora y el horario activo de cada persona. Es de reglas, sin IA, y es la misma identidad del bot (`id_comun`).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from backend.api.db import bot_memoria_repo
from backend.api.models.bot_memoria import BotPerfilUsuario
from backend.api.services.agent_seguimientos import id_comun

ESTILOS = {"corto": "corto", "breve": "corto", "resumido": "corto", "tecnico": "tecnico", "detallado": "tecnico", "normal": "normal"}
MERCADOS = {"1x2": "1x2", "resultado": "1x2", "goles": "goles", "gol": "goles", "ambos marcan": "ambos marcan", "btts": "ambos marcan", "mas de 2,5": "mas de 2,5", "mas de 2.5": "mas de 2,5", "over": "mas de 2,5"}
MAX_MERCADOS = 4
MAX_LARGO = 40
ZONAS = {
    "chile": "America/Santiago", "santiago": "America/Santiago", "argentina": "America/Argentina/Buenos_Aires", "buenos aires": "America/Argentina/Buenos_Aires",
    "mexico": "America/Mexico_City", "ciudad de mexico": "America/Mexico_City", "colombia": "America/Bogota", "bogota": "America/Bogota", "peru": "America/Lima", "lima": "America/Lima",
    "uruguay": "America/Montevideo", "montevideo": "America/Montevideo", "venezuela": "America/Caracas", "caracas": "America/Caracas", "ecuador": "America/Guayaquil", "quito": "America/Guayaquil",
    "bolivia": "America/La_Paz", "paraguay": "America/Asuncion", "brasil": "America/Sao_Paulo", "sao paulo": "America/Sao_Paulo", "espana": "Europe/Madrid", "madrid": "Europe/Madrid",
    "portugal": "Europe/Lisbon", "lisboa": "Europe/Lisbon", "estados unidos": "America/New_York", "nueva york": "America/New_York", "costa rica": "America/Costa_Rica", "panama": "America/Panama",
}
_ZONA = re.compile(r"^(?:mi zona horaria es|mi zona es|zona horaria|estoy en|vivo en|mi hora es la de|usa la hora de)\s+(?P<valor>[^.,;!?]{2,40})$")
_ESTILO = re.compile(r"^(?:respondeme|responde|contestame|hablame)(?: siempre)?(?: mas)?(?: de forma| en forma)?\s+(?P<valor>corto|breve|resumido|tecnico|detallado|normal)\b")
_MERCADOS = re.compile(r"^(?:me interesan?|miro|quiero ver|muestrame)(?: solo)?\s+(?P<valor>[^.;!?]{2,80})$")
_VER = re.compile(r"^(?:ver |muestrame |dime )?(?:mi perfil|mis preferencias)$")
# MS-10: la retroalimentación del usuario ajusta el estilo (nunca las probabilidades) y se revierte con «como antes» o «estilo normal»
_RETRO_CORTO = re.compile(r"^(?:mas (?:corto|breve|resumido)|(?:muy|demasiado) largo|menos largo|menos detalle|sin tanto detalle)$")
_RETRO_TECNICO = re.compile(r"^(?:mas (?:tecnico|detallado|completo)|mas detalle|con mas detalle|explicame mas)$")
_RETRO_NORMAL = re.compile(r"^(?:estilo normal|vuelve al estilo normal|como antes|menos tecnico|mas simple|mas sencillo)$")
_BORRAR = re.compile(r"^(?:olvida|borra|elimina|quita)(?:r)? (?:mi |mis )?(?:perfil|preferencias)$")


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).casefold().strip()


def _zona_valida(valor: str) -> str | None:
    """Nombre IANA de lo que dijo la persona (un nombre IANA tal cual o un país o ciudad conocidos), o None."""
    candidato = ZONAS.get(_plano(valor))
    if candidato is None and "/" in valor:
        candidato = valor.strip()
    try:
        return candidato if candidato and ZoneInfo(candidato) else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def interpretar(mensaje: str) -> tuple[str, str] | None:
    """(acción, valor): `zona`, `estilo`, `mercados`, `ver` o `borrar`; None si el mensaje no habla del perfil. Solo mira el INICIO del mensaje y no ejecuta una pregunta («?»)."""
    original = re.sub(r"[¿¡]", "", mensaje).strip()
    texto = _plano(original)
    if _BORRAR.match(texto):
        return "borrar", ""
    if _VER.match(texto):
        return "ver", ""
    for patron, estilo in ((_RETRO_CORTO, "corto"), (_RETRO_TECNICO, "tecnico"), (_RETRO_NORMAL, "normal")):
        if patron.match(texto):
            return "estilo", estilo
    if (m := _ESTILO.match(texto)):
        return "estilo", m.group("valor")
    if _ZONA.match(texto):
        crudo = re.match(r"(?i)^(?:mi zona horaria es|mi zona es|zona horaria|estoy en|vivo en|mi hora es la de|usa la hora de)\s+([^.,;!?]{2,40})$", original)
        valor = (crudo.group(1) if crudo else _ZONA.match(texto).group("valor")).strip()
        if re.match(r"(?:estoy en|vivo en)\b", texto) and _zona_valida(valor) is None:
            return None  # «estoy en el estadio» no es una zona horaria: la conversación sigue
        return "zona", valor
    if (m := _MERCADOS.match(texto)):
        valor = m.group("valor")
        hallados = sorted(((mm.start(), MERCADOS[k]) for k in MERCADOS for mm in re.finditer(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", valor)), key=lambda t: t[0])
        encontrados = [nombre for _, nombre in hallados]  # en el orden en que la persona los dijo
        return ("mercados", "|".join(dict.fromkeys(encontrados))) if encontrados else None
    return None


def perfil(db: Session, user_id: str) -> BotPerfilUsuario | None:
    try:
        return db.get(BotPerfilUsuario, id_comun(user_id))
    except Exception:  # noqa: BLE001 — accesorio: nunca rompe el chat
        db.rollback()
        return None


def _texto_perfil(p: BotPerfilUsuario | None) -> str:
    if p is None or not (p.zona_horaria or p.estilo or p.mercados):
        return "Todavía no guardé nada de tu perfil. Dime, por ejemplo: «estoy en Chile», «responde corto» o «me interesan goles y ambos marcan»."
    partes = [f"zona horaria {p.zona_horaria}" if p.zona_horaria else "", f"estilo {p.estilo}" if p.estilo else "", f"mercados: {p.mercados.replace('|', ', ')}" if p.mercados else ""]
    return "Tu perfil: " + "; ".join(x for x in partes if x) + ". Se borra con «borra mi perfil»."


def aplicar(db: Session, user_id: str, accion: str, valor: str) -> str:
    """Ejecuta la acción y devuelve la respuesta. Nunca lanza: ante un fallo dice que no pudo."""
    uid = id_comun(user_id)
    try:
        if accion == "ver":
            return _texto_perfil(db.get(BotPerfilUsuario, uid))
        if accion == "borrar":
            borrado = db.query(BotPerfilUsuario).filter(BotPerfilUsuario.user_id == uid).delete()
            db.commit()
            return "Borré tu perfil." if borrado else "No tenías un perfil guardado."
        if not bot_memoria_repo.tiene_consentimiento(db, uid):
            return bot_memoria_repo.TEXTO_CONSENTIMIENTO + "\nResponde «acepto» para guardar tu perfil."
        fila = db.get(BotPerfilUsuario, uid) or BotPerfilUsuario(user_id=uid, actualizado_en="")
        if accion == "zona":
            zona = _zona_valida(valor)
            if zona is None:
                return f"No reconozco «{valor[:MAX_LARGO]}» como zona horaria. Dime un país o ciudad conocidos (Chile, Madrid, Bogotá…) o el nombre completo, como America/Santiago."
            fila.zona_horaria, respuesta = zona, f"Listo: zona horaria {zona}. Los avisos llegarán en tu hora."
        elif accion == "estilo":
            fila.estilo = ESTILOS[valor]
            respuesta = f"Listo: respondo en estilo {fila.estilo}."
        elif accion == "mercados":
            mercados = valor.split("|")
            if len(mercados) > MAX_MERCADOS:
                return f"El tope es de {MAX_MERCADOS} mercados; elige hasta {MAX_MERCADOS}."
            fila.mercados, respuesta = valor, "Listo: me fijo en " + ", ".join(mercados) + "."
        else:
            return "No entendí qué guardar."
        fila.actualizado_en = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        db.merge(fila)
        db.commit()
        return respuesta
    except Exception:  # noqa: BLE001
        db.rollback()
        return "No pude guardar eso ahora. Inténtalo de nuevo en un momento."


def intentar(db: Session, user_id: str, mensaje: str, incognito: bool = False) -> str | None:
    """Si el mensaje es del perfil lo resuelve y devuelve la respuesta; si no, None. En modo sin memoria no se guarda nada (ver y borrar sí)."""
    interpretado = interpretar(mensaje)
    if interpretado is None:
        return None
    if incognito and interpretado[0] not in ("ver", "borrar"):
        return "Estás en modo sin memoria: no guardo tu perfil. Sal de ese modo para guardarlo."
    return aplicar(db, user_id, *interpretado)


def instantanea_para_ia(db: Session, user_id: str) -> str:
    """Una línea con lo guardado, para el prompt de la IA al construir la respuesta («instantánea»); vacío si no hay nada. Nunca cambia probabilidades."""
    p = perfil(db, user_id)
    if p is None:
        return ""
    partes = []
    if p.estilo == "corto":
        partes.append("responde en pocas líneas")
    elif p.estilo == "tecnico":
        partes.append("responde con más detalle técnico")
    if p.mercados:
        partes.append("le interesan los mercados: " + p.mercados.replace("|", ", "))
    if p.zona_horaria:
        partes.append(f"su zona horaria es {p.zona_horaria}")
    return ("Preferencias guardadas por el usuario (úsalas para el estilo, nunca para cambiar cifras): " + "; ".join(partes) + ".") if partes else ""


def zona_de(db: Session, user_id: str) -> ZoneInfo | None:
    p = perfil(db, user_id)
    try:
        return ZoneInfo(p.zona_horaria) if p and p.zona_horaria else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def hora_para(hora_chile: str | None, fecha_iso: str, zona: ZoneInfo | None) -> str | None:
    """Convierte una hora «HH:MM» de Chile del día `fecha_iso` (AAAA-MM-DD) a la zona de la persona; sin zona o con un dato raro devuelve la hora tal cual."""
    if not hora_chile or zona is None:
        return hora_chile
    try:
        local = datetime.strptime(f"{fecha_iso} {hora_chile}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/Santiago"))
        return local.astimezone(zona).strftime("%H:%M")
    except ValueError:
        return hora_chile
