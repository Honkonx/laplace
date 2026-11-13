"""El modelo registra solo, sin gastar cuota, su pronóstico para los partidos próximos que el bot ya conoce (evidencia en vivo que se acumula sola)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base
from backend.api.ml.laplace import pronostico, servicio
from backend.api.models.ml_modelo import MlPrediccion
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import laboratorio_pronosticos as lab
from backend.api.services import modelo_historico

AHORA = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)   # 08:00 en Chile (desfase fijo -4)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    lab.asegurar_experimentos_base(s)
    s.commit()
    monkeypatch.setattr(lab, "_now", lambda: AHORA.isoformat())   # el corte de datos lo sella el laboratorio con su propio reloj: se alinea con el «ahora» de la prueba
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: {"ok": True, "degradado": False, "modelo": {"id": 3, "version": "g2"}, **pronostico.pronosticar(1.6, 1.1)})
    monkeypatch.setattr(modelo_historico, "validar_historico", lambda d: (True, ""))
    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": True, "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "lambda_local": 1.5, "lambda_visit": 1.0, "metodo": "dixon_coles", "pick": "Local"})
    yield s
    s.close()


def _partido(db, match_id, fecha, hora, status="scheduled", kick=None, local="A", visitante="B"):
    db.add(PartidoDia(fecha=fecha, match_id=match_id, liga_nombre="Liga X", local=local, visitante=visitante, hora_chile=hora, status=status, kick_off_utc=kick))
    db.commit()


def _variantes(db, pid):
    return sorted(f.variante for f in db.query(PronosticoExperimental).filter_by(partido_id=pid))


def test_registra_el_modelo_y_dixon_coles_sobre_el_mismo_partido_futuro(db):
    _partido(db, "m1", "2026-11-10", "15:00")   # 19:00 UTC: 7 h después de AHORA
    r = lab.registrar_proximos(db, AHORA)
    assert r["registrados"] == 1 and _variantes(db, "m1") == ["dixon_coles_historico", "laplace_modelo"]
    assert db.query(MlPrediccion).filter_by(partido_id="m1").count() == 1


def test_es_idempotente_y_no_repite_un_partido(db):
    _partido(db, "m1", "2026-11-10", "15:00")
    lab.registrar_proximos(db, AHORA)
    lab.registrar_proximos(db, AHORA)
    assert len(_variantes(db, "m1")) == 2 and db.query(MlPrediccion).filter_by(partido_id="m1").count() == 1


@pytest.mark.parametrize("hora,motivo", [("07:00", "pasado"), ("08:20", "en menos de 30 min")])
def test_nunca_registra_un_partido_que_ya_empezo_o_empieza_ya(db, hora, motivo):
    _partido(db, "m1", "2026-11-10", hora)
    r = lab.registrar_proximos(db, AHORA)
    assert r["registrados"] == 0 and _variantes(db, "m1") == [], motivo


def test_ignora_lo_que_no_esta_programado_o_esta_fuera_del_horizonte(db):
    _partido(db, "fin", "2026-11-10", "20:00", status="finished")
    _partido(db, "lejos", "2026-11-12", "20:00")      # a más de 48 h
    _partido(db, "ayer", "2026-11-09", "20:00")       # fecha ya pasada
    assert lab.registrar_proximos(db, AHORA)["registrados"] == 0


def test_prefiere_kick_off_utc_cuando_viene(db):
    _partido(db, "m1", "2026-11-10", "01:00", kick="2026-11-10T22:00:00")   # la hora_chile diría «pasado», el UTC dice «futuro»
    assert lab.registrar_proximos(db, AHORA)["registrados"] == 1


def test_hora_ilegible_se_cuenta_y_no_rompe(db):
    _partido(db, "m1", "2026-11-10", "xx:yy")
    r = lab.registrar_proximos(db, AHORA)
    assert r["sin_hora"] == 1 and r["registrados"] == 0


def test_sin_cobertura_del_modelo_no_registra_la_variante(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: {"ok": False})
    _partido(db, "m1", "2026-11-10", "15:00")
    r = lab.registrar_proximos(db, AHORA)
    assert r["sin_cobertura"] == 1 and "laplace_modelo" not in _variantes(db, "m1")


def test_un_partido_que_falla_no_detiene_a_los_demas(db, monkeypatch):
    llamadas = []

    def analizar(d):
        llamadas.append(d["local"])
        if d["local"] == "Roto":
            raise RuntimeError("x")
        return {"ok": True, "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "lambda_local": 1.5, "lambda_visit": 1.0, "metodo": "dixon_coles", "pick": "Local"}

    monkeypatch.setattr(modelo_historico, "analizar", analizar)
    _partido(db, "roto", "2026-11-10", "15:00", local="Roto")
    _partido(db, "ok", "2026-11-10", "16:00")
    r = lab.registrar_proximos(db, AHORA)
    assert r["registrados"] == 1 and "laplace_modelo" in _variantes(db, "ok") and _variantes(db, "roto") == []


def test_el_trabajo_diario_registra_los_proximos_y_lo_deja_en_el_detalle(monkeypatch):
    import asyncio

    from backend.api.db import scheduler_repo
    from backend.api.ml.laplace import jobs
    from backend.api.routers.scheduler import JOB_MODELO_LAPLACE

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine)
    monkeypatch.setattr(lab, "registrar_proximos", lambda db: {"registrados": 5, "candidatos": 9, "sin_cobertura": 4, "ya_empezados": 0, "sin_hora": 0})
    asyncio.run(jobs.evaluar_modelo_diario(fabrica))
    with fabrica() as db:
        assert "proximos: 5 nuevos de 9" in scheduler_repo.ultimo_run(db, JOB_MODELO_LAPLACE).detalle


def test_la_hora_chile_guardada_se_lee_con_el_mismo_desfase_con_que_se_calculo():
    """El gateway guarda UTC-4 fijo; leerla con -4 devuelve el instante real (15:00 guardado = 19:00 UTC)."""
    from backend.api.services.laboratorio_modelo_laplace import _inicio_estimado

    p = PartidoDia(fecha="2026-11-10", match_id="x", hora_chile="15:00", status="scheduled")
    assert _inicio_estimado(p) == datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)


def test_si_el_corte_no_fuera_anterior_al_inicio_el_laboratorio_lo_rechaza_y_se_omite(db, monkeypatch):
    """Red de seguridad: aunque la estimación de la hora fallara, `registrar_pronostico` no admite un corte posterior al inicio."""
    _partido(db, "m1", "2026-11-10", "15:00")
    monkeypatch.setattr(lab, "_now", lambda: "2099-01-01T00:00:00+00:00")
    r = lab.registrar_proximos(db, AHORA)
    assert r["registrados"] == 0 and _variantes(db, "m1") == []
