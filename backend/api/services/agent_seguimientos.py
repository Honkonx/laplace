"""services/agent_seguimientos.py — seguir equipos y ligas desde el agente (MS-1, MS-2, MS-3 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Un solo almacén para el bot y el agente: los equipos van a `bot_preferencias.equipos_favoritos` y las ligas a `usuarios.favoritos_ligas`. Lo único que cambia es la identidad: el bot de partidos usa el
id de Telegram a secas y el agente `telegram:<id>`; `id_comun` los junta. Guardar exige el consentimiento de siempre (`bot_memoria_repo`): un «sigue a X» nunca lo salta.
Es de reglas, sin IA: el texto lo resuelve el enrutador antes de cualquier proveedor.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import bot_memoria_repo, usuarios_repo

PREFIJO_TELEGRAM = "telegram:"
# Nombres que solos no identifican a nadie («Real», «Atlético»): se pide el nombre completo en vez de adivinar.
GENERICOS = {"real", "club", "fc", "cf", "united", "city", "sporting", "atletico", "deportivo", "union", "racing", "independiente", "olimpia", "universidad", "liga", "copa", "campeonato"}
_TIPO_LIGA = re.compile(r"\b(?:liga|ligas|campeonato|campeonatos|copa|copas|torneo|torneos|champions|libertadores|sudamericana|premier|laliga|bundesliga|serie a|serie b|eredivisie|ligue 1)\b")
_PREFIJO = r"^(?:por favor,?\s+|quiero\s+|puedes\s+|podrias\s+|ahora\s+|ya\s+|oye,?\s+)*"
_SEGUIR = re.compile(_PREFIJO + r"(?:sigue(?:me|lo|la|los|las)?|seguir|sigamos|segui|empieza a seguir|comienza a seguir)\s+(?:a\s+|al\s+|el\s+|la\s+|los\s+|las\s+|del\s+|de\s+)?(?P<nombre>[^.,;!?]{2,60})$")
_DEJAR = re.compile(_PREFIJO + r"(?:deja(?:r)? de seguir|no (?:lo |la )?sigas|no quiero seguir|quita(?:r)? (?:de )?(?:mis )?seguimientos?|olvida(?:r)?(?: a)?)\s+(?:a\s+|al\s+|el\s+|la\s+|los\s+|las\s+|del\s+|de\s+)?(?P<nombre>[^.,;!?]{2,60})$")
_LISTAR = re.compile(r"\b(?:que|cuales|cuantos?|a quien(?:es)?|a que)\b.{0,25}\b(?:sigo|siguiendo|sigues)\b|\bmis seguimientos\b|\bque estoy siguiendo\b|\bmis favoritos\b")
_ACEPTO = re.compile(r"^(?:acepto|si,? acepto|acepto la privacidad)$")
_AVISOS_ON = re.compile(r"^(?:por favor,?\s+)?(?:activa|enciende|prende|pon)\s+(?:los\s+)?avisos$|^avisame\b|^quiero\s+(?:que\s+me\s+avises|recibir\s+avisos|avisos)\b")
_AVISOS_OFF = re.compile(r"^(?:por favor,?\s+)?(?:desactiva|apaga|quita|deten)\s+(?:los\s+)?avisos$|^no\s+me\s+avises\b")
_NO_ES_NOMBRE = re.compile(r"^(?:donde|con|adelante|igual|asi|nomas|por|hasta|que|cuando|sin|mas)\b")
_CONECTORES = re.compile(r"\b(?:en|que|con|para|porque|como|cuando|donde|si|por|hasta|sin)\b")  # «sigue lloviendo en Santiago» no es un equipo
_COLA = re.compile(r"\s+(?:y\s+)?(?:avisame|avisarme|notificame|por favor|porfa|gracias)\b.*$")


def id_comun(user_id: str) -> str:
    """`telegram:123` → `123`: la identidad que ya usa el bot de partidos. Los ids que no son de Telegram (web, app) quedan como están."""
    return user_id[len(PREFIJO_TELEGRAM):] if user_id.startswith(PREFIJO_TELEGRAM) else user_id


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).casefold().strip()


def interpretar(mensaje: str) -> tuple[str, str] | None:
    """(acción, nombre) con acción `seguir_equipo`, `seguir_liga`, `dejar`, `listar` o `aceptar`; None si el mensaje no habla de seguir. Solo mira el INICIO del mensaje para no
    confundir «sigue lloviendo» ni «sigue donde quedamos» con una orden."""
    texto = _plano(re.sub(r"[¿¡]", "", mensaje)).strip()
    if _ACEPTO.match(texto):
        return "aceptar", ""
    if _AVISOS_OFF.match(texto):
        return "avisos_off", ""
    if _AVISOS_ON.match(texto):
        return "avisos_on", ""
    if _LISTAR.search(texto):
        return "listar", ""
    for patron, accion in ((_DEJAR, "dejar"), (_SEGUIR, "seguir")):
        m = patron.match(texto)
        if not m:
            continue
        nombre = _COLA.sub("", m.group("nombre")).strip()
        if len(nombre) < 3 or len(nombre.split()) > 4 or _NO_ES_NOMBRE.match(nombre) or _CONECTORES.search(nombre):
            return None
        if accion == "dejar":
            return "dejar", nombre
        return ("seguir_liga" if _TIPO_LIGA.search(nombre) else "seguir_equipo"), nombre


def _visible(nombre: str) -> str:
    return " ".join(p.capitalize() for p in nombre.split())


def seguidos(db: Session, user_id: str) -> dict[str, list[str]]:
    """Lo que sigue el usuario: `{"equipos": [...], "ligas": [...]}`. Vacío si no hay nada o si la base falla (un accesorio nunca rompe el chat)."""
    uid = id_comun(user_id)
    try:
        return {"equipos": bot_memoria_repo.equipos_favoritos(db, uid), "ligas": usuarios_repo.listar_favoritos_ligas(db, uid)}
    except Exception:  # noqa: BLE001
        db.rollback()
        return {"equipos": [], "ligas": []}


def sigue_a(seguido: dict[str, list[str]], equipo: str) -> str | None:
    """El nombre guardado que corresponde a `equipo` (coincidencia por contención, sin acentos ni mayúsculas, mínimo 4 letras), o None."""
    buscado = _plano(equipo)
    for nombre in seguido.get("equipos", []):
        guardado = _plano(nombre)
        if len(guardado) >= 4 and len(buscado) >= 4 and (guardado in buscado or buscado in guardado):
            return nombre
    return None


def alguno_seguido(db: Session, user_id: str, equipos: tuple[str, str]) -> str | None:
    """MS-3: el equipo seguido que juega ese partido, para pronosticar sin preguntar la vía."""
    s = seguidos(db, user_id)
    return sigue_a(s, equipos[0]) or sigue_a(s, equipos[1])


def _lista(s: dict[str, list[str]]) -> str:
    partes = []
    if s["equipos"]:
        partes.append("Equipos: " + ", ".join(s["equipos"]))
    if s["ligas"]:
        partes.append("Ligas: " + ", ".join(s["ligas"]))
    return "\n".join(partes)


def aplicar(db: Session, user_id: str, accion: str, nombre: str) -> str:
    """Ejecuta la acción y devuelve la respuesta (breve). Nunca lanza: ante un fallo dice que no pudo."""
    uid = id_comun(user_id)
    try:
        if accion == "aceptar":
            if bot_memoria_repo.tiene_consentimiento(db, uid):
                return "Ya tenías aceptada la privacidad."
            bot_memoria_repo.aceptar(db, uid)
            return "Listo, guardaré lo que sigues. Dime qué equipo o liga quieres seguir."
        if accion in ("avisos_on", "avisos_off"):
            r = bot_memoria_repo.configurar_avisos(db, uid, accion == "avisos_on")
            if not r.get("ok"):
                if r.get("error") == "sin_favoritos":
                    return "Primero dime qué sigues: «sigue al Barcelona» o «sigue la Premier League»."
                return r["mensaje"] + " Responde «acepto» para guardar lo que sigues."
            if accion == "avisos_off":
                return "Listo, no te enviaré avisos."
            return "Avisos activados: te avisaré de los partidos de lo que sigues." if settings.AVISOS_FAVORITOS else "Avisos activados, pero el envío automático está apagado en esta instalación."
        if accion == "listar":
            s = seguidos(db, user_id)
            return _lista(s) or "Todavía no sigues nada. Di «sigue al Barcelona» o «sigue la Premier League»."
        if nombre.split()[0] in GENERICOS and len(nombre.split()) == 1:
            return f"«{_visible(nombre)}» no alcanza para identificarlo: escribe el nombre completo, por ejemplo el equipo y su ciudad o país."
        if accion == "dejar":
            visible = _visible(nombre)
            r1, r2 = bot_memoria_repo.quitar_equipo(db, uid, visible), usuarios_repo.quitar_favorito_liga(db, uid, visible)
            return f"Dejé de seguir {visible}." if r1.get("ok") or r2.get("quitado") else f"No seguías a {visible}."
        if not bot_memoria_repo.tiene_consentimiento(db, uid):
            return bot_memoria_repo.TEXTO_CONSENTIMIENTO + "\nResponde «acepto» para guardar lo que sigues."
        visible = _visible(nombre)
        if accion == "seguir_equipo":
            r = bot_memoria_repo.agregar_equipo(db, uid, visible)
            return f"Ahora sigues a {visible}." if r.get("ok") else r["mensaje"]
        if user_id.startswith(PREFIJO_TELEGRAM):
            usuarios_repo.registrar_usuario_telegram(db, user_id=uid, chat_id=uid, first_name="")
        r = usuarios_repo.agregar_favorito_liga(db, uid, visible)
        return f"Ahora sigues {visible}." if r.get("agregado") else r["mensaje"]
    except Exception:  # noqa: BLE001
        db.rollback()
        return "No pude guardar eso ahora. Inténtalo de nuevo en un momento."


def intentar(db: Session, user_id: str, mensaje: str, incognito: bool = False) -> str | None:
    """Si el mensaje es de seguimientos, lo resuelve y devuelve la respuesta; si no, None y el enrutador sigue."""
    interpretado = interpretar(mensaje)
    if interpretado is None:
        return None
    if incognito and interpretado[0] != "listar":
        return "Estás en modo sin memoria: no guardo lo que sigues. Sal de ese modo para seguir equipos o ligas."
    return aplicar(db, user_id, *interpretado)
