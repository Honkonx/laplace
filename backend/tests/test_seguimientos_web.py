"""MS-13 y MS-11: «Mis seguimientos» de la web y la PWA y los topes por plan, sobre una base de las MIGRACIONES REALES y el servidor real (JWT incluido).
La web usa la misma lógica, el mismo almacén y los mismos mensajes que el chat de Telegram; solo cambia la identidad (el `sub` de la sesión)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.api.core.auth_deps import ALGORITMO_JWT
from backend.api.core.config import settings
from backend.api.db import bot_memoria_repo
from backend.api.db.session import get_db
from backend.api.models.usuarios import Usuario
from backend.api.services import agent_runtime, planes_seguimiento


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def cliente(db):
    from backend.api.main import app

    app.dependency_overrides[get_db] = lambda: (yield db)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token(sub: str, plan: str = "free", rol: str = "usuario") -> dict:
    t = jwt.encode({"sub": sub, "username": sub, "plan": plan, "rol": rol, "exp": datetime.now(UTC) + timedelta(hours=1)}, settings.WEB_JWT_SECRET, algorithm=ALGORITMO_JWT)
    return {"Authorization": f"Bearer {t}"}


def _usuario(db, sub: str, plan: str) -> None:
    db.add(Usuario(device_id=sub, activo=1, plan=plan, nickname=sub, origen="web", creado_en="2026-11-20T00:00:00"))
    db.commit()


# ---------------------------------------------------------------- la API
def test_sin_sesion_no_se_entra(cliente):
    assert cliente.get("/api/v1/agent/seguimientos").status_code in (401, 422)
    assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Real Madrid"}).status_code in (401, 422)


def test_el_recorrido_completo_de_la_web_usa_las_mismas_reglas_que_el_chat(cliente, db):
    h = _token("web-1")
    _usuario(db, "web-1", "pro")
    inicial = cliente.get("/api/v1/agent/seguimientos", headers=h).json()
    assert inicial["equipos"] == [] and inicial["consentimiento"] is False and inicial["plan"] == "pro" and inicial["limites"] == {"equipos": 5, "ligas": 3, "partidos_24h": 6}
    sin_permiso = cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Real Madrid"}, headers=h).json()
    assert sin_permiso["ok"] is False and "acepto" in sin_permiso["mensaje"].lower()
    assert cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=h).json()["consentimiento"] is True
    r = cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Real Madrid"}, headers=h).json()
    assert r["ok"] is True and r["equipos"] == ["Real Madrid"] and "Ahora sigues a Real Madrid" in r["mensaje"]
    assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "liga", "nombre": "Premier League"}, headers=h).json()["ligas"] == ["Premier League"]
    avisos = cliente.put("/api/v1/agent/seguimientos/avisos", json={"activar": True}, headers=h).json()
    assert avisos["ok"] is True and avisos["avisos"] is True
    perfil = cliente.put("/api/v1/agent/perfil", json={"zona_horaria": "Chile", "estilo": "corto", "mercados": ["goles", "ambos marcan"]}, headers=h).json()
    assert perfil["ok"] is True and perfil["perfil"] == {"zona_horaria": "America/Santiago", "estilo": "corto", "mercados": ["goles", "ambos marcan"]}
    quitado = cliente.delete("/api/v1/agent/seguimientos", params={"nombre": "Real Madrid"}, headers=h).json()
    assert quitado["ok"] is True and quitado["equipos"] == []
    assert cliente.delete("/api/v1/agent/perfil", headers=h).json()["perfil"]["estilo"] is None


def test_lo_que_se_guarda_en_la_web_lo_ve_el_chat_con_la_misma_identidad(cliente, db):
    h = _token("web-2")
    _usuario(db, "web-2", "pro")
    cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=h)
    cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Boca Juniors"}, headers=h)
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "web-2", "que sigo", None, "web", False, False))
    assert "Boca Juniors" in r["respuesta"]


def test_los_datos_invalidos_se_rechazan_con_motivo(cliente, db):
    h = _token("web-3")
    cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=h)
    assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "jugador", "nombre": "Messi"}, headers=h).status_code == 422
    assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "ab"}, headers=h).status_code == 422
    r = cliente.put("/api/v1/agent/perfil", json={"estilo": "gritando"}, headers=h).json()
    assert r["ok"] is False and "Estilo no válido" in r["mensaje"]
    r = cliente.put("/api/v1/agent/perfil", json={"zona_horaria": "Marte"}, headers=h).json()
    assert r["ok"] is False and "No reconozco" in r["mensaje"]
    assert cliente.put("/api/v1/agent/perfil", json={"mercados": []}, headers=h).json()["ok"] is False
    assert cliente.put("/api/v1/agent/perfil", json={}, headers=h).json()["mensaje"] == "No hay nada que guardar."


def test_cada_persona_ve_solo_lo_suyo(cliente, db):
    a, b = _token("web-a"), _token("web-b")
    cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=a)
    cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Sevilla"}, headers=a)
    assert cliente.get("/api/v1/agent/seguimientos", headers=b).json()["equipos"] == []


def test_el_borrado_total_tambien_vacia_lo_de_la_web(cliente, db):
    h = _token("web-4")
    cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=h)
    cliente.put("/api/v1/agent/perfil", json={"estilo": "corto"}, headers=h)
    assert bot_memoria_repo.olvidar(db, "web-4")["bot_perfil_usuario"] == 1
    assert cliente.get("/api/v1/agent/seguimientos", headers=h).json()["perfil"]["estilo"] is None


# ---------------------------------------------------------------- MS-11: topes por plan
@pytest.mark.parametrize("plan, equipos, ligas", [("free", 3, 1), ("pro", 5, 3), ("max", 10, 6)])
def test_los_topes_dependen_del_plan_en_la_web(cliente, db, plan, equipos, ligas):
    sub = f"plan-{plan}"
    h = _token(sub, plan)
    _usuario(db, sub, plan)
    cliente.post("/api/v1/agent/seguimientos/consentimiento", headers=h)
    for i in range(equipos):
        assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": f"Equipo Numero{i}"}, headers=h).json()["ok"] is True
    pasado = cliente.post("/api/v1/agent/seguimientos", json={"tipo": "equipo", "nombre": "Equipo Extra"}, headers=h).json()
    assert pasado["ok"] is False and f"Máximo {equipos} equipos" in pasado["mensaje"]
    for i in range(ligas):
        assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "liga", "nombre": f"Liga Numero{i}"}, headers=h).json()["ok"] is True
    assert cliente.post("/api/v1/agent/seguimientos", json={"tipo": "liga", "nombre": "Liga Extra"}, headers=h).json()["ok"] is False


def test_los_topes_son_los_mismos_en_el_chat_de_telegram(db):
    _usuario(db, "555", "free")
    bot_memoria_repo.aceptar(db, "555")
    for nombre in ("Uno Fc", "Dos Fc", "Tres Fc"):
        assert bot_memoria_repo.agregar_equipo(db, "555", nombre)["ok"]
    r = asyncio.run(agent_runtime.procesar_mensaje(db, "telegram:555", "sigue al Cuatro Fc", None, "telegram_agent", False, False))
    assert "Máximo 3 equipos con tu plan" in r["respuesta"]


def test_un_administrador_tiene_los_topes_del_plan_max_y_quien_no_esta_registrado_los_de_siempre(db, monkeypatch):
    assert planes_seguimiento.limites(db, "nadie") == planes_seguimiento.SIN_PLAN == {"equipos": 5, "ligas": 3, "partidos_24h": 6}
    assert planes_seguimiento.limites(db, "nadie", es_admin=True) == planes_seguimiento.LIMITES["max"]
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "999,1000")
    assert planes_seguimiento.limites(db, "telegram:999") == planes_seguimiento.LIMITES["max"]


def test_si_la_base_falla_el_plan_no_rompe_y_rige_el_limite_de_siempre(db, monkeypatch):
    def roto(*_a, **_k):
        raise RuntimeError("tabla ausente")

    monkeypatch.setattr(db, "query", roto)
    assert planes_seguimiento.plan_de(db, "x") is None
