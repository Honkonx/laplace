"""test_routers_resultados_partidos.py — `routers/resultados.py` (POST /api/v1/resultados/verificar, solo admin)
y `routers/partidos.py` (GET /api/v1/partidos y /partidos/pronosticables) con TestClient, BD en memoria y las
fuentes externas sustituidas (sin red)."""
from __future__ import annotations

from datetime import datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from backend.api.core.auth_deps import requerir_admin
from backend.api.core.config import settings
from backend.api.core.rate_limit import limiter
from backend.api.db.session import Base, get_db
from backend.api.main import app
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services import gateway, modelo_historico
from backend.api.services import resultados as resultados_svc

URL_VERIFICAR = "/api/v1/resultados/verificar"


@pytest.fixture()
def fabrica():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def cliente(fabrica):
    def _db():
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def cliente_admin(cliente):
    app.dependency_overrides[requerir_admin] = lambda: {"rol": "admin", "device_id": "admin-test"}
    return cliente


# ------------------------------------------------------------------ /resultados/verificar
def test_verificar_exige_admin(cliente):
    # Sin cabecera Authorization FastAPI responde 422 (Header(...) requerido) antes del 401 propio; mismo criterio que test_scheduler.py.
    assert cliente.post(URL_VERIFICAR, json={}).status_code in (401, 422)
    assert cliente.post(URL_VERIFICAR, json={}, headers={"Authorization": "Bearer basura"}).status_code == 401
    assert cliente.post(URL_VERIFICAR, json={}, headers={"Authorization": "Token x"}).status_code == 401
    no_admin = jwt.encode({"rol": "usuario", "sub": "u"}, settings.WEB_JWT_SECRET, algorithm="HS256")
    assert cliente.post(URL_VERIFICAR, json={}, headers={"Authorization": f"Bearer {no_admin}"}).status_code == 403


def test_verificar_sin_pendientes_responde_sin_pendientes_y_no_consulta_apis(cliente_admin, monkeypatch):
    async def no_debe_llamarse(*a, **kw):
        raise AssertionError("no hay nada que verificar: no debe gastar cuota")

    monkeypatch.setattr(resultados_svc, "actualizar_resultados", no_debe_llamarse)
    r = cliente_admin.post(URL_VERIFICAR, json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "data": {"total": 0, "actualizados": 0, "mensaje": "Sin pendientes"}}


def test_verificar_usa_los_pendientes_del_dia_si_no_vienen_ids(cliente_admin, fabrica, monkeypatch):
    hoy = datetime.now().strftime("%Y-%m-%d")
    with fabrica() as db:
        db.add(AnalisisComparativo(partido_id="pend1", fecha=hoy, local="A", visitante="B", creado_en="2026-11-01 10:00:00"))
        db.add(AnalisisComparativo(partido_id="hecho", fecha=hoy, resultado_real="1-0", creado_en="2026-11-01 10:00:00"))
        db.commit()
    recibido = {}

    async def falso(db, client, fixture_ids, fecha):
        recibido.update(ids=fixture_ids, fecha=fecha)
        return {"fecha": fecha, "resumen": {"total": len(fixture_ids)}, "detalle": []}

    monkeypatch.setattr(resultados_svc, "actualizar_resultados", falso)
    r = cliente_admin.post(URL_VERIFICAR, json={})
    assert r.status_code == 200 and r.json()["data"]["resumen"]["total"] == 1
    assert recibido == {"ids": ["pend1"], "fecha": hoy}


def test_verificar_con_ids_y_fecha_explicitos(cliente_admin, monkeypatch):
    recibido = {}

    async def falso(db, client, fixture_ids, fecha):
        recibido.update(ids=fixture_ids, fecha=fecha)
        return {"fecha": fecha, "resumen": {}, "detalle": []}

    monkeypatch.setattr(resultados_svc, "actualizar_resultados", falso)
    r = cliente_admin.post(URL_VERIFICAR, json={"fixture_ids": ["7", "8"], "fecha": "2026-05-05"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert recibido == {"ids": ["7", "8"], "fecha": "2026-05-05"}


def test_verificar_flujo_real_sin_claves_deja_sin_datos(cliente_admin, fabrica, monkeypatch):
    """Sin claves de BSD ni api-football el servicio real no sale a la red y reporta `sin_datos`."""
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "")
    r = cliente_admin.post(URL_VERIFICAR, json={"fixture_ids": ["x1"], "fecha": "2026-05-05"})
    assert r.status_code == 200
    assert r.json()["data"]["resumen"]["sin_datos"] == 1


def test_verificar_valida_el_cuerpo(cliente_admin):
    assert cliente_admin.post(URL_VERIFICAR, json={"fixture_ids": "no-es-lista"}).status_code == 422


# ------------------------------------------------------------------ GET /partidos
def test_partidos_fecha_invalida_es_422(cliente):
    for malo in ("hoy", "2026-13-40", "20261340", ""):
        assert cliente.get("/api/v1/partidos", params={"fecha": malo}).status_code == 422


def test_partidos_cascada_guarda_en_cache_si_no_viene_de_la_bd(cliente, monkeypatch):
    stages = [{"Events": [{"Eid": "1"}, {"Eid": "2"}]}, {"Events": [{"Eid": "3"}]}]
    guardado = {}

    async def cascada(db, client, fecha):
        guardado["fecha_consulta"] = fecha
        return stages, "bsd"

    monkeypatch.setattr(gateway, "obtener_fixtures_cascada", cascada)
    monkeypatch.setattr(gateway, "guardar_stages_en_cache",
                        lambda db, fecha, st, fuente: guardado.update(fecha=fecha, fuente=fuente, n=len(st)))
    r = cliente.get("/api/v1/partidos", params={"fecha": "2026-05-05"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["ok"], cuerpo["fuente"], cuerpo["total"]) == (True, "bsd", 3)
    assert guardado == {"fecha_consulta": "20260505", "fecha": "20260505", "fuente": "bsd", "n": 2}


@pytest.mark.parametrize("fuente,stages", [("bd", [{"Events": [{"Eid": "1"}]}]), ("api-football", [])])
def test_partidos_no_guarda_cache_si_vino_de_bd_o_vacio(cliente, monkeypatch, fuente, stages):
    async def cascada(db, client, fecha):
        return stages, fuente

    def no_guardar(*a, **kw):
        raise AssertionError("no debía guardar en caché")

    monkeypatch.setattr(gateway, "obtener_fixtures_cascada", cascada)
    monkeypatch.setattr(gateway, "guardar_stages_en_cache", no_guardar)
    r = cliente.get("/api/v1/partidos", params={"fecha": "20260505"})
    assert r.status_code == 200 and r.json()["fuente"] == fuente


# ------------------------------------------------------------------ GET /partidos/pronosticables
def test_pronosticables_fecha_invalida_es_422(cliente):
    assert cliente.get("/api/v1/partidos/pronosticables", params={"fecha": "31-12-2026"}).status_code == 422


def test_pronosticables_lista_solo_los_que_el_modelo_sabe_pronosticar(cliente, fabrica, monkeypatch):
    with fabrica() as db:
        db.add_all([
            PartidoDia(fecha="2026-05-05", match_id="a", liga_nombre="LaLiga", local="Real Madrid", visitante="Getafe",
                       hora_chile="16:00", status="scheduled"),
            PartidoDia(fecha="2026-05-05", match_id="b", liga_nombre="LaLiga", local="Nuevo FC", visitante="Getafe",
                       hora_chile="14:00", status="scheduled"),
            PartidoDia(fecha="2026-05-05", match_id="c", liga_nombre="Liga Rara", local="X", visitante="Y",
                       hora_chile="12:00", status="scheduled"),
            PartidoDia(fecha="2026-05-05", match_id="d", liga_nombre="LaLiga", local="Real Madrid", visitante="Getafe",
                       status="finished"),
        ])
        db.commit()

    def validar(datos):
        if datos["liga"] == "Liga Rara":
            return False, "liga_sin_modelo"
        return True, "equipo_sin_historial" if datos["local"] == "Nuevo FC" else None

    monkeypatch.setattr(modelo_historico, "validar_historico", validar)
    r = cliente.get("/api/v1/partidos/pronosticables", params={"fecha": "20260505"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["fecha"], cuerpo["total_programados"], cuerpo["total_pronosticables"]) == ("2026-05-05", 3, 2)
    # primero los de cobertura completa, luego los de equipo sin historial
    assert [(p["match_id"], p["cobertura"]) for p in cuerpo["partidos"]] == [("a", "completa"), ("b", "equipo_sin_historial")]


def test_pronosticables_dia_sin_partidos(cliente):
    r = cliente.get("/api/v1/partidos/pronosticables", params={"fecha": "2026-01-01"})
    assert r.json() == {"ok": True, "fecha": "2026-01-01", "total_programados": 0, "total_pronosticables": 0, "partidos": []}
