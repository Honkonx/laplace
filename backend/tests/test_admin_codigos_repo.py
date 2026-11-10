"""test_admin_codigos_repo.py — funciones admin/CLI de db_query.py que ningún workflow n8n
llamaba (generación/listado/asignación de códigos, gestión manual de usuarios, verificación de
admin, stats por módulo, predicción externa). Portadas para completar el backend al 100%."""
from __future__ import annotations

import pytest

from backend.api.core.config import settings
from backend.api.db import admin_repo, auditoria_repo, codigos_repo
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.models.usuarios import CodigoAcceso, Usuario


def test_verificar_admin_reconoce_id_en_settings(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "111,222")
    assert admin_repo.verificar_admin("111")["es_admin"] is True
    assert admin_repo.verificar_admin("999")["es_admin"] is False


def test_gestionar_usuario_agregar_activar_cambiar_plan_eliminar(db_session):
    r1 = admin_repo.gestionar_usuario(db_session, "agregar", "u1", "pro")
    assert r1["accion"] == "agregado"
    assert db_session.query(Usuario).filter(Usuario.device_id == "u1").first().plan == "pro"

    r2 = admin_repo.gestionar_usuario(db_session, "desactivar", "u1")
    assert r2["accion"] == "desactivado"
    assert db_session.query(Usuario).filter(Usuario.device_id == "u1").first().activo == 0

    r3 = admin_repo.gestionar_usuario(db_session, "cambiar_plan", "u1", "max")
    assert r3["accion"] == "plan_actualizado"
    assert db_session.query(Usuario).filter(Usuario.device_id == "u1").first().plan == "max"

    r4 = admin_repo.gestionar_usuario(db_session, "eliminar", "u1")
    assert r4["accion"] == "eliminado"
    assert db_session.query(Usuario).filter(Usuario.device_id == "u1").first() is None


def test_gestionar_usuario_plan_invalido_no_rompe(db_session):
    resultado = admin_repo.gestionar_usuario(db_session, "agregar", "u2", "planX")
    assert "error" in resultado


def test_guardar_prediccion_externa_actualiza_comparativo(db_session):
    db_session.add(AnalisisComparativo(partido_id="p1", fecha="2026-01-01", creado_en="2026-01-01 00:00:00"))
    db_session.commit()

    resultado = admin_repo.guardar_prediccion_externa(db_session, "p1", "Local", 70.0, fuente="forebet")
    assert resultado["guardado"] is True

    fila = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "p1").first()
    assert fila.pick_externo == "Local"
    assert fila.fuente_externo == "forebet"


def test_leer_stats_modulos_calcula_winrate_por_modulo(db_session):
    db_session.add(AnalisisComparativo(
        partido_id="p1", fecha="2026-01-01", creado_en="2026-01-01 00:00:00",
        resultado_real="1-0", pick_correcto=1, pick_python_correcto=1, pick_form_correcto=0,
        consenso_nivel="FUERTE", over25_correcto=1,
    ))
    db_session.add(AnalisisComparativo(
        partido_id="p2", fecha="2026-01-01", creado_en="2026-01-01 00:00:00",
        resultado_real="0-0", pick_correcto=0, pick_python_correcto=0,
        consenso_nivel="DEBIL",
    ))
    db_session.commit()

    resultado = admin_repo.leer_stats_modulos(db_session, fecha="2026-01-01", fecha_fin="2026-01-01")
    assert resultado["periodo"]["total_partidos"] == 2
    assert resultado["final"]["winrate"] == 50.0
    assert resultado["poisson"]["total"] == 2
    assert resultado["poisson"]["ok"] == 1
    assert resultado["consenso"]["fuerte"]["total"] == 1
    assert resultado["mercados"]["over25"]["total"] == 1


def test_generar_codigos_lote_cantidad_y_unicidad(db_session):
    resultado = codigos_repo.generar_codigos_lote(db_session, "pro", 30, 5)
    assert resultado["generados"] == 5
    assert len(set(resultado["codigos"])) == 5
    assert all(c.startswith("KS-PRO-") for c in resultado["codigos"])
    assert db_session.query(CodigoAcceso).count() == 5


def test_generar_codigos_lote_valida_limites(db_session):
    assert "error" in codigos_repo.generar_codigos_lote(db_session, "free", 30, 5)
    assert "error" in codigos_repo.generar_codigos_lote(db_session, "pro", 30, 0)
    assert "error" in codigos_repo.generar_codigos_lote(db_session, "pro", 0, 5)


def test_listar_codigos_filtra_por_estado(db_session):
    codigos_repo.generar_codigos_lote(db_session, "pro", 30, 3)
    resultado = codigos_repo.listar_codigos(db_session, "disponibles")
    assert resultado["total"] == 3

    codigo = resultado["codigos"][0]["codigo"]
    codigos_repo.activar_codigo(db_session, codigo, "device_x")

    assert codigos_repo.listar_codigos(db_session, "disponibles")["total"] == 2
    assert codigos_repo.listar_codigos(db_session, "usados")["total"] == 1
    assert codigos_repo.listar_codigos(db_session, "todos")["total"] == 3


def test_asignar_codigo_reserva_y_libera(db_session):
    resultado = codigos_repo.generar_codigos_lote(db_session, "pro", 30, 1)
    codigo = resultado["codigos"][0]

    asignado = codigos_repo.asignar_codigo(db_session, codigo, "device_reservado")
    assert asignado["asignado"] is True
    assert asignado["device_id"] == "device_reservado"

    # otro device_id no puede activarlo
    intento_ajeno = codigos_repo.activar_codigo(db_session, codigo, "device_ajeno")
    assert intento_ajeno["activado"] is False
    assert intento_ajeno["error"] == "codigo_no_asignado"

    liberado = codigos_repo.asignar_codigo(db_session, codigo, "")
    assert liberado["device_id"] is None

    ok = codigos_repo.activar_codigo(db_session, codigo, "device_cualquiera")
    assert ok["activado"] is True


def test_asignar_codigo_ya_usado_no_se_puede_reasignar(db_session):
    resultado = codigos_repo.generar_codigos_lote(db_session, "pro", 30, 1)
    codigo = resultado["codigos"][0]
    codigos_repo.activar_codigo(db_session, codigo, "device_y")

    reasignar = codigos_repo.asignar_codigo(db_session, codigo, "device_z")
    assert reasignar["asignado"] is False


def test_activar_codigo_deja_rastro_en_historial_plan(db_session):
    """Hallazgo real de la auditoría de permisos/BD 2026-09-08: `activar_codigo` sobrescribía
    `Usuario.plan` sin dejar rastro de que el cambio vino de un código canjeado (vs. una
    asignación manual de admin, ver test siguiente) — ver `models/auditoria.py`."""
    resultado = codigos_repo.generar_codigos_lote(db_session, "pro", 30, 1)
    codigo = resultado["codigos"][0]

    codigos_repo.activar_codigo(db_session, codigo, "device_historial")

    historial = auditoria_repo.leer_historial_plan(db_session, "device_historial")
    assert len(historial) == 1
    assert historial[0]["plan_anterior"] is None
    assert historial[0]["plan_nuevo"] == "pro"
    assert historial[0]["medio"] == "codigo"
    assert historial[0]["detalle"] == codigo


def test_gestionar_usuario_cambiar_plan_deja_rastro_con_actor_admin(db_session):
    admin_repo.gestionar_usuario(db_session, "agregar", "u_admin_hist", "pro", actor_admin_id="admin_007")
    admin_repo.gestionar_usuario(db_session, "cambiar_plan", "u_admin_hist", "max", actor_admin_id="admin_007")

    historial = auditoria_repo.leer_historial_plan(db_session, "u_admin_hist")
    assert len(historial) == 2
    # más reciente primero
    assert historial[0]["plan_anterior"] == "pro"
    assert historial[0]["plan_nuevo"] == "max"
    assert historial[0]["medio"] == "admin"
    assert historial[0]["detalle"] == "admin_007"
    assert historial[1]["plan_anterior"] is None
    assert historial[1]["plan_nuevo"] == "pro"


def test_gestionar_usuario_sin_actor_admin_id_no_rompe(db_session):
    """`actor_admin_id` es opcional — llamadas que no lo pasan (código legado o pruebas
    anteriores a esta ronda) deben seguir funcionando, con `detalle=None`."""
    resultado = admin_repo.gestionar_usuario(db_session, "agregar", "u_sin_actor", "pro")
    assert resultado["accion"] == "agregado"
    historial = auditoria_repo.leer_historial_plan(db_session, "u_sin_actor")
    assert historial[0]["detalle"] is None


def test_registrar_cambio_plan_medio_invalido_lanza_valueerror(db_session):
    with pytest.raises(ValueError):
        auditoria_repo.registrar_cambio_plan(db_session, "dev1", None, "pro", medio="webhook_random")


def test_registrar_accion_admin_deja_rastro_real(db_session):
    """`AccionAdminAuditoria` — agregada 2026-09-09 para auditar acciones admin sin device_id
    asociado (ej. `/generarcodigos`). Ver `models/auditoria.py` para por qué no reusa
    `historial_plan`."""
    resultado = auditoria_repo.registrar_accion_admin(
        db_session, actor_admin_id="admin_1", accion="generar_codigos", detalle="5 codigos pro x30d",
    )
    assert resultado == {"registrado": True, "actor_admin_id": "admin_1", "accion": "generar_codigos"}

    listado = auditoria_repo.listar_acciones_admin(db_session)
    assert listado["total"] == 1
    assert listado["acciones"][0]["actor_admin_id"] == "admin_1"
    assert listado["acciones"][0]["accion"] == "generar_codigos"
    assert listado["acciones"][0]["detalle"] == "5 codigos pro x30d"


def test_listar_acciones_admin_orden_mas_reciente_primero(db_session):
    auditoria_repo.registrar_accion_admin(db_session, "admin_1", "generar_codigos", "1ra")
    auditoria_repo.registrar_accion_admin(db_session, "admin_1", "generar_codigos", "2da")

    listado = auditoria_repo.listar_acciones_admin(db_session)
    assert [a["detalle"] for a in listado["acciones"]] == ["2da", "1ra"]
