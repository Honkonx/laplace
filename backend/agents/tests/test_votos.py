"""test_votos.py — conecta los votos reales de `/encuesta` (tabla `predicciones_usuario`) al
ciclo del agente (roadmap 2026-09-10 del README: "Conectar /encuesta al ciclo del agente").
Esto NO es "la IA aprende de los votos" (ver docstring de `laplace_agents/votos.py`) — solo
expone una comparación honesta de winrate entre el consenso mayoritario de usuarios y el
`pick_final` del motor, para partidos YA resueltos."""
from __future__ import annotations

from datetime import datetime

from backend.api.db import predicciones_usuario_repo
from backend.api.models.predicciones import AnalisisComparativo

from laplace_agents import votos


def _crear_comparativo_resuelto(
    db, partido_id, pick_final, pick_correcto, goles_local, goles_visitante, resultado_real="2-1",
):
    fila = AnalisisComparativo(
        partido_id=partido_id, fecha="2026-09-01", local="Local FC", visitante="Visitante FC",
        liga="Liga X", pick_final=pick_final, pick_correcto=pick_correcto,
        resultado_real=resultado_real, goles_local=goles_local, goles_visitante=goles_visitante,
        creado_en=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(fila)
    db.commit()
    return fila


def test_sin_ningun_voto_devuelve_muestra_vacia(db_session):
    resultado = votos.comparar_votos_vs_motor(db_session)

    assert resultado["total_partidos_con_voto_y_resultado"] == 0
    assert resultado["muestra_suficiente"] is False
    assert resultado["motor_winrate_pct"] is None
    assert resultado["detalle"] == []


def test_partido_con_voto_pero_sin_resolver_todavia_se_ignora(db_session):
    """Voto real registrado, pero `AnalisisComparativo` todavía sin `resultado_real` (partido
    no jugado aún) — no debe aparecer en la comparación."""
    fila = AnalisisComparativo(
        partido_id="1", fecha="2026-09-10", pick_final="Local",
        creado_en=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db_session.add(fila)
    db_session.commit()
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user1", "local")

    resultado = votos.comparar_votos_vs_motor(db_session)

    assert resultado["total_partidos_con_voto_y_resultado"] == 0


def test_motor_acierta_y_mayoria_de_usuarios_tambien(db_session):
    """Local gana 2-1. Motor picked "Local" (acertó, pick_correcto=1). 2 usuarios votaron
    'local', 1 votó 'empate' — mayoría real es 'local', también acertó."""
    _crear_comparativo_resuelto(db_session, "1", pick_final="Local", pick_correcto=1,
                                 goles_local=2, goles_visitante=1)
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user1", "local")
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user2", "local")
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user3", "empate")

    resultado = votos.comparar_votos_vs_motor(db_session)

    assert resultado["total_partidos_con_voto_y_resultado"] == 1
    assert resultado["motor_winrate_pct"] == 100.0
    assert resultado["usuarios_con_mayoria_clara"] == 1
    assert resultado["usuarios_winrate_pct"] == 100.0
    assert resultado["detalle"][0]["ganador_real"] == "local"
    assert resultado["detalle"][0]["usuarios_pick_mayoritario"] == "local"


def test_empate_de_votos_entre_dos_picks_no_cuenta_como_mayoria_clara(db_session):
    """2 votos 'local', 2 votos 'visitante' — empate real de votos, no hay mayoría clara, ese
    partido no entra al cálculo de winrate de usuarios (pero sí al total y al winrate del
    motor)."""
    _crear_comparativo_resuelto(db_session, "1", pick_final="Empate", pick_correcto=0,
                                 goles_local=2, goles_visitante=1)
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user1", "local")
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user2", "local")
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user3", "visitante")
    predicciones_usuario_repo.registrar_voto(db_session, "1", "user4", "visitante")

    resultado = votos.comparar_votos_vs_motor(db_session)

    assert resultado["total_partidos_con_voto_y_resultado"] == 1
    assert resultado["usuarios_con_mayoria_clara"] == 0
    assert resultado["usuarios_winrate_pct"] is None
    assert resultado["detalle"][0]["usuarios_pick_mayoritario"] is None
    assert resultado["detalle"][0]["usuarios_acerto"] is None
    assert resultado["detalle"][0]["motor_acerto"] is False  # motor picked Empate, ganó local


def test_muestra_suficiente_solo_a_partir_del_umbral(db_session):
    for i in range(votos.MUESTRA_MINIMA_PARA_WINRATE - 1):
        pid = str(i)
        _crear_comparativo_resuelto(db_session, pid, pick_final="Local", pick_correcto=1,
                                     goles_local=1, goles_visitante=0)
        predicciones_usuario_repo.registrar_voto(db_session, pid, "user1", "local")

    resultado = votos.comparar_votos_vs_motor(db_session)
    assert resultado["muestra_suficiente"] is False

    pid_extra = "extra"
    _crear_comparativo_resuelto(db_session, pid_extra, pick_final="Local", pick_correcto=1,
                                 goles_local=1, goles_visitante=0)
    predicciones_usuario_repo.registrar_voto(db_session, pid_extra, "user1", "local")

    resultado = votos.comparar_votos_vs_motor(db_session)
    assert resultado["muestra_suficiente"] is True
