"""test_analisis_completo.py — verifica el punto central del bug real de WF-B (`Guardar en
BD` con `cmd: ''` — el job de un análisis con IA nunca se marcaba `listo`). Acá se confirma
empíricamente (no solo "compila") que `procesar_job` deja SIEMPRE el job en un estado terminal
y persiste el análisis, tanto con IA (plan pro) como sin ella (plan free), y también cuando
falla a mitad de camino.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.db import usuarios_repo
from backend.api.db.jobs_repo import crear_job, crear_job_app
from backend.api.models.jobs import Job
from backend.api.models.predicciones import AnalisisComparativo, AnalisisIndividual, AnalisisModulo
from backend.api.models.usuarios import Usuario
from backend.api.services import analisis_completo


def _resultado_motor_fake(local="River Plate", visitante="Boca Juniors"):
    return {
        "local": local, "visitante": visitante, "liga": "Liga Profesional",
        "modulos": {
            "poisson": {"ok": True, "pick": "Local", "prob_local": 0.55, "prob_empate": 0.25,
                        "prob_visitante": 0.20, "over25_prob": 0.5, "btts_prob": 0.4,
                        "confianza_score": 70, "confianza": "ALTA", "marcador_probable": "2-1",
                        "value_bet": False, "value_pct": 0},
            "forma": {"ok": True, "pick": "Local", "prob_local": 0.6, "prob_visitante": 0.4,
                      "confianza_score": 60},
        },
        "modulos_skip": {},
        "consenso": {"pick_final": "Local", "nivel": "MODERADO", "score_consenso": 65,
                     "confianza_final": "MEDIA", "total_modulos": 2},
    }


@pytest.fixture()
def mocks(monkeypatch):
    async def _fixtures_cascada(db, client, fecha):
        return [{"Snm": "Liga Profesional", "Events": [
            {"Eid": "999", "Eps": "NS", "T1": [{"Nm": "River Plate"}], "T2": [{"Nm": "Boca Juniors"}]}
        ]}], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        return {"odds_local": None, "odds_empate": None, "odds_visit": None, "odds_disponibles": False, "odds_source": "ninguna"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        return {"h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0,
                "h2h_total": 0, "h2h_resumen": "Sin historial directo disponible.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}

    async def _bsd(client, local, visitante, fecha):
        # settings.BSD_API_KEY viene de un .env real (no vacío) — sin este mock, estos tests
        # dispararían una llamada HTTP real a BSD en cada corrida de la suite. None = "BSD no
        # tuvo el partido", mismo comportamiento por default que antes de conectar bsd_ml.
        return None

    async def _bsd_xg(db, client, local, visitante, fecha):
        # Mismo motivo que `_bsd` arriba — `gateway.enriquecer_bsd` (xG, conectado 2026-09-10)
        # también pegaría a la red real de BSD sin este mock. `found=False` = comportamiento
        # real cuando BSD no tiene el partido (ver `gateway.enriquecer_bsd`).
        return {"found": False, "motivo": "mock", "fuente": "bsd"}

    def _motor_analizar(d):
        return _resultado_motor_fake(d["local"], d["visitante"])

    enviados: list[tuple[str, str]] = []

    async def _enviar_mensaje(client, chat_id, texto, **kw):
        enviados.append((chat_id, texto))
        return True

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd)
    monkeypatch.setattr(analisis_completo.gateway, "enriquecer_bsd", _bsd_xg)
    monkeypatch.setattr(analisis_completo.motor, "analizar_partido", _motor_analizar)
    monkeypatch.setattr(analisis_completo.telegram_client, "enviar_mensaje", _enviar_mensaje)

    # Este fixture prueba persistencia y consenso con un motor falso ya validado. Declara la
    # procedencia mínima de ese escenario para que la puerta de calidad no lo confunda con un
    # fallback de proveedores reales.
    enriquecer_real = analisis_completo._enriquecer_partido

    async def _enriquecer_validado(*args, **kwargs):
        datos = await enriquecer_real(*args, **kwargs)
        datos["calidad_datos"] = {"eligible": True, "sources": ["fixture-test", "motor-test"], "source_count": 2, "reason": None}
        return datos

    monkeypatch.setattr(analisis_completo, "_enriquecer_partido", _enriquecer_validado)
    return enviados


def test_procesar_job_telegram_free_no_llama_claude_y_queda_listo(db_session, mocks):
    job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id="12345", user_id="u1", plan="free")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    job = db_session.query(Job).filter(Job.job_id == job_id).first()
    assert job.status == "listo"
    assert len(mocks) == 1  # se envió un mensaje a Telegram
    assert db_session.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == "999").count() == 1


def test_procesar_job_puebla_analisis_modulos_y_columnas_por_modulo(db_session, mocks):
    """2026-09-09 — cierra el hallazgo real de la auditoría (`analisis_modulos` en 0 filas en la
    BD real porque `_persistir` llamaba a `guardar_comparativo`, que nunca tocaba esa tabla):
    confirma contra la BD real de test — no solo que `procesar_job` no tira excepción — que
    `AnalisisModulo` queda con una fila por módulo que corrió (poisson + forma, únicos que
    devuelve `_resultado_motor_fake`) y que las columnas por-módulo de `AnalisisComparativo`
    (antes siempre NULL en este pipeline) quedan pobladas con el mismo dato."""
    job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id="12345", user_id="u1", plan="free")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    modulos = db_session.query(AnalisisModulo).filter(AnalisisModulo.partido_id == "999").all()
    nombres = {m.modulo for m in modulos}
    assert nombres == {"poisson", "forma"}
    poisson_row = next(m for m in modulos if m.modulo == "poisson")
    assert poisson_row.pick == "Local"
    assert poisson_row.score == 70
    assert poisson_row.confianza == "ALTA"
    assert poisson_row.datos_json is not None  # guarda el dict completo del módulo (over25_prob, etc.)

    ac = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "999").first()
    assert ac is not None
    assert ac.pick_form == "Local" and ac.score_form == 60
    assert ac.score_poisson == 70
    assert ac.consenso_nivel == "MODERADO"
    assert ac.consenso == "MODERADO"  # sin IA (plan free) — mismo valor que antes ponía guardar_comparativo
    assert ac.total_modulos == 2
    assert ac.over25_pred == 0.5 and ac.btts_pred == 0.4
    # h2h/odds/tabla no corrieron en el motor mockeado (_resultado_motor_fake solo trae
    # poisson+forma) — sus columnas quedan NULL, no strings vacíos falsos.
    assert ac.pick_h2h is None and ac.pick_odds is None and ac.pick_tabla is None


def test_procesar_job_app_marca_resultado_app_sin_tocar_telegram(db_session, mocks):
    job_id = crear_job_app(db_session, match_id="999", fecha="20260101", device_id="dev1", plan="free",
                            local="River Plate", visitante="Boca Juniors", liga="Liga Profesional")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    job = db_session.query(Job).filter(Job.job_id == job_id).first()
    assert job.status == "listo"
    assert job.resultado_app is not None
    assert len(mocks) == 0  # origen app no envía Telegram


def test_procesar_job_con_ia_usa_claude_y_combina_pick(db_session, mocks, monkeypatch):
    async def _ia_ok(prompt, max_tokens=1024):
        return "🏆 River Plate vs Boca Juniors\n\n⚖️ Balance y PICK: River Plate"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_ok)
    job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id="12345", user_id="u1", plan="pro")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    job = db_session.query(Job).filter(Job.job_id == job_id).first()
    assert job.status == "listo"
    chat_id, texto = mocks[0]
    assert "PICK" in texto
    assert "River Plate" in texto


def test_procesar_job_app_pro_incrementa_contador_uso_ia(db_session, mocks, monkeypatch):
    """Bug real corregido en la auditoría de permisos 2026-09-08: `usuarios_repo.
    registrar_uso_ia_app` existía pero nada la llamaba — el límite de 10 IA/día del plan `pro`
    en la app nunca se aplicaba de verdad (`UsoDiarioIaApp.usados` quedaba siempre en 0, a
    diferencia de Telegram, donde `verificar_limite` sí cuenta jobs reales del día). Se verifica
    la post-condición real en BD (no solo que el job termine 'listo'), como pide
    `empirical-verification-before-fix.md`."""
    async def _ia_ok(prompt, max_tokens=1024):
        return "🏆 River Plate vs Boca Juniors\n\n⚖️ Balance y PICK: River Plate"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_ok)
    # `verificar_limite_ia_app` lee el plan VIGENTE desde `Usuario.plan` (no el plan que el job
    # llevaba grabado al crearse) — sin esta fila, `usuario is None` degrada a plan "free" y la
    # IA nunca se dispara. Confirmado empíricamente al escribir este test (fallaba sin esto).
    db_session.add(Usuario(device_id="dev_pro", activo=1, plan="pro", origen="app", creado_en="2026-01-01 00:00:00"))
    db_session.commit()

    job_id = crear_job_app(db_session, match_id="999", fecha="20260101", device_id="dev_pro", plan="pro",
                            local="River Plate", visitante="Boca Juniors", liga="Liga Profesional")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    job = db_session.query(Job).filter(Job.job_id == job_id).first()
    assert job.status == "listo"

    uso = usuarios_repo.verificar_limite_ia_app(db_session, "dev_pro")
    assert uso["usados_hoy"] == 1
    assert uso["restantes_ia"] == 9  # límite pro = 10/día


def test_procesar_job_app_free_no_incrementa_contador_uso_ia(db_session, mocks):
    """free nunca usa IA (solo estadístico) — el contador de uso de IA de la app debe quedar
    en 0, no solo el mensaje de bienvenida debe decir 'gratis'."""
    job_id = crear_job_app(db_session, match_id="999", fecha="20260101", device_id="dev_free", plan="free",
                            local="River Plate", visitante="Boca Juniors", liga="Liga Profesional")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    uso = usuarios_repo.verificar_limite_ia_app(db_session, "dev_free")
    assert uso["usados_hoy"] == 0


def test_procesar_job_marca_error_si_falla_a_mitad_de_camino(db_session, mocks, monkeypatch):
    async def _rompe(db, client, fecha):
        raise RuntimeError("fuente externa caída")

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _rompe)
    job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id="12345", user_id="u1", plan="free")["job_id"]

    async def _run():
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    asyncio.run(_run())

    job = db_session.query(Job).filter(Job.job_id == job_id).first()
    assert job.status == "error"  # nunca queda colgado en 'procesando'
    assert any("error" in texto.lower() for _, texto in mocks)


def test_consenso_ia_segundo_usuario_distinto_valida_y_ahorra_llamadas_a_la_ia(db_session, mocks, monkeypatch):
    """Piece 2 del pedido (consenso 'N usuarios validan el mismo resultado de IA', ver
    db/consenso_ia_repo.py) — distinto de CacheConsenso (esa cuenta análisis, no usuarios
    distintos). Verifica con un mock que cuenta invocaciones reales:

    - Usuario 1 pide análisis del partido -> llama a la IA real (1 llamada), pick queda como
      candidato SIN validar (1 solo usuario no alcanza).
    - Usuario 2, DISTINTO, pide análisis del MISMO partido y la IA da el MISMO pick -> llama
      a la IA real otra vez (2da llamada, porque el candidato del usuario 1 todavía no estaba
      validado) y con esa coincidencia el resultado queda validado.
    - Usuario 3, DISTINTO de los dos anteriores, pide análisis del MISMO partido DENTRO del
      TTL -> debe servirse desde el consenso ya validado, CERO llamadas nuevas a la IA.

    Total esperado: 2 llamadas reales a la IA para 3 usuarios distintos pidiendo el mismo
    partido — el mecanismo ahorra, nunca duplica."""
    llamadas_ia = {"n": 0}

    async def _ia_ok(prompt, max_tokens=1024):
        llamadas_ia["n"] += 1
        return "🏆 River Plate vs Boca Juniors\n\n⚖️ Balance y PICK: River Plate"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_ok)

    async def _run(job_id):
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    job_id_1 = crear_job(db_session, match_id="999", fecha="20260101", chat_id="c1", user_id="usuario_1", plan="pro")["job_id"]
    asyncio.run(_run(job_id_1))
    assert llamadas_ia["n"] == 1
    assert db_session.query(Job).filter(Job.job_id == job_id_1).first().status == "listo"

    job_id_2 = crear_job(db_session, match_id="999", fecha="20260101", chat_id="c2", user_id="usuario_2", plan="pro")["job_id"]
    asyncio.run(_run(job_id_2))
    assert llamadas_ia["n"] == 2, "el 2do usuario distinto todavia debe llamar a la IA real (recién ahí valida)"
    assert db_session.query(Job).filter(Job.job_id == job_id_2).first().status == "listo"

    job_id_3 = crear_job(db_session, match_id="999", fecha="20260101", chat_id="c3", user_id="usuario_3", plan="pro")["job_id"]
    asyncio.run(_run(job_id_3))
    assert llamadas_ia["n"] == 2, "el 3er usuario debe servirse del consenso validado — 0 llamadas nuevas a la IA"
    job_3 = db_session.query(Job).filter(Job.job_id == job_id_3).first()
    assert job_3.status == "listo"
    chat_id_3, texto_3 = mocks[-1]
    assert "River Plate" in texto_3  # el pick validado se sigue formateando y enviando normal


def test_consenso_ia_mismo_usuario_repetido_no_cuenta_como_segunda_confirmacion(db_session, mocks, monkeypatch):
    """Un mismo usuario pidiendo el análisis dos veces no debe poder 'auto-validar' el
    consenso — hace falta un SEGUNDO usuario DISTINTO."""
    llamadas_ia = {"n": 0}

    async def _ia_ok(prompt, max_tokens=1024):
        llamadas_ia["n"] += 1
        return "🏆 River Plate vs Boca Juniors\n\n⚖️ Balance y PICK: River Plate"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_ok)

    async def _run(job_id):
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    for _ in range(2):
        job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id="c1", user_id="mismo_usuario", plan="pro")["job_id"]
        asyncio.run(_run(job_id))

    assert llamadas_ia["n"] == 2, "el mismo usuario repitiendo no debe validar el consenso ni ahorrar la llamada a la IA"


def test_consenso_ia_pick_divergente_no_valida_y_sigue_llamando_a_la_ia(db_session, mocks, monkeypatch):
    """Si un segundo usuario distinto pide el mismo partido pero la IA da un pick DIFERENTE,
    no hay consenso — el candidato se reemplaza y un 3er usuario que coincida con ESE nuevo
    candidato es quien lo valida."""
    picks = iter([
        "⚖️ Balance y PICK: River Plate",   # usuario_1
        "⚖️ Balance y PICK: Boca Juniors",  # usuario_2 (diverge del candidato de usuario_1)
        "⚖️ Balance y PICK: Boca Juniors",  # usuario_3 (coincide con el candidato de usuario_2)
    ])
    llamadas_ia = {"n": 0}

    async def _ia_variable(prompt, max_tokens=1024):
        llamadas_ia["n"] += 1
        return f"🏆 River Plate vs Boca Juniors\n\n{next(picks)}"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_variable)

    async def _run(job_id):
        async with httpx.AsyncClient() as client:
            await analisis_completo.procesar_job(db_session, client, job_id)

    for i in range(1, 4):
        job_id = crear_job(db_session, match_id="999", fecha="20260101", chat_id=f"c{i}", user_id=f"usuario_{i}", plan="pro")["job_id"]
        asyncio.run(_run(job_id))

    assert llamadas_ia["n"] == 3, "un pick divergente no ahorra la llamada — reemplaza el candidato en vez de validar"

    from backend.api.db import consenso_ia_repo
    validado = consenso_ia_repo.leer_validado(db_session, "999")
    assert validado is not None
    assert validado["pick_ia"] == "Boca Juniors"
    assert validado["usuarios_confirmaron"] == 2


def test_enriquecer_partido_corre_standings_odds_h2h_bsd_en_paralelo(db_session, monkeypatch):
    """Antes del refactor 2026-09-09, standings->odds->H2H se esperaban secuencialmente
    (latencia real = suma de las 3). Con asyncio.gather, la latencia real debe acercarse al
    máximo de las 5 fuentes (BSD pick + BSD xG, conectado 2026-09-10), no a la suma — se simula
    un delay artificial por fuente y se mide el tiempo real transcurrido."""
    DELAY = 0.15

    async def _fixtures_cascada(db, client, fecha):
        return [], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        await asyncio.sleep(DELAY)
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        await asyncio.sleep(DELAY)
        return {"odds_local": None, "odds_empate": None, "odds_visit": None, "odds_disponibles": False, "odds_source": "ninguna"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        await asyncio.sleep(DELAY)
        return {"h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0,
                "h2h_total": 0, "h2h_resumen": "Sin historial directo disponible.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}

    async def _bsd(client, local, visitante, fecha):
        await asyncio.sleep(DELAY)
        return None

    async def _bsd_xg(db, client, local, visitante, fecha):
        await asyncio.sleep(DELAY)
        return {"found": False, "motivo": "mock", "fuente": "bsd"}

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd)
    monkeypatch.setattr(analisis_completo.gateway, "enriquecer_bsd", _bsd_xg)

    async def _run():
        async with httpx.AsyncClient() as client:
            inicio = asyncio.get_event_loop().time()
            d = await analisis_completo._enriquecer_partido(
                db_session, client, {"local": "A", "visitante": "B", "liga": "Liga X"}, "999", "20260101"
            )
            elapsed = asyncio.get_event_loop().time() - inicio
            return d, elapsed

    d, elapsed = asyncio.run(_run())

    # Secuencial habría tardado >= 5*DELAY (~0.75s); en paralelo debe quedar bien por debajo
    # de 2*DELAY (holgura generosa para no ser flaky en CI cargado).
    assert elapsed < DELAY * 2
    assert d["odds_disponibles"] is False
    assert d["h2h_disponible"] is False
    assert d["bsd_prediccion"] is None
    assert d["xg_local"] is None
    assert d["xg_visit"] is None


def test_enriquecer_partido_propaga_bsd_prediccion_al_dict_final(db_session, monkeypatch):
    """`d['bsd_prediccion']` debe llegar tal cual lo devuelve bsd_predictions — es lo que
    motor.py::validar_bsd() lee para decidir si bsd_ml corre."""
    async def _fixtures_cascada(db, client, fecha):
        return [], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        return {"odds_local": None, "odds_empate": None, "odds_visit": None, "odds_disponibles": False, "odds_source": "ninguna"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        return {"h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0,
                "h2h_total": 0, "h2h_resumen": "Sin historial directo disponible.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}

    bsd_esperado = {"disponible": True, "pick": "Local", "pick_nombre": "River Plate",
                     "confianza_pct": 65, "fuente": "bsd_ml"}

    async def _bsd(client, local, visitante, fecha):
        return bsd_esperado

    xg_esperado = {"found": True, "event_id": "e1", "xg_local": 1.85, "xg_visit": 0.92,
                    "xg_disponible": True, "odds_local": None, "odds_empate": None,
                    "odds_visit": None, "odds_disponibles": False, "fuente": "bsd"}

    async def _bsd_xg(db, client, local, visitante, fecha):
        return xg_esperado

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd)
    monkeypatch.setattr(analisis_completo.gateway, "enriquecer_bsd", _bsd_xg)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await analisis_completo._enriquecer_partido(
                db_session, client, {"local": "River Plate", "visitante": "Boca", "liga": "Liga X"}, "999", "20260101"
            )

    d = asyncio.run(_run())
    assert d["bsd_prediccion"] == bsd_esperado
    # xG conectado 2026-09-10 — regresión del hallazgo real: `pronostico.py` ya sabía mezclar
    # xG (peso 0.30) pero `gateway.enriquecer_bsd()` nunca se llamaba desde producción.
    assert d["xg_local"] == 1.85
    assert d["xg_visit"] == 0.92


def test_enriquecer_partido_bsd_que_lanza_excepcion_no_bloquea_el_resto(db_session, monkeypatch):
    """Si bsd_predictions revienta con una excepción no prevista (no solo un fallo de red que
    ya atrapa internamente), _bsd_prediccion_segura debe atraparla y dejar bsd_prediccion=None
    en vez de tumbar el resto del enriquecimiento (odds/h2h/standings)."""
    async def _fixtures_cascada(db, client, fecha):
        return [], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        return {"odds_local": 2.0, "odds_empate": 3.0, "odds_visit": 4.0, "odds_disponibles": True, "odds_source": "test"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        return {"h2h_disponible": False, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0,
                "h2h_total": 0, "h2h_resumen": "Sin historial directo disponible.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}

    async def _bsd_rompe(client, local, visitante, fecha):
        raise RuntimeError("BSD explotó de forma inesperada")

    async def _bsd_xg_rompe(db, client, local, visitante, fecha):
        # Mismo criterio que `_bsd_rompe` — `_bsd_xg_seguro` debe atrapar esto también
        # (ver analisis_completo.py) sin bloquear odds/h2h/standings.
        raise RuntimeError("BSD xG explotó de forma inesperada")

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd_rompe)
    monkeypatch.setattr(analisis_completo.gateway, "enriquecer_bsd", _bsd_xg_rompe)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await analisis_completo._enriquecer_partido(
                db_session, client, {"local": "A", "visitante": "B", "liga": "Liga X"}, "999", "20260101"
            )

    d = asyncio.run(_run())
    assert d["bsd_prediccion"] is None
    assert d["xg_local"] is None  # _bsd_xg_seguro atrapa la excepción igual que _bsd_prediccion_segura
    assert d["xg_visit"] is None
    assert d["odds_disponibles"] is True  # el resto del enriquecimiento no se vio afectado

def test_enriquecer_partido_marca_datos_de_respaldo_como_no_publicables(db_session, monkeypatch):
    async def _fixture_info(db, client, match_id, local, visitante, fecha):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None, "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(*_): return None
    async def _odds(*_): return {"odds_local": None, "odds_empate": None, "odds_visit": None, "odds_disponibles": False}
    async def _h2h(*_, **__): return {"h2h_disponible": False, "h2h_total": 0, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0, "h2h_resumen": "Sin historial", "goles_local_avg": 1.3, "goles_visit_avg": 1.0, "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}
    async def _bsd(*_): return None
    async def _xg(*_): return {"found": False}

    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _fixture_info)
    monkeypatch.setattr(analisis_completo, "_standings_o_none", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo, "_bsd_prediccion_segura", _bsd)
    monkeypatch.setattr(analisis_completo, "_bsd_xg_seguro", _xg)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await analisis_completo._enriquecer_partido(db_session, client, {"local": "A", "visitante": "B", "liga": "Liga X"}, "sin-datos", "20260101")

    datos = asyncio.run(_run())
    assert datos["calidad_datos"]["eligible"] is False
    assert datos["calidad_datos"]["source_count"] == 0
    assert datos["fuente_goles"] == "liga_generico"


def _enriquecer_con(db_session, monkeypatch, *, odds_ok, bsd, historico_ok):
    async def _fixture_info(db, client, match_id, local, visitante, fecha):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None, "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(*_): return None
    async def _odds(*_):
        return {"odds_local": 2.0 if odds_ok else None, "odds_empate": 3.2 if odds_ok else None,
                "odds_visit": 3.8 if odds_ok else None, "odds_disponibles": odds_ok}
    async def _h2h(*_, **__): return {"h2h_disponible": False, "h2h_total": 0, "h2h_local_wins": 0, "h2h_visit_wins": 0, "h2h_empates": 0, "h2h_resumen": "Sin historial", "goles_local_avg": 1.3, "goles_visit_avg": 1.0, "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3}
    async def _bsd(*_): return {"disponible": True, "pick": "Local"} if bsd else None
    async def _xg(*_): return {"found": False}

    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _fixture_info)
    monkeypatch.setattr(analisis_completo, "_standings_o_none", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo, "_bsd_prediccion_segura", _bsd)
    monkeypatch.setattr(analisis_completo, "_bsd_xg_seguro", _xg)
    monkeypatch.setattr(
        analisis_completo.calidad_datos_svc.modelo_historico_svc, "validar_historico",
        lambda d: (historico_ok, "ok" if historico_ok else "fuera de cobertura"),
    )

    async def _run():
        async with httpx.AsyncClient() as client:
            return await analisis_completo._enriquecer_partido(db_session, client, {"local": "A", "visitante": "B", "liga": "Liga X"}, "p-cal", "20260101")

    return asyncio.run(_run())


def test_puerta_cuenta_historico_aunque_no_haya_fuentes_externas(db_session, monkeypatch):
    datos = _enriquecer_con(db_session, monkeypatch, odds_ok=False, bsd=False, historico_ok=True)
    assert datos["calidad_datos"]["sources"] == ["historico"]
    assert datos["calidad_datos"]["source_count"] == 1
    # El histórico con ambos equipos conocidos es un ancla medido (DC acierta 69 % con p>=0,60): publica solo.
    assert datos["calidad_datos"]["tier"] == "completa" and datos["calidad_datos"]["eligible"] is True


def test_puerta_no_cuenta_odds_y_bsd_como_dos_fuentes_independientes(db_session, monkeypatch):
    datos = _enriquecer_con(db_session, monkeypatch, odds_ok=True, bsd=True, historico_ok=False)
    assert datos["calidad_datos"]["sources"] == ["mercado"]  # un solo canal, aunque sean dos señales crudas
    assert datos["calidad_datos"]["source_count"] == 1
    assert datos["calidad_datos"]["eligible"] is True  # cuotas reales = ancla (cuotas con p>=0,60 aciertan 71 %)


def test_resumen_estadistico_para_ia_usa_la_probabilidad_ponderada():
    resultado = {
        "consenso": {
            "pick_final": "Visitante", "score_consenso": 52, "nivel": "MODERADO", "total_modulos": 2,
            "prob_ponderada": {"local": 0.30, "empate": 0.25, "visitante": 0.45},
            "peso_efectivo": {"odds": 0.8, "poisson": 0.2},
        },
        "modulos": {"poisson": {"ok": True, "prob_local": 0.45, "prob_empate": 0.27, "prob_visitante": 0.28}},
    }
    texto = analisis_completo._resumen_estadistico(resultado)
    assert "Visitante 45.0%" in texto and "odds 80%" in texto
    assert "Detalle Poisson" in texto
    assert texto.index("Probabilidad ponderada") < texto.index("Detalle Poisson")
    assert "Value" not in texto


def test_resumen_estadistico_sin_consenso_dice_no_disponible():
    assert analisis_completo._resumen_estadistico({"consenso": {"total_modulos": 0}, "modulos": {}}) == "Motor estadístico no disponible."
