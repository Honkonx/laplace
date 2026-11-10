"""test_memoria.py — memoria SQL propia del agente (`laplace_agents/memoria.py`, roadmap
2026-09-10 del README: "Memoria SQL propia"). Confirma que un evento se persiste real en
`LaplaceAgentMemoria` (BD en memoria del test, mismo patrón que `test_core.py`) y que se puede
leer de vuelta con el JSON de `resumen` ya deserializado."""
from __future__ import annotations

from backend.api.models.laplace_agents import LaplaceAgentMemoria

from laplace_agents import memoria


def test_guardar_evento_persiste_una_fila_real(db_session):
    resultado = memoria.guardar_evento(
        db_session, tipo_evento="ciclo_diario",
        resumen={"distribucion_picks": {"Local": 3, "Empate": 1}, "total_analizados_con_pick": 4},
        fecha="2026-09-10",
    )

    assert resultado["id"] is not None
    fila = db_session.query(LaplaceAgentMemoria).filter(LaplaceAgentMemoria.id == resultado["id"]).first()
    assert fila is not None
    assert fila.tipo_evento == "ciclo_diario"
    assert fila.fecha == "2026-09-10"
    assert fila.creado_en  # timestamp real, no vacío


def test_guardar_evento_sin_fecha_usa_hoy_por_default(db_session):
    resultado = memoria.guardar_evento(db_session, tipo_evento="ciclo_diario", resumen={"x": 1})
    assert resultado["fecha"]  # se completó solo, no quedó vacío


def test_leer_ultimo_evento_devuelve_none_si_no_hay_ninguno(db_session):
    assert memoria.leer_ultimo_evento(db_session, tipo_evento="ciclo_diario") is None


def test_leer_ultimo_evento_devuelve_el_mas_reciente_con_resumen_deserializado(db_session):
    memoria.guardar_evento(db_session, tipo_evento="ciclo_diario", resumen={"total": 1}, fecha="2026-09-09")
    memoria.guardar_evento(db_session, tipo_evento="ciclo_diario", resumen={"total": 2}, fecha="2026-09-10")
    memoria.guardar_evento(db_session, tipo_evento="deriva_detectada", resumen={"otra_cosa": True}, fecha="2026-09-10")

    ultimo = memoria.leer_ultimo_evento(db_session, tipo_evento="ciclo_diario")

    assert ultimo is not None
    assert ultimo["fecha"] == "2026-09-10"
    assert ultimo["resumen"] == {"total": 2}  # el segundo, no el primero ni el de otro tipo_evento
