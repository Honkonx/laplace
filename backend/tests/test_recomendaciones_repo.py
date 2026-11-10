"""test_recomendaciones_repo.py — recomendaciones_dia (sobrantes del Top Picks del canal)."""
from __future__ import annotations

from datetime import datetime

from backend.api.db import recomendaciones_repo
from backend.api.models.predicciones import AnalisisComparativo


def test_guardar_y_leer_recomendaciones(db_session):
    guardados = recomendaciones_repo.guardar_recomendaciones(
        db_session, "20260601",
        [{"fixture_id": "f1", "local": "River", "visitante": "Boca", "liga": "Liga Profesional", "hora_chile": "20:00"}],
    )
    assert guardados == 1

    filas = recomendaciones_repo.leer_recomendaciones(db_session, "20260601")
    assert len(filas) == 1
    assert filas[0]["local"] == "River"
    assert filas[0]["pick_final"] is None  # sin análisis todavía


def test_guardar_recomendaciones_reemplaza_las_del_mismo_dia(db_session):
    recomendaciones_repo.guardar_recomendaciones(
        db_session, "20260601", [{"fixture_id": "f1", "local": "A", "visitante": "B", "liga": "L"}],
    )
    recomendaciones_repo.guardar_recomendaciones(
        db_session, "20260601", [{"fixture_id": "f2", "local": "C", "visitante": "D", "liga": "L"}],
    )
    filas = recomendaciones_repo.leer_recomendaciones(db_session, "20260601")
    assert len(filas) == 1
    assert filas[0]["fixture_id"] == "f2"


def test_guardar_recomendaciones_descarta_incompletas(db_session):
    guardados = recomendaciones_repo.guardar_recomendaciones(
        db_session, "20260601", [{"fixture_id": "", "local": "A", "visitante": "B", "liga": "L"}],
    )
    assert guardados == 0


def test_leer_recomendaciones_enriquece_con_analisis_comparativo(db_session):
    recomendaciones_repo.guardar_recomendaciones(
        db_session, "20260601", [{"fixture_id": "f1", "local": "River", "visitante": "Boca", "liga": "L"}],
    )
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-01", local="River", visitante="Boca", liga="L",
        pick_final="Local", confianza="ALTA", score_final=80, fuentes_disp=3,
        creado_en=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    db_session.commit()

    filas = recomendaciones_repo.leer_recomendaciones(db_session, "20260601")
    assert filas[0]["pick_final"] == "Local"
    assert filas[0]["score"] == 80
    assert filas[0]["consenso"] == "3/3"
