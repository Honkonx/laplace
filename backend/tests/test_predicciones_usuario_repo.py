"""test_predicciones_usuario_repo.py — Tests reales (BD SQLite en memoria) para
`backend/api/db/predicciones_usuario_repo.py`: votos de usuarios reales sobre quién gana un
partido (primer paso de la visión "Laplace-Agents le pregunta a los usuarios, tipo encuestas").
"""
from __future__ import annotations

from backend.api.db import predicciones_usuario_repo
from backend.api.models.predicciones import PrediccionUsuario


def test_registrar_voto_crea_fila_real_en_bd(db_session):
    resultado = predicciones_usuario_repo.registrar_voto(
        db_session, match_id="m1", telegram_user_id="111", pick="local",
    )

    assert resultado == {"ok": True, "id": resultado["id"], "pick": "local", "voto_actualizado": False}
    # Post-condición real en la BD, no solo el dict de retorno.
    fila = db_session.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "m1").first()
    assert fila is not None
    assert fila.telegram_user_id == "111"
    assert fila.pick == "local"
    assert fila.razon is None
    assert fila.creado_en


def test_registrar_voto_normaliza_mayusculas_y_espacios(db_session):
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="  Local ")
    fila = db_session.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "m1").first()
    assert fila.pick == "local"


def test_registrar_voto_pick_invalido_no_toca_la_bd(db_session):
    resultado = predicciones_usuario_repo.registrar_voto(
        db_session, match_id="m1", telegram_user_id="111", pick="gana_seguro",
    )
    assert resultado["ok"] is False
    assert "pick inválido" in resultado["error"]
    assert db_session.query(PrediccionUsuario).count() == 0


def test_registrar_voto_dos_usuarios_distintos_generan_dos_filas(db_session):
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="local")
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="222", pick="visitante")

    assert db_session.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "m1").count() == 2


def test_registrar_voto_mismo_usuario_cambia_de_opinion_actualiza_en_vez_de_duplicar(db_session):
    primero = predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="local")
    segundo = predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="empate")

    assert primero["voto_actualizado"] is False
    assert segundo["voto_actualizado"] is True
    # Post-condición real: sigue habiendo UNA sola fila para ese usuario+partido, con el pick nuevo.
    filas = db_session.query(PrediccionUsuario).filter(
        PrediccionUsuario.match_id == "m1", PrediccionUsuario.telegram_user_id == "111",
    ).all()
    assert len(filas) == 1
    assert filas[0].pick == "empate"


def test_registrar_voto_mismo_pick_de_nuevo_no_marca_actualizado(db_session):
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="local")
    repetido = predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="local")
    assert repetido["voto_actualizado"] is False
    assert db_session.query(PrediccionUsuario).count() == 1


def test_guardar_razon_sobre_voto_existente(db_session):
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="111", pick="local")
    resultado = predicciones_usuario_repo.guardar_razon(db_session, match_id="m1", telegram_user_id="111", razon="Juega de local y llega mejor.")
    assert resultado["ok"] is True

    fila = db_session.query(PrediccionUsuario).filter(PrediccionUsuario.match_id == "m1").first()
    assert fila.razon == "Juega de local y llega mejor."


def test_guardar_razon_sin_voto_previo_devuelve_error(db_session):
    resultado = predicciones_usuario_repo.guardar_razon(db_session, match_id="m1", telegram_user_id="999", razon="algo")
    assert resultado["ok"] is False
    assert db_session.query(PrediccionUsuario).count() == 0


def test_leer_agregado_cuenta_los_tres_picks_reales(db_session):
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="1", pick="local")
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="2", pick="local")
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="3", pick="empate")
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m1", telegram_user_id="4", pick="visitante")
    # Voto de otro partido — no debe contaminar el agregado de "m1".
    predicciones_usuario_repo.registrar_voto(db_session, match_id="m2", telegram_user_id="1", pick="visitante")

    agregado = predicciones_usuario_repo.leer_agregado(db_session, "m1")
    assert agregado == {"local": 2, "empate": 1, "visitante": 1, "total": 4}


def test_leer_agregado_partido_sin_votos_devuelve_ceros(db_session):
    agregado = predicciones_usuario_repo.leer_agregado(db_session, "sin_votos")
    assert agregado == {"local": 0, "empate": 0, "visitante": 0, "total": 0}
