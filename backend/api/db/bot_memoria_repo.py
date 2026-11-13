"""db/bot_memoria_repo.py — memoria mínima del bot con consentimiento (MB-30…33).

Reglas: (1) nada se guarda del historial sin consentimiento vigente; (2) la personalización SOLO reordena listas, jamás cambia una cifra; (3) `olvidar` borra todo lo del usuario en las tablas
`bot_*`, sus ligas favoritas y sus votos de encuesta; (4) el historial se recorta a 90 días y a 200 filas por usuario.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.api.models.bot_memoria import BotAvisoEnviado, BotConsentimiento, BotHistorialConsulta, BotPerfilUsuario, BotPreferencias
from backend.api.models.predicciones import PrediccionUsuario
from backend.api.models.usuarios import Usuario

VERSION_CONSENTIMIENTO = "bot-1"
MAX_EQUIPOS = 5
RETENCION_DIAS = 90
MAX_HISTORIAL = 200
TABLAS_DEL_BOT = (BotPreferencias, BotHistorialConsulta, BotConsentimiento, BotAvisoEnviado, BotPerfilUsuario)
TEXTO_CONSENTIMIENTO = (
    "Guardo tus equipos favoritos y los partidos que consultas (90 días) solo para ordenar tus listas. "
    "Nunca cambia un pronóstico. /privacidad aceptar · /privacidad revocar · /olvidame borra todo."
)


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tiene_consentimiento(db: Session, user_id: str) -> bool:
    fila = db.get(BotConsentimiento, str(user_id))
    return bool(fila and fila.revocado_en is None and fila.version == VERSION_CONSENTIMIENTO)


def aceptar(db: Session, user_id: str) -> None:
    uid = str(user_id)
    fila = db.get(BotConsentimiento, uid)
    if fila is None:
        db.add(BotConsentimiento(user_id=uid, version=VERSION_CONSENTIMIENTO, aceptado_en=_ahora()))
    else:
        fila.version, fila.aceptado_en, fila.revocado_en = VERSION_CONSENTIMIENTO, _ahora(), None
    db.commit()


def revocar(db: Session, user_id: str) -> None:
    """Retira el consentimiento y borra lo que dependía de él (historial y equipos favoritos); deja constancia de la revocación."""
    uid = str(user_id)
    fila = db.get(BotConsentimiento, uid)
    if fila is not None:
        fila.revocado_en = _ahora()
    db.query(BotHistorialConsulta).filter(BotHistorialConsulta.user_id == uid).delete()
    db.query(BotPreferencias).filter(BotPreferencias.user_id == uid).delete()
    db.query(BotAvisoEnviado).filter(BotAvisoEnviado.user_id == uid).delete()
    db.query(BotPerfilUsuario).filter(BotPerfilUsuario.user_id == uid).delete()
    db.commit()


def equipos_favoritos(db: Session, user_id: str) -> list[str]:
    fila = db.get(BotPreferencias, str(user_id))
    if fila is None or not fila.personalizar or not fila.equipos_favoritos:
        return []
    return [e for e in fila.equipos_favoritos.split("|") if e]


def agregar_equipo(db: Session, user_id: str, equipo: str) -> dict:
    uid, equipo = str(user_id), equipo.strip()
    if not tiene_consentimiento(db, uid):
        return {"ok": False, "error": "sin_consentimiento", "mensaje": TEXTO_CONSENTIMIENTO}
    if not equipo or "|" in equipo or len(equipo) > 60:
        return {"ok": False, "error": "equipo_invalido", "mensaje": "Escribe el nombre del equipo (máximo 60 caracteres)."}
    fila = db.get(BotPreferencias, uid) or BotPreferencias(user_id=uid, idioma="es", personalizar=1, avisos=0, actualizado_en=_ahora())
    actuales = [e for e in (fila.equipos_favoritos or "").split("|") if e]
    if any(e.lower() == equipo.lower() for e in actuales):
        return {"ok": False, "error": "ya_existe", "favoritos": actuales, "mensaje": f"{equipo} ya está en tus favoritos."}
    from backend.api.services import planes_seguimiento  # noqa: PLC0415 — MS-11: el tope depende del plan

    maximo = planes_seguimiento.limites(db, uid)["equipos"]
    if len(actuales) >= maximo:
        return {"ok": False, "error": "limite_alcanzado", "favoritos": actuales, "mensaje": f"Máximo {maximo} equipos con tu plan."}
    fila.equipos_favoritos, fila.actualizado_en = "|".join(actuales + [equipo]), _ahora()
    db.merge(fila)
    db.commit()
    return {"ok": True, "favoritos": actuales + [equipo], "mensaje": f"{equipo} agregado."}


def quitar_equipo(db: Session, user_id: str, equipo: str) -> dict:
    uid = str(user_id)
    fila = db.get(BotPreferencias, uid)
    actuales = [e for e in (fila.equipos_favoritos if fila and fila.equipos_favoritos else "").split("|") if e]
    nuevos = [e for e in actuales if e.lower() != equipo.strip().lower()]
    if fila is None or len(nuevos) == len(actuales):
        return {"ok": False, "error": "no_encontrado", "favoritos": actuales, "mensaje": f"{equipo} no estaba en tus favoritos."}
    fila.equipos_favoritos, fila.actualizado_en = ("|".join(nuevos) or None), _ahora()
    db.commit()
    return {"ok": True, "favoritos": nuevos, "mensaje": f"{equipo} quitado."}


def registrar_consulta(db: Session, user_id: str, partido_id: str, fecha_partido: str | None = None) -> bool:
    """Guarda que el usuario consultó un partido; sin consentimiento NO guarda nada. Poda por antigüedad y por cantidad."""
    uid = str(user_id)
    if not tiene_consentimiento(db, uid):
        return False
    db.add(BotHistorialConsulta(user_id=uid, partido_id=str(partido_id)[:64], fecha_partido=fecha_partido, creado_en=_ahora()))
    db.flush()
    limite = (datetime.now(timezone.utc) - timedelta(days=RETENCION_DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.query(BotHistorialConsulta).filter(BotHistorialConsulta.user_id == uid, BotHistorialConsulta.creado_en < limite).delete()
    ids = [i for (i,) in db.query(BotHistorialConsulta.id).filter(BotHistorialConsulta.user_id == uid).order_by(BotHistorialConsulta.id.desc()).offset(MAX_HISTORIAL).all()]
    if ids:
        db.query(BotHistorialConsulta).filter(BotHistorialConsulta.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return True


def historial(db: Session, user_id: str, limite: int = 10) -> list[dict]:
    filas = db.query(BotHistorialConsulta).filter(BotHistorialConsulta.user_id == str(user_id)).order_by(BotHistorialConsulta.id.desc()).limit(limite).all()
    return [{"partido_id": f.partido_id, "fecha_partido": f.fecha_partido, "creado_en": f.creado_en} for f in filas]


def olvidar(db: Session, user_id: str) -> dict:
    """`/olvidame`: borra TODO lo del usuario en el bot y devuelve cuántas filas salieron de cada lugar (para poder comprobarlo)."""
    uid = str(user_id)
    borrado = {m.__tablename__: db.query(m).filter(m.user_id == uid).delete() for m in TABLAS_DEL_BOT}
    borrado["predicciones_usuario"] = db.query(PrediccionUsuario).filter(PrediccionUsuario.telegram_user_id == uid).delete()
    usuario = db.query(Usuario).filter(Usuario.device_id == uid).first()
    borrado["favoritos_ligas"] = 1 if usuario is not None and usuario.favoritos_ligas else 0
    if usuario is not None:
        usuario.favoritos_ligas = None
    db.commit()
    return borrado


def ordenar_por_favoritos(elementos: list, nombre_liga=None, nombres_equipo=None, ligas_favoritas: list[str] | None = None, equipos: list[str] | None = None) -> list:
    """Reordena una lista (ligas o partidos) poniendo primero lo favorito; es un orden estable y NO añade, quita ni modifica elementos: la personalización no toca ninguna cifra."""
    ligas_f = {x.lower() for x in (ligas_favoritas or [])}
    equipos_f = {x.lower() for x in (equipos or [])}
    if not ligas_f and not equipos_f:
        return list(elementos)

    def es_favorito(e) -> bool:
        liga = (nombre_liga(e) if nombre_liga else "") or ""
        if liga.lower() in ligas_f:
            return True
        return any((n or "").lower() in equipos_f for n in (nombres_equipo(e) if nombres_equipo else ()))

    return sorted(elementos, key=lambda e: not es_favorito(e))


def configurar_avisos(db: Session, user_id: str, activar: bool) -> dict:
    """Activa o apaga el aviso diario de partidos de los favoritos. Exige consentimiento vigente y al menos un favorito (liga o equipo) para activarlo."""
    uid = str(user_id)
    if activar:
        if not tiene_consentimiento(db, uid):
            return {"ok": False, "error": "sin_consentimiento", "mensaje": TEXTO_CONSENTIMIENTO}
        from backend.api.db import usuarios_repo

        if not equipos_favoritos(db, uid) and not usuarios_repo.listar_favoritos_ligas(db, uid):
            return {"ok": False, "error": "sin_favoritos", "mensaje": "Primero guarda un favorito: /equipos agregar <equipo> o /favoritos agregar <liga>."}
    fila = db.get(BotPreferencias, uid) or BotPreferencias(user_id=uid, idioma="es", personalizar=1, avisos=0, actualizado_en=_ahora())
    fila.avisos, fila.actualizado_en = 1 if activar else 0, _ahora()
    db.merge(fila)
    db.commit()
    return {"ok": True, "avisos": bool(activar), "mensaje": "Te avisaré cada mañana si juega alguno de tus favoritos. /avisos off para dejarlo." if activar else "Avisos apagados."}


def avisos_del_dia(db: Session, partidos: list[dict]) -> dict[str, list[dict]]:
    """{user_id: partidos del día que tocan a sus favoritos} solo para quien activó los avisos y mantiene el consentimiento. No incluye pronósticos: es un aviso, no una recomendación."""
    from backend.api.db import usuarios_repo

    salida: dict[str, list[dict]] = {}
    for fila in db.query(BotPreferencias).filter(BotPreferencias.avisos == 1).all():
        if not tiene_consentimiento(db, fila.user_id):
            continue
        equipos = {e.lower() for e in (fila.equipos_favoritos or "").split("|") if e}
        ligas = {x.lower() for x in usuarios_repo.listar_favoritos_ligas(db, fila.user_id)}
        tocan = [p for p in partidos if (p.get("local") or "").lower() in equipos or (p.get("visitante") or "").lower() in equipos or (p.get("liga") or "").lower() in ligas]
        if tocan:
            salida[fila.user_id] = tocan
    return salida
