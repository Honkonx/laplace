"""services/agent_panel.py — lo que ven y hacen la web y la PWA con sus seguimientos y su perfil (MS-13 del plan `05_PLAN_AGENTE_SEGUIMIENTO_MEMORIA_Y_LENGUAJE.md`).

Es la MISMA lógica del chat de Telegram (`agent_seguimientos`, `agent_perfil`): mismo almacén que el bot de partidos, mismo consentimiento, mismos topes por plan (`planes_seguimiento`) y mismos mensajes. Cada
operación devuelve `{ok, mensaje, ...resumen}` para que la pantalla muestre lo mismo que diría el agente. La identidad es el `sub` del JWT de la sesión web: una cuenta web y una de Telegram no se unen solas.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.db import bot_memoria_repo
from backend.api.models.bot_memoria import BotPerfilUsuario, BotPreferencias
from backend.api.services import agent_perfil, agent_seguimientos, planes_seguimiento

TIPOS = {"equipo": "seguir_equipo", "liga": "seguir_liga"}


def resumen(db: Session, user_id: str, es_admin: bool = False) -> dict:
    uid = agent_seguimientos.id_comun(user_id)
    seguidos = agent_seguimientos.seguidos(db, user_id)
    perfil = db.get(BotPerfilUsuario, uid)
    preferencias = db.get(BotPreferencias, uid)
    return {
        "equipos": seguidos["equipos"], "ligas": seguidos["ligas"], "consentimiento": bot_memoria_repo.tiene_consentimiento(db, uid),
        "avisos": bool(preferencias and preferencias.avisos == 1), "plan": planes_seguimiento.plan_de(db, user_id) or "sin plan",
        "limites": planes_seguimiento.limites(db, user_id, es_admin),
        "perfil": {"zona_horaria": perfil.zona_horaria if perfil else None, "estilo": perfil.estilo if perfil else None,
                   "mercados": [m for m in (perfil.mercados or "").split("|") if m] if perfil else []},
    }


def _respuesta(db: Session, user_id: str, es_admin: bool, ok: bool, mensaje: str) -> dict:
    return {"ok": ok, "mensaje": mensaje, **resumen(db, user_id, es_admin)}


def aceptar(db: Session, user_id: str, es_admin: bool = False) -> dict:
    mensaje = agent_seguimientos.aplicar(db, user_id, "aceptar", "")
    return _respuesta(db, user_id, es_admin, bot_memoria_repo.tiene_consentimiento(db, agent_seguimientos.id_comun(user_id)), mensaje)


def seguir(db: Session, user_id: str, tipo: str, nombre: str, es_admin: bool = False) -> dict:
    accion = TIPOS.get(tipo)
    nombre = agent_seguimientos._plano(nombre)  # noqa: SLF001 — el mismo tratamiento que el chat
    if accion is None or not (3 <= len(nombre) <= 60):
        return _respuesta(db, user_id, es_admin, False, "Indica si es un equipo o una liga y su nombre (de 3 a 60 letras).")
    antes = agent_seguimientos.seguidos(db, user_id)
    mensaje = agent_seguimientos.aplicar(db, user_id, accion, nombre)
    return _respuesta(db, user_id, es_admin, agent_seguimientos.seguidos(db, user_id) != antes, mensaje)


def dejar(db: Session, user_id: str, nombre: str, es_admin: bool = False) -> dict:
    antes = agent_seguimientos.seguidos(db, user_id)
    mensaje = agent_seguimientos.aplicar(db, user_id, "dejar", agent_seguimientos._plano(nombre))  # noqa: SLF001
    return _respuesta(db, user_id, es_admin, agent_seguimientos.seguidos(db, user_id) != antes, mensaje)


def avisos(db: Session, user_id: str, activar: bool, es_admin: bool = False) -> dict:
    mensaje = agent_seguimientos.aplicar(db, user_id, "avisos_on" if activar else "avisos_off", "")
    efecto = db.get(BotPreferencias, agent_seguimientos.id_comun(user_id))
    return _respuesta(db, user_id, es_admin, bool(efecto and efecto.avisos == 1) == activar, mensaje)


def guardar_perfil(db: Session, user_id: str, zona_horaria: str | None = None, estilo: str | None = None, mercados: list[str] | None = None, es_admin: bool = False) -> dict:
    """Guarda cada campo que llega (con las mismas reglas del chat); devuelve los mensajes y si todos se guardaron."""
    mensajes, ok = [], True
    for accion, valor in (("zona", zona_horaria), ("estilo", estilo), ("mercados", "|".join(mercados) if mercados is not None else None)):
        if valor is None:
            continue
        if accion == "estilo" and valor not in agent_perfil.ESTILOS:
            mensajes.append("Estilo no válido: corto, normal o técnico.")
            ok = False
            continue
        if accion == "mercados" and not valor:
            mensajes.append("Elige al menos un mercado: 1x2, goles, ambos marcan o mas de 2,5.")
            ok = False
            continue
        mensaje = agent_perfil.aplicar(db, user_id, accion, valor)
        mensajes.append(mensaje)
        ok = ok and mensaje.startswith("Listo")
    return _respuesta(db, user_id, es_admin, ok and bool(mensajes), " ".join(mensajes) or "No hay nada que guardar.")


def borrar_perfil(db: Session, user_id: str, es_admin: bool = False) -> dict:
    return _respuesta(db, user_id, es_admin, True, agent_perfil.aplicar(db, user_id, "borrar", ""))
