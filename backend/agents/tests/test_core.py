"""test_core.py — el sistema se auto-evalúa: analiza y persiste partidos de ligas conocidas
por su cuenta, sin depender de que un usuario real pida un análisis.

Reubicado 2026-09-10 desde `tests/test_laplace_agents.py` (ver `laplace_agents/core.py`
para el porqué de la reubicación completa de este paquete).

Hallazgo real que motiva esto (2026-09-09, ver el registro de decisiones del proyecto): antes de este módulo,
`analisis_comparativo` solo se poblaba cuando un usuario real disparaba `procesar_job` — el
verificador de resultados solo verifica lo que ya está ahí, así que la calibración dependía
100% del tráfico de usuarios. Estos tests confirman que `ejecutar_ciclo_autoevaluacion` llena
esa tabla por su cuenta, usando el MISMO motor real que un request de usuario."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from backend.api.db import analisis_repo
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services import analisis_completo
from laplace_agents import core as laplace_agents_core


def _resultado_motor_fake(local="River Plate", visitante="Boca Juniors"):
    return {
        "local": local, "visitante": visitante, "liga": "Liga Profesional",
        "modulos": {
            "poisson": {"ok": True, "pick": "Local", "prob_local": 0.55, "prob_empate": 0.25,
                        "prob_visitante": 0.20, "over25_prob": 0.5, "btts_prob": 0.4,
                        "confianza_score": 70, "confianza": "ALTA", "marcador_probable": "2-1",
                        "value_bet": False, "value_pct": 0},
        },
        "modulos_skip": {},
        "consenso": {"pick_final": "Local", "nivel": "MODERADO", "score_consenso": 65,
                     "confianza_final": "MEDIA", "total_modulos": 1},
    }


@pytest.fixture()
def mocks_2_partidos(monkeypatch):
    """2 partidos reales en ligas conocidas ("Liga Profesional" matchea "liga profesional" en
    `services/ligas.py::LIGAS`) el mismo día."""
    async def _fixtures_cascada(db, client, fecha):
        return [{"Snm": "Liga Profesional", "Events": [
            {"Eid": "501", "Eps": "NS", "T1": [{"Nm": "River Plate"}], "T2": [{"Nm": "Boca Juniors"}]},
            {"Eid": "502", "Eps": "NS", "T1": [{"Nm": "Racing"}], "T2": [{"Nm": "Independiente"}]},
        ]}], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        # Cuotas reales (una de las 2 fuentes que exige la puerta de calidad de
        # `analisis_completo._enriquecer_partido` para persistir un análisis).
        return {"odds_local": 2.1, "odds_empate": 3.3, "odds_visit": 3.5, "odds_disponibles": True, "odds_source": "test"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        # H2H real con 5 partidos = segunda fuente que exige la puerta de calidad (2026-09-27).
        return {"h2h_disponible": True, "h2h_local_wins": 2, "h2h_visit_wins": 2, "h2h_empates": 1,
                "h2h_total": 5, "h2h_resumen": "5 partidos de historial directo.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3, "fuente_goles": "liga_generico"}

    async def _bsd(client, local, visitante, fecha):
        return None

    def _motor_analizar(d):
        return _resultado_motor_fake(d["local"], d["visitante"])

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd)
    monkeypatch.setattr(analisis_completo.motor, "analizar_partido", _motor_analizar)


def _run(coro):
    return asyncio.run(coro)


def test_ejecutar_ciclo_analiza_y_persiste_partidos_de_liga_conocida(db_session, mocks_2_partidos):
    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert resumen["candidatos_liga_conocida"] == 2
    assert resumen["analizados"] == 2
    assert resumen["errores"] == 0
    filas = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id.in_(["501", "502"])).all()
    assert len(filas) == 2
    assert all(f.pick_final for f in filas)


def test_ejecutar_ciclo_no_usa_ia_por_default(db_session, mocks_2_partidos, monkeypatch):
    """La auto-evaluación es para calibración/pre-caché, no gasta cuota de IA en partidos que
    nadie pidió — confirma que el proveedor de IA nunca se llama."""
    llamado = {"n": 0}

    async def _ia_que_no_deberia_llamarse(prompt, max_tokens=1024):
        llamado["n"] += 1
        return "no debería llegar acá"

    monkeypatch.setattr(analisis_completo, "generar_texto_ia", _ia_que_no_deberia_llamarse)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    _run(_go())
    assert llamado["n"] == 0


def test_ejecutar_ciclo_no_reanaliza_partido_que_ya_existe(db_session, mocks_2_partidos):
    """Si un usuario real (o una corrida anterior de este mismo ciclo) ya generó la fila de
    `analisis_comparativo` para un partido de hoy, la auto-evaluación no lo vuelve a analizar —
    ni gasta cálculo/red de nuevo, ni duplica la fila."""
    analisis_repo.guardar_comparativo(
        db_session, partido_id="501", local="River Plate", visitante="Boca Juniors",
        liga="Liga Profesional", pick_final="Local", pick_python="Local",
    )

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert resumen["candidatos_liga_conocida"] == 2
    assert resumen["ya_existian"] == 1
    assert resumen["analizados"] == 1  # solo el 502, el 501 ya existía
    assert db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "501").count() == 1


def test_ejecutar_ciclo_ignora_ligas_desconocidas(db_session, monkeypatch):
    async def _fixtures_cascada(db, client, fecha):
        return [{"Snm": "Liga Completamente Inventada FC", "Events": [
            {"Eid": "999", "Eps": "NS", "T1": [{"Nm": "A"}], "T2": [{"Nm": "B"}]},
        ]}], "test"

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert resumen["candidatos_liga_conocida"] == 0
    assert resumen["analizados"] == 0
    assert db_session.query(AnalisisComparativo).count() == 0


def test_ejecutar_ciclo_un_partido_que_falla_no_frena_el_resto(db_session, mocks_2_partidos, monkeypatch):
    original = analisis_completo.analizar_y_persistir

    async def _falla_el_501(db, client, *, match_id, local, visitante, liga, fecha, con_ia, usuario_id=""):
        if match_id == "501":
            raise RuntimeError("fallo simulado")
        return await original(db, client, match_id=match_id, local=local, visitante=visitante, liga=liga, fecha=fecha, con_ia=con_ia, usuario_id=usuario_id)

    monkeypatch.setattr(laplace_agents_core.analisis_completo, "analizar_y_persistir", _falla_el_501)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert resumen["analizados"] == 1
    assert resumen["errores"] == 1
    assert db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "502").count() == 1
    assert db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "501").count() == 0


# ─── roadmap 2026-09-10: riqueza de datos + detector de uniformidad + hoy/mañana ──────────────


def test_ejecutar_ciclo_agrega_detalle_con_pick_final_y_fuente_goles_y_resumen_uniformidad(db_session, mocks_2_partidos):
    """`detalle` (para cada partido analizado) y el resumen de `consistencia.detectar_
    uniformidad` quedan disponibles en el resultado real de `ejecutar_ciclo_autoevaluacion` —
    no solo en los módulos aislados (ya cubiertos por `test_consistencia.py`)."""
    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert resumen["analizados"] == 2
    detalle_analizado = [d for d in resumen["detalle"] if d["estado"] == "analizado"]
    assert len(detalle_analizado) == 2
    assert all(d["pick_final"] == "Local" for d in detalle_analizado)  # ver _resultado_motor_fake
    assert all(d["fuente_goles"] == "liga_generico" for d in detalle_analizado)  # ver mock _h2h

    assert resumen["distribucion_picks"] == {"Local": 2}
    assert resumen["distribucion_fuente_goles"] == {"liga_generico": 2}
    # Con solo 2 partidos, por debajo de `MUESTRA_MINIMA_PARA_ALERTA` (5) — no debe alertar aunque
    # el 100% comparta pick, mismo criterio que `test_consistencia.py`.
    assert resumen["alerta_uniformidad"] is False


def test_ejecutar_ciclo_sin_fecha_procesa_hoy_y_manana(db_session, monkeypatch):
    """Sin `fecha` explícita (el uso real del cron diario) — corre `_ejecutar_un_dia` dos veces
    (hoy y mañana) y devuelve `{"hoy": ..., "mañana": ...}` distinguibles, más el agregado plano
    de siempre (`analizados`, `candidatos_liga_conocida`, etc. — compatibilidad con
    `backend/api/main.py::_job_laplace_agents` y `routers/scheduler.py::disparar_laplace_agents`,
    que leen esas claves en forma plana)."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    async def _fixtures_cascada(db, client, fecha_livescore):
        # `fecha_livescore` es YYYYMMDD (sin guiones) — un partido real por día, distinguible
        # por match_id para confirmar que cada rama (hoy/mañana) procesó SU propio fixture.
        if fecha_livescore == hoy.replace("-", ""):
            eid = "701"
        elif fecha_livescore == manana.replace("-", ""):
            eid = "702"
        else:
            eid = None
        if eid is None:
            return [], "test"
        return [{"Snm": "Liga Profesional", "Events": [
            {"Eid": eid, "Eps": "NS", "T1": [{"Nm": "River Plate"}], "T2": [{"Nm": "Boca Juniors"}]},
        ]}], "test"

    async def _buscar_fixture_id(db, client, match_id, local, visitante, fecha_bd):
        return {"apifootball_fixture_id": None, "apifootball_league_id": None,
                "apifootball_season": None, "apifootball_team_home": None, "apifootball_team_away": None}

    async def _standings(client, db, league_code, season):
        return None

    async def _odds(client, db, local, visitante, odds_key, fixture_id, fecha, kick_off_utc=None):
        # Cuotas reales (una de las 2 fuentes que exige la puerta de calidad de
        # `analisis_completo._enriquecer_partido` para persistir un análisis).
        return {"odds_local": 2.1, "odds_empate": 3.3, "odds_visit": 3.5, "odds_disponibles": True, "odds_source": "test"}

    async def _h2h(client, db, team_home, team_away, local, visitante, liga, liga_avg_input=2.6, league_id=None, season=None):
        # H2H real con 5 partidos = segunda fuente que exige la puerta de calidad (2026-09-27).
        return {"h2h_disponible": True, "h2h_local_wins": 2, "h2h_visit_wins": 2, "h2h_empates": 1,
                "h2h_total": 5, "h2h_resumen": "5 partidos de historial directo.",
                "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
                "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3, "fuente_goles": "liga_generico"}

    async def _bsd(client, local, visitante, fecha):
        return None

    def _motor_analizar(d):
        return _resultado_motor_fake(d["local"], d["visitante"])

    monkeypatch.setattr(analisis_completo.gateway, "obtener_fixtures_cascada", _fixtures_cascada)
    monkeypatch.setattr(analisis_completo.gateway, "buscar_fixture_id", _buscar_fixture_id)
    monkeypatch.setattr(analisis_completo.standings_fetch, "obtener_standings", _standings)
    monkeypatch.setattr(analisis_completo.odds_fetch, "obtener_odds_partido", _odds)
    monkeypatch.setattr(analisis_completo.h2h_fetch, "obtener_h2h", _h2h)
    monkeypatch.setattr(analisis_completo.bsd_predictions, "obtener_prediccion_externa_bsd", _bsd)
    monkeypatch.setattr(analisis_completo.motor, "analizar_partido", _motor_analizar)

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client)

    resumen = _run(_go())

    assert "hoy" in resumen and "mañana" in resumen
    assert resumen["hoy"]["fecha"] == hoy
    assert resumen["mañana"]["fecha"] == manana
    assert resumen["hoy"]["analizados"] == 1
    assert resumen["mañana"]["analizados"] == 1
    # Agregado plano — mismas claves que ya leen main.py/scheduler.py en forma no anidada.
    assert resumen["analizados"] == 2
    assert resumen["candidatos_liga_conocida"] == 2
    assert resumen["errores"] == 0
    assert len(resumen["detalle"]) == 2

    filas = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id.in_(["701", "702"])).all()
    assert len(filas) == 2


# ─── roadmap 2026-09-10: memoria propia + deriva entre corridas + votos de /encuesta ──────────


def test_ejecutar_ciclo_agrega_deriva_y_comparacion_de_votos_al_resumen(db_session, mocks_2_partidos):
    """Primera corrida real del agente: sin corrida anterior en memoria, `deriva` no alerta
    pero SÍ queda expuesta en el resumen — y `comparacion_usuarios_vs_motor` también, aunque
    esté vacía (nadie votó todavía en este test)."""
    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    assert "deriva" in resumen
    assert resumen["deriva"]["hay_corrida_anterior"] is False
    assert resumen["deriva"]["alerta_deriva"] is False
    assert "comparacion_usuarios_vs_motor" in resumen
    assert resumen["comparacion_usuarios_vs_motor"]["total_partidos_con_voto_y_resultado"] == 0


def test_ejecutar_ciclo_escribe_memoria_real_de_la_corrida(db_session, mocks_2_partidos):
    """Cada corrida deja una fila real en `laplace_agent_memoria` (tipo_evento='ciclo_diario')
    — es lo que le permite a la PRÓXIMA corrida comparar contra esta."""
    from laplace_agents import memoria as memoria_mod

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    resumen = _run(_go())

    ultimo = memoria_mod.leer_ultimo_evento(db_session, tipo_evento=laplace_agents_core.TIPO_EVENTO_CICLO_DIARIO)
    assert ultimo is not None
    assert ultimo["fecha"] == "2026-06-01"
    assert ultimo["resumen"]["distribucion_picks"] == resumen["distribucion_picks"]


def test_ejecutar_ciclo_dos_corridas_seguidas_la_segunda_compara_contra_la_primera(db_session, mocks_2_partidos):
    """Segunda corrida real (mismo día no importa acá, lo que importa es que ya hay memoria
    previa): `deriva.hay_corrida_anterior` pasa a True — con solo 2 partidos por corrida sigue
    sin alertar (por debajo de `MUESTRA_MINIMA_PARA_COMPARAR`), pero la comparación ya ocurre."""
    async def _go(fecha):
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha=fecha)

    _run(_go("2026-06-01"))
    # Segunda corrida: mismos 2 partidos ya existen (`ya_existian`), pero igual se escribe
    # memoria nueva con la distribución de ESTA corrida (0 analizados esta vez).
    resumen_2 = _run(_go("2026-06-01"))

    assert resumen_2["deriva"]["hay_corrida_anterior"] is True


def test_ejecutar_ciclo_incluye_partido_resuelto_con_votos_en_la_comparacion(db_session, mocks_2_partidos):
    """Fin a fin: un usuario vota, el partido queda resuelto (mismo patrón real de
    `services/resultados.py`), y la próxima corrida del agente expone la comparación."""
    from backend.api.db import predicciones_usuario_repo
    from backend.api.models.predicciones import AnalisisComparativo

    async def _go():
        async with httpx.AsyncClient() as client:
            return await laplace_agents_core.ejecutar_ciclo_autoevaluacion(db_session, client, fecha="2026-06-01")

    _run(_go())  # analiza y persiste los partidos 501/502 (ver mocks_2_partidos)

    fila = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "501").first()
    assert fila is not None
    fila.resultado_real = "2-1"
    fila.goles_local, fila.goles_visitante = 2, 1
    fila.pick_correcto = 1  # pick_final ya es "Local" (ver _resultado_motor_fake) — acertó
    db_session.commit()
    predicciones_usuario_repo.registrar_voto(db_session, "501", "userA", "local")

    resumen = _run(_go())

    comparacion = resumen["comparacion_usuarios_vs_motor"]
    assert comparacion["total_partidos_con_voto_y_resultado"] == 1
    assert comparacion["motor_winrate_pct"] == 100.0
    assert comparacion["usuarios_winrate_pct"] == 100.0
