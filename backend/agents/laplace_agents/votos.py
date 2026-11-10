"""laplace_agents/votos.py — compara el voto agregado real de usuarios (comando `/encuesta` del
bot, tabla `predicciones_usuario` vía `backend.api.db.predicciones_usuario_repo`) contra el
resultado real y contra el `pick_final` del motor, para partidos ya resueltos. Primer uso real
de `predicciones_usuario_repo.leer_agregado` fuera de su propio test — ver el docstring de ese
módulo: "Nada en el repo todavía lee `leer_agregado` para otra cosa que no sea el propio test".

Esto NO es "la IA aprende de los votos de los usuarios" — sería sobre-prometer con el volumen
real de hoy (ver `INVESTIGACION_ARQUITECTURA_AGENTES_2026-09.md`: ningún
framework grande de agentes tiene aprendizaje automático real más allá de memoria persistente +
recuperación, y acá el volumen de votos reales es todavía menor que el de partidos verificados).
Es solo EXPONER una comparación honesta: de los partidos resueltos donde hubo al menos un voto
real, ¿qué tan seguido acertó el consenso mayoritario de usuarios vs. el `pick_final` del motor?
Ninguno de los dos valores alimenta ni ajusta al otro."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.db import predicciones_usuario_repo
from backend.api.models.predicciones import AnalisisComparativo, PrediccionUsuario

# Igual que `deriva.MUESTRA_MINIMA_PARA_COMPARAR`/`consistencia.MUESTRA_MINIMA_PARA_ALERTA` —
# un winrate calculado sobre pocos partidos no es una señal real, es ruido. Se expone igual el
# número crudo (`total_partidos_con_voto_y_resultado`), pero `muestra_suficiente` deja explícito
# cuándo el winrate ya significa algo.
MUESTRA_MINIMA_PARA_WINRATE = 5


def _ganador_real(goles_local: int | None, goles_visitante: int | None) -> str | None:
    """Mismo criterio de negocio que `backend/api/services/resultados.py::_guardar_resultado`
    (no se reimporta esa función privada ni se reimplementa su lógica completa — ese archivo
    está fuera del alcance de archivos tocables de esta ronda; acá solo se replica la regla
    pública y simple "más goles gana, empate si son iguales" sobre las columnas ya persistidas
    `goles_local`/`goles_visitante` de `AnalisisComparativo`, que esa misma función deja
    escritas junto con `resultado_real`)."""
    if goles_local is None or goles_visitante is None:
        return None
    if goles_local > goles_visitante:
        return "local"
    if goles_visitante > goles_local:
        return "visitante"
    return "empate"


def _pick_mayoritario(agregado: dict) -> str | None:
    """Pick con más votos entre local/empate/visitante. `None` si no hay ningún voto, o si hay
    empate de votos entre dos o más picks — un empate de votos no es una mayoría real, no se
    desempata arbitrariamente."""
    conteos = {
        pick: conteo for pick, conteo in agregado.items()
        if pick in predicciones_usuario_repo.PICKS_VALIDOS and conteo > 0
    }
    if not conteos:
        return None
    maximo = max(conteos.values())
    ganadores = [pick for pick, conteo in conteos.items() if conteo == maximo]
    return ganadores[0] if len(ganadores) == 1 else None


def comparar_votos_vs_motor(db: Session) -> dict:
    """Recorre los partidos que tienen al menos un voto real registrado y ya tienen
    `resultado_real` (resueltos por `services/resultados.py`), y compara el acierto del
    consenso mayoritario de usuarios contra el acierto ya calculado del motor
    (`AnalisisComparativo.pick_correcto`, que `resultados.py` ya deja calculado — no se
    recalcula acá). Sin filtro de fecha: el volumen real de votos es bajo (ver
    el registro de decisiones del proyecto), acotar por fecha dejaría la muestra todavía más chica sin
    beneficio real."""
    match_ids_con_voto = [
        row[0] for row in db.query(PrediccionUsuario.match_id).distinct().all()
    ]

    detalle: list[dict] = []
    for match_id in match_ids_con_voto:
        fila = (
            db.query(AnalisisComparativo)
            .filter(
                AnalisisComparativo.partido_id == match_id,
                AnalisisComparativo.resultado_real.isnot(None),
            )
            .order_by(AnalisisComparativo.id.desc())
            .first()
        )
        if fila is None:
            continue
        ganador = _ganador_real(fila.goles_local, fila.goles_visitante)
        if ganador is None:
            continue

        agregado = predicciones_usuario_repo.leer_agregado(db, match_id)
        pick_mayoritario = _pick_mayoritario(agregado)
        detalle.append({
            "match_id": match_id,
            "ganador_real": ganador,
            "motor_pick_final": fila.pick_final,
            "motor_acerto": fila.pick_correcto == 1,
            "usuarios_total_votos": agregado["total"],
            "usuarios_pick_mayoritario": pick_mayoritario,
            "usuarios_acerto": (pick_mayoritario == ganador) if pick_mayoritario else None,
        })

    total = len(detalle)
    motor_aciertos = sum(1 for d in detalle if d["motor_acerto"])
    con_mayoria_clara = [d for d in detalle if d["usuarios_acerto"] is not None]
    usuarios_aciertos = sum(1 for d in con_mayoria_clara if d["usuarios_acerto"])

    def _winrate(aciertos: int, n: int) -> float | None:
        return round(aciertos / n * 100, 1) if n else None

    return {
        "total_partidos_con_voto_y_resultado": total,
        "muestra_suficiente": total >= MUESTRA_MINIMA_PARA_WINRATE,
        "motor_winrate_pct": _winrate(motor_aciertos, total),
        "usuarios_con_mayoria_clara": len(con_mayoria_clara),
        "usuarios_winrate_pct": _winrate(usuarios_aciertos, len(con_mayoria_clara)),
        "detalle": detalle,
    }
