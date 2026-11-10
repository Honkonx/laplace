"""db/predicciones_usuario_repo.py — Votos reales de usuarios sobre quién gana un partido
(2026-09-10) — primer paso de la visión "Laplace-Agents le pregunta a los usuarios, tipo
encuestas" (pedido original del usuario, ver el registro de decisiones del proyecto).

Esta ronda SOLO captura el voto (`registrar_voto`) y permite leer el agregado real
(`leer_agregado`) — "auto-alimentarse y aprender" de estos votos (conectarlo a
`laplace-agents/` o al motor de consenso) es una decisión de diseño más grande, deliberadamente
fuera de esta ronda. Nada en el repo todavía lee `leer_agregado` para otra cosa que no sea el
propio test de esta ronda.
"""
from __future__ import annotations


from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.predicciones import PrediccionUsuario

PICKS_VALIDOS = ("local", "empate", "visitante")


def _now_str() -> str:
    """`creado_en` — UTC, mismo patrón que el resto de `db/*_repo.py` (ver docstring de
    `jobs_repo._now_str`). Tabla nueva de esta misma ronda, sin filas previas en otro huso."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def registrar_voto(
    db: Session,
    match_id: str,
    telegram_user_id: str,
    pick: str,
    razon: str | None = None,
) -> dict:
    """Guarda el voto real de un usuario para un partido. Si el mismo usuario ya había votado
    para este `match_id`, actualiza su voto (upsert por `match_id` + `telegram_user_id`, ver la
    unique constraint del modelo) en vez de acumular filas duplicadas del mismo usuario — eso
    inflaría el agregado de `leer_agregado` sin aportar señal nueva.

    Devuelve `{"ok": False, "error": ...}` si `pick` no es uno de los 3 valores válidos —
    el caller (el bot) nunca debería mandar otra cosa (los botones inline solo ofrecen los 3),
    pero esta función no confía ciegamente en el caller.
    """
    pick_normalizado = (pick or "").strip().lower()
    if pick_normalizado not in PICKS_VALIDOS:
        return {"ok": False, "error": f"pick inválido: {pick!r} (válidos: {PICKS_VALIDOS})"}

    fila = (
        db.query(PrediccionUsuario)
        .filter(
            PrediccionUsuario.match_id == match_id,
            PrediccionUsuario.telegram_user_id == telegram_user_id,
        )
        .first()
    )
    cambio_de_voto = fila is not None and fila.pick != pick_normalizado

    if fila is None:
        fila = PrediccionUsuario(
            match_id=match_id,
            telegram_user_id=telegram_user_id,
            pick=pick_normalizado,
            razon=razon,
            creado_en=_now_str(),
        )
        db.add(fila)
    else:
        fila.pick = pick_normalizado
        if razon is not None:
            fila.razon = razon

    db.commit()
    db.refresh(fila)
    return {"ok": True, "id": fila.id, "pick": fila.pick, "voto_actualizado": cambio_de_voto}


def guardar_razon(db: Session, match_id: str, telegram_user_id: str, razon: str) -> dict:
    """Guarda el texto libre de "¿por qué?" sobre un voto ya existente. Separado de
    `registrar_voto` porque el flujo de conversación (preguntar la razón DESPUÉS del botón) no
    se implementó en esta ronda (no existe todavía un patrón `ConversationHandler`/estado de
    conversación en `laplace_bot.py` para reusar sin agregar uno nuevo de cero) — queda lista
    para cuando se implemente ese próximo paso, documentado en el reporte de esta ronda."""
    fila = (
        db.query(PrediccionUsuario)
        .filter(
            PrediccionUsuario.match_id == match_id,
            PrediccionUsuario.telegram_user_id == telegram_user_id,
        )
        .first()
    )
    if fila is None:
        return {"ok": False, "error": "no hay un voto previo de este usuario para este partido"}
    fila.razon = razon
    db.commit()
    return {"ok": True}


def leer_agregado(db: Session, match_id: str) -> dict:
    """Agregado real de votos para un partido: `{"local": N, "empate": N, "visitante": N,
    "total": N}`. No se expone todavía en ningún endpoint ni se usa para nada más — ver
    docstring del módulo."""
    conteos = {pick: 0 for pick in PICKS_VALIDOS}
    filas = (
        db.query(PrediccionUsuario.pick)
        .filter(PrediccionUsuario.match_id == match_id)
        .all()
    )
    for (pick,) in filas:
        if pick in conteos:
            conteos[pick] += 1
    conteos["total"] = sum(conteos.values())
    return conteos
