"""Simulador público (H-018, regla simulaciones-internas-y-publicas.md): solo planes pro/max y administradores, con datos propios (viejos + actuales) y de punta a punta sobre migraciones reales.

Datos sintéticos de una liga de 8 equipos: una temporada anterior COMPLETA (ida y vuelta) y una actual a medias. Se prueba el cálculo (tabla, partidos que faltan, rechazos honestos) y el acceso por plan
(sin sesión, free, pro, max, administrador, plan vencido, token con un plan que la base no respalda).
"""
from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api.models.usuarios import Usuario
from backend.api.services import simulador_propio as sp

EQ = [f"Eq{i}" for i in range(8)]


def _liga(codigo="E0", jugados_actual=20, repetir=False, quitar_equipo=False):
    ps, dia = [], date(2025, 8, 1).toordinal()
    for a, b in itertools.permutations(EQ, 2):  # temporada anterior completa
        dia += 1
        ps.append({"liga": codigo, "temporada": "2025/2026", "dia": dia, "fecha": date.fromordinal(dia), "local": a, "visitante": b, "gl": (dia % 3), "gv": (dia % 2), "tl": None, "tv": None, "al": None, "av": None})
    dia = date(2026, 8, 10).toordinal()
    pares = list(itertools.permutations(EQ if not quitar_equipo else EQ[:-1], 2))[:jugados_actual]
    if repetir and pares:
        pares.append(pares[0])
    for a, b in pares:
        dia += 1
        ps.append({"liga": codigo, "temporada": "2026/2027", "dia": dia, "fecha": date.fromordinal(dia), "local": a, "visitante": b, "gl": (dia % 3), "gv": (dia % 2), "tl": None, "tv": None, "al": None, "av": None})
    return ps


# ------------------------------------------------------------------ cálculo
def test_la_tabla_y_los_partidos_pendientes_salen_de_los_resultados_propios():
    b = sp.preparar("E0", _liga(jugados_actual=20))
    assert b["ok"] and b["partidos_jugados"] == 20 and len(b["pendientes"]) == 8 * 7 - 20 and len(b["equipos"]) == 8
    assert sum(f["pj"] for f in b["tabla"]) == 40 and all(f["pts"] == 3 * 0 + f["pts"] for f in b["tabla"])
    jugados = {(p["local"], p["visitante"]) for p in _liga(jugados_actual=20) if p["temporada"] == "2026/2027"}
    assert not ({(p["local"], p["visitante"]) for p in b["pendientes"]} & jugados), "un partido ya jugado no puede estar pendiente"


@pytest.mark.parametrize("partidos,fragmento", [
    ([], "no tiene datos propios"),
    (_liga(quitar_equipo=True), "aún no tiene datos de los 8 equipos"),
    (_liga(repetir=True), "partidos repetidos"),
    ([p for p in _liga() if p["temporada"] == "2026/2027"], "No hay una temporada anterior completa"),
])
def test_si_no_se_puede_estimar_con_honestidad_se_dice_y_no_se_inventa_la_tabla(partidos, fragmento):
    r = sp.preparar("E0", partidos)
    assert r["ok"] is False and fragmento in r["razon"]


def test_la_simulacion_devuelve_probabilidades_coherentes_y_declara_su_procedencia(monkeypatch):
    monkeypatch.setitem(sp.SLUGS, "prueba", ("E0", "Liga de prueba"))
    r = sp.simular("prueba", n_sim=2000, partidos=_liga())
    assert r["ok"] and r["n_simulaciones"] == 2000 and r["partidos_pendientes"] == 36 and r["datos_hasta"] and r["motor"] in ("go", "python") and "no es una certeza" in r["aviso"]
    assert abs(sum(v["prob_campeon"] for v in r["tabla"].values()) - 1.0) < 1e-6
    assert abs(sum(v["prob_descenso"] for v in r["tabla"].values()) - 3.0) < 1e-6 and abs(sum(v["prob_copa"] for v in r["tabla"].values()) - 4.0) < 1e-6
    assert all(1 <= v["posicion_promedio"] <= 8 and v["puntos"]["p05"] <= v["puntos"]["p95"] for v in r["tabla"].values())


def test_el_tope_de_simulaciones_se_aplica_y_una_liga_desconocida_se_rechaza():
    assert sp.simular("no_existe")["ok"] is False
    import backend.api.services.simulador_propio as modulo

    assert modulo.N_SIM_MAX == 20_000


def test_la_misma_semilla_da_el_mismo_resultado_en_python(monkeypatch):
    monkeypatch.setitem(sp.SLUGS, "prueba", ("E0", "Liga de prueba"))
    monkeypatch.setenv("LAPLACE_MOTOR_SIM", "python")
    a = sp.simular("prueba", n_sim=500, partidos=_liga())
    b = sp.simular("prueba", n_sim=500, partidos=_liga())
    assert a["tabla"] == b["tabla"]


# ------------------------------------------------------------------ acceso por plan (HTTP real sobre migraciones)
@pytest.fixture()
def cliente(base_migrada, monkeypatch):
    from backend.api.core.config import settings
    from backend.api.db.session import SessionLocal, get_db
    from backend.api.main import app

    fabrica = base_migrada("head")
    original = SessionLocal.kw.get("bind")
    SessionLocal.configure(bind=fabrica.kw["bind"])
    monkeypatch.setitem(sp.SLUGS, "prueba", ("E0", "Liga de prueba"))
    monkeypatch.setattr(sp, "_partidos", lambda: _liga())
    monkeypatch.setattr(settings, "WEB_JWT_SECRET", "secreto-de-prueba-suficientemente-largo-0123456789")
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "999")

    def db():
        s = fabrica()
        try:
            yield s
        finally:
            s.close()

    from backend.api.core.rate_limit import limiter

    limiter.reset()  # el límite por IP es global: cada prueba empieza con el cupo lleno
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            c.fabrica = fabrica
            yield c
    finally:
        app.dependency_overrides.clear()
        SessionLocal.configure(bind=original)


def _token(cliente, device_id, plan_claim="free"):
    from backend.api.routers.auth import _emitir_token

    class U:  # lo mínimo que lee _emitir_token
        pass

    u = U()
    u.device_id, u.username, u.plan, u.rol = device_id, device_id, plan_claim, "usuario"
    return _emitir_token(u)


def _usuario(cliente, device_id, plan, rol="usuario", activo_hasta=None):
    with cliente.fabrica() as db:
        db.add(Usuario(device_id=device_id, username=device_id, activo=1, plan=plan, rol=rol, activo_hasta=activo_hasta, creado_en="2026-11-12 10:00:00", origen="web"))
        db.commit()


def test_el_limite_de_frecuencia_protege_el_simulador(cliente):
    _usuario(cliente, "rl", "pro")
    cab = {"Authorization": f"Bearer {_token(cliente, 'rl', 'pro')}"}
    codigos = [cliente.get("/api/v1/simulador/prueba?n_simulaciones=100", headers=cab).status_code for _ in range(12)]
    assert codigos.count(200) == 10 and codigos.count(429) == 2


def test_sin_sesion_el_simulador_responde_401_pero_la_lista_de_ligas_es_publica(cliente):
    assert cliente.get("/api/v1/simulador/prueba").status_code == 401
    r = cliente.get("/api/v1/simulador")
    assert r.status_code == 200 and "pro o max" in r.json()["requiere"] and any(x["slug"] == "premier" for x in r.json()["ligas"])


@pytest.mark.parametrize("plan,rol,vence,esperado", [
    ("free", "usuario", None, 403), ("pro", "usuario", None, 200), ("max", "usuario", None, 200), ("free", "admin", None, 200),
    ("pro", "usuario", (date.today() - timedelta(days=3)).isoformat(), 403), ("pro", "usuario", (date.today() + timedelta(days=30)).isoformat(), 200),
])
def test_solo_planes_pro_max_y_administradores_pueden_simular(cliente, plan, rol, vence, esperado):
    _usuario(cliente, "u1", plan, rol, vence)
    r = cliente.get("/api/v1/simulador/prueba?n_simulaciones=300", headers={"Authorization": f"Bearer {_token(cliente, 'u1', plan)}"})
    assert r.status_code == esperado, r.text[:200]
    if esperado == 403:
        assert "planes pro y max" in r.json()["detail"]
    else:
        assert r.json()["ok"] is True and r.json()["tabla"]


def test_un_token_que_dice_max_no_concede_nada_si_la_base_dice_free(cliente):
    _usuario(cliente, "falso", "free")
    r = cliente.get("/api/v1/simulador/prueba?n_simulaciones=300", headers={"Authorization": f"Bearer {_token(cliente, 'falso', plan_claim='max')}"})
    assert r.status_code == 403


def test_un_token_de_alguien_que_no_existe_en_la_base_no_simula(cliente):
    assert cliente.get("/api/v1/simulador/prueba", headers={"Authorization": f"Bearer {_token(cliente, 'fantasma', 'max')}"}).status_code == 403


def test_el_administrador_declarado_en_el_env_simula_sin_fila_de_plan(cliente):
    assert cliente.get("/api/v1/simulador/prueba?n_simulaciones=300", headers={"Authorization": f"Bearer {_token(cliente, '999')}"}).status_code == 200


def test_un_token_adulterado_o_mal_formado_no_pasa(cliente):
    assert cliente.get("/api/v1/simulador/prueba", headers={"Authorization": "Bearer basura"}).status_code == 401
    assert cliente.get("/api/v1/simulador/prueba", headers={"Authorization": "Basic abc"}).status_code == 401


# ------------------------------------------------------------------ Telegram y agente (mismo acceso que la web)
@pytest.fixture()
def canales(base_migrada, monkeypatch):
    from unittest.mock import AsyncMock

    from backend.api.bot import laplace_bot, laplace_bot_usuario
    from backend.api.core.config import settings
    from backend.tests.test_e2e_menu_telegram import _Entorno

    fabrica = base_migrada("head")
    monkeypatch.setattr(laplace_bot_usuario, "SessionLocal", fabrica)
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "999")
    monkeypatch.setitem(sp.SLUGS, "prueba", ("E0", "Liga de prueba"))
    monkeypatch.setitem(sp.ALIAS_LIGAS, "liga de prueba", "prueba")
    monkeypatch.setattr(sp, "_partidos", lambda: _liga())
    monkeypatch.setattr(laplace_bot.telegram_client, "enviar_mensaje", AsyncMock())
    return fabrica, _Entorno(fabrica)


@pytest.mark.parametrize("persona,plan,rol,permitido", [("5001", None, "usuario", False), ("5002", "free", "usuario", False), ("5003", "pro", "usuario", True), ("5004", "max", "usuario", True), ("999", None, "usuario", True)])
def test_telegram_simular_responde_segun_el_plan(canales, persona, plan, rol, permitido):
    import asyncio

    from backend.api.bot import laplace_bot

    fabrica, ent = canales
    if plan:
        with fabrica() as db:
            db.add(Usuario(device_id=persona, username=persona, activo=1, plan=plan, rol=rol, creado_en="2026-11-12 10:00:00", origen="telegram"))
            db.commit()
    for args, esperado in (((), "Simulador de liga" if permitido else "planes pro y max"), (("prueba",), "Campeón:" if permitido else "planes pro y max"), (("zzz",), "No conozco esa liga" if permitido else "planes pro y max")):
        u = ent.update(persona)
        asyncio.run(laplace_bot.cmd_simular(u, ent.contexto(*args)))
        textos = ent.respuestas(u)
        assert textos and esperado in textos[0], (persona, args, textos)
        if not permitido:
            assert "Campeón:" not in textos[0], "un usuario sin plan vio el resultado"


@pytest.mark.parametrize("plan,es_admin,permitido", [("free", False, False), ("pro", False, True), ("max", False, True), ("free", True, True)])
def test_el_agente_simula_solo_para_planes_pro_max_y_administradores(canales, plan, es_admin, permitido):
    import asyncio

    from backend.api.services.agent_runtime import procesar_mensaje

    fabrica, _ = canales
    with fabrica() as db:
        db.add(Usuario(device_id="7", username="siete", activo=1, plan=plan, rol="usuario", creado_en="2026-11-12 10:00:00", origen="web"))
        db.commit()
        r = asyncio.run(procesar_mensaje(db, "7", "quien sera campeon de la liga de prueba", None, "web", False, es_admin))
    assert r["herramienta"] == "agent.simulate_league"
    assert ("Campeón:" in r["respuesta"]) is permitido and ("planes pro y max" in r["respuesta"]) is (not permitido)


def test_el_tope_responde_vacio_con_el_cupo_lleno_y_el_cupo_vuelve_al_terminar_fallar_o_cancelarse(monkeypatch):
    import threading
    import time

    from backend.api.routers import simulador as r

    suelta = threading.Event()
    monkeypatch.setattr(r.simulador_propio, "simular", lambda *a: (suelta.wait(5), {"ok": 1})[1])
    f1, f2 = r._lanzar_simulacion("x", 1, 4, 3), r._lanzar_simulacion("x", 1, 4, 3)
    assert f1 and f2 and r._lanzar_simulacion("x", 1, 4, 3) is None, "con el cupo lleno no entra otra"
    suelta.set()
    assert f1.result(5) == {"ok": 1} and f2.result(5) == {"ok": 1}
    time.sleep(0.2)
    # un fallo del cálculo también devuelve el cupo
    monkeypatch.setattr(r.simulador_propio, "simular", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    f3 = r._lanzar_simulacion("x", 1, 4, 3)
    with pytest.raises(RuntimeError):
        f3.result(5)
    time.sleep(0.2)
    # y si el envío al ejecutor falla, no queda tomado
    monkeypatch.setattr(r._ejecutor, "submit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin hilos")))
    with pytest.raises(RuntimeError):
        r._lanzar_simulacion("x", 1, 4, 3)
    assert [r._cupo.acquire(blocking=False) for _ in range(r.MAX_SIMULACIONES_SIMULTANEAS)] == [True, True]
    for _ in range(r.MAX_SIMULACIONES_SIMULTANEAS):
        r._cupo.release()


def test_sin_los_datos_historicos_el_simulador_lo_dice_y_no_se_cae(monkeypatch):
    """La instalación pública no trae los datos (licencias de terceros): la lista de ligas responde 200 con el motivo en cada una, y al aparecer los datos funciona sin reiniciar."""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    def sin_archivo(*a, **k):
        raise FileNotFoundError("no hay partidos.csv")

    sp.limpiar_cache()
    monkeypatch.setattr(sp.datos, "cargar_partidos_con_vivo", sin_archivo)
    r = TestClient(app).get("/api/v1/simulador")
    assert r.status_code == 200
    ligas = r.json()["ligas"]
    assert ligas and not any(x["disponible"] for x in ligas) and all(x.get("motivo") for x in ligas)
    assert sp.simular("premier")["ok"] is False
    monkeypatch.setattr(sp.datos, "cargar_partidos_con_vivo", lambda *a, **k: ([], {}))  # los datos «aparecen»: no queda guardado el fallo
    assert sp._partidos() == []
    sp.limpiar_cache()
