"""test_gateway.py — cascada de fixtures (fuente 'bd' vía SQLAlchemy) y fallback a 'none'
cuando no hay caché ni API keys configuradas (comportamiento real esperado en dev sin .env)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.db import partidos_repo
from backend.api.models.partidos import PartidoDia
from backend.api.services import gateway


def test_yyyymmdd_to_bd():
    assert gateway._yyyymmdd_to_bd("20260601") == "2026-06-01"


def test_guardar_stage_persiste_badge_de_competicion_como_logo_de_liga(db_session):
    gateway.guardar_stages_en_cache(db_session, "20260601", [{
        "Snm": "Premier League", "badgeUrl": "premier-league.png",
        "Events": [{"Eid": "m-logo", "T1": [{"Nm": "Arsenal"}], "T2": [{"Nm": "Chelsea"}], "Esd": "202606011200"}],
    }], "livescore6")

    fila = db_session.get(PartidoDia, ("2026-06-01", "m-logo"))
    assert fila is not None
    assert fila.liga_logo == "https://lsm-static-prod.livescore.com/premier-league.png"


def test_bd_stages_hit(db_session):
    partidos_repo.guardar_ligas_cache(
        db_session,
        "2026-06-01",
        [{"match_id": "m1", "liga_slug": "premier-league", "liga_nombre": "Premier League",
          "local": "Arsenal", "visitante": "Chelsea", "hora_chile": "12:00",
          "kick_off_utc": "2026-06-01T16:00:00"}],
    )

    stages = gateway._bd_stages(db_session, "20260601")

    assert stages is not None
    assert stages[0]["Snm"] == "Premier League"
    assert stages[0]["Events"][0]["T1"][0]["Nm"] == "Arsenal"


def test_bd_stages_miss_sin_cache(db_session):
    assert gateway._bd_stages(db_session, "20991231") is None


def test_cascada_sin_api_keys_ni_cache_devuelve_none(db_session):
    """Sin BD, sin LIVESCORE6_KEY/BSD_API_KEY/SPORTS_API_KEY configuradas (default de
    Settings en test) — la cascada debe agotar las 4 fuentes y devolver ([], 'none'), no
    lanzar una excepción sin manejar."""

    async def _run():
        async with httpx.AsyncClient() as client:
            return await gateway.obtener_fixtures_cascada(db_session, client, "20991231")

    stages, fuente = asyncio.run(_run())

    assert stages == []
    assert fuente == "none"


def test_buscar_fixture_id_matchea_por_nombre_y_cachea(db_session):
    """Usa `"20260601"` (YYYYMMDD, el formato REAL que pasan los 2 callers reales —
    `analisis_completo.py`/`laplace_agents/seleccion.py`, confirmado con grep) — no
    `"2026-06-01"` como tenía este test antes. Bug real encontrado 2026-09-10: con fecha ya
    con guiones, este test nunca hubiera detectado que la función le mandaba a api-football el
    formato crudo (`YYYYMMDD`) en vez de `Y-m-d`, porque el mock no valida el query param real.
    Ahora sí lo valida (ver `test_buscar_fixture_id_convierte_fecha_a_formato_apifootball`)."""
    original = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "fake-key"
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "response": [
                        {
                            "fixture": {"id": 999},
                            "league": {"id": 39, "season": 2026},
                            "teams": {"home": {"id": 1, "name": "Arsenal"}, "away": {"id": 2, "name": "Chelsea"}},
                        }
                    ]
                },
            )

        async def _run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await gateway.buscar_fixture_id(db_session, client, "m1", "Arsenal", "Chelsea", "20260601")

        resultado = asyncio.run(_run())

        assert resultado["apifootball_fixture_id"] == 999
        assert resultado["apifootball_league_id"] == 39

        # Segunda llamada debe pegar en caché (no importa que el handler siga disponible)
        async def _run2():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await gateway.buscar_fixture_id(db_session, client, "m1", "Arsenal", "Chelsea", "20260601")

        resultado_cache = asyncio.run(_run2())
        # El valor cacheado vuelve a leerse como texto (columna Text en fixture_id_cache) —
        # es el mismo id, solo cambia el tipo Python del round-trip por SQLAlchemy.
        assert str(resultado_cache["apifootball_fixture_id"]) == "999"
    finally:
        settings.SPORTS_API_KEY = original


def test_buscar_fixture_id_convierte_fecha_a_formato_apifootball(db_session):
    """Regresión directa del bug real 2026-09-10: `buscar_fixture_id` recibía `fecha_raw` en
    formato `YYYYMMDD` (LiveScore6) pero mandaba ese mismo valor crudo a api-football, que
    exige `Y-m-d` — la API respondía HTTP 200 con `response: []` (nunca un error), así que
    NINGÚN partido matcheaba nunca, en toda la historia del proyecto (`fixture_id_cache` con 0
    filas reales, confirmado). Este test inspecciona el query param REAL que llega a la API."""
    original = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "fake-key"
    fecha_recibida = {}

    def handler(request: httpx.Request) -> httpx.Response:
        fecha_recibida["date"] = dict(request.url.params)["date"]
        return httpx.Response(200, json={"response": []})

    try:
        async def _run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await gateway.buscar_fixture_id(db_session, client, "m2", "River", "Boca", "20260601")

        asyncio.run(_run())

        assert fecha_recibida["date"] == "2026-06-01", (
            f"api-football recibió '{fecha_recibida['date']}' — debe ser 'Y-m-d', no el "
            "formato crudo YYYYMMDD (esto es exactamente el bug real que causaba 0 matches)"
        )
    finally:
        settings.SPORTS_API_KEY = original


def test_segunda_consulta_secuencial_del_mismo_dia_responde_100_por_ciento_desde_bd(db_session):
    """Piece 1 del pedido (caché de fixtures con timestamp explícito de consulta + hora de
    partido + día): a diferencia del test de single-flight (2 requests CONCURRENTES por el
    mismo lock), acá son 2 llamadas SECUENCIALES e independientes — la primera ya terminó y
    soltó el lock antes de que arranque la segunda. La segunda consulta al mismo día/partido
    debe responder 100% desde BD, sin ninguna llamada de red adicional, usando los campos
    reales que `partidos_dia` ya tiene (`creado_en` = timestamp del fetch real, `kick_off_utc`
    = hora real del partido, `fecha` = día) — no hizo falta agregar columnas nuevas."""
    original = settings.LIVESCORE6_KEY
    settings.LIVESCORE6_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(
            200,
            json={
                "Stages": [
                    {
                        "Snm": "Premier League",
                        "Events": [
                            {
                                "Eid": "m1", "Eps": "NS",
                                "T1": [{"Nm": "Arsenal", "Img": ""}],
                                "T2": [{"Nm": "Chelsea", "Img": ""}],
                                "Esd": "202606011200",
                                "kick_off_utc": "2026-06-01T16:00:00",
                            }
                        ],
                    }
                ]
            },
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            r1 = await gateway.obtener_fixtures_cascada(db_session, client, "20260601")
            r2 = await gateway.obtener_fixtures_cascada(db_session, client, "20260601")
            return r1, r2

    try:
        (stages_1, fuente_1), (stages_2, fuente_2) = asyncio.run(_run())
    finally:
        settings.LIVESCORE6_KEY = original

    assert llamadas["n"] == 1, f"la 2da consulta del mismo dia debio responder 100% desde BD, hubo {llamadas['n']} llamadas de red"
    assert fuente_1 == "livescore6"
    assert fuente_2 == "bd"

    fila = db_session.get(PartidoDia, ("2026-06-01", "m1"))
    assert fila is not None
    assert fila.creado_en, "consultado_en (creado_en) debe quedar registrado tras el fetch real"
    assert fila.kick_off_utc == "2026-06-01T16:00:00", "hora real del partido debe quedar guardada"
    assert fila.fecha == "2026-06-01"


def test_bsd_buscar_event_id_cachea_no_repite_busqueda_de_red(db_session):
    """Punto 4 de la auditoría 2026-09-09: a diferencia de `buscar_fixture_id` (que sí
    cacheaba vía `fixture_cache_repo`), `_bsd_buscar_event_id` repetía la búsqueda completa
    en BSD en cada llamada. Acá la 2da resolución del MISMO partido (mismo local/visitante/
    fecha) debe pegar en caché — 0 llamadas de red adicionales."""
    original = settings.BSD_API_KEY
    settings.BSD_API_KEY = "fake-key"
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(
            200,
            json={"results": [{"id": 555, "home_team": {"name": "Arsenal"}, "away_team": {"name": "Chelsea"}}]},
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            e1 = await gateway._bsd_buscar_event_id(db_session, client, "Arsenal", "Chelsea", "2026-06-01")
            e2 = await gateway._bsd_buscar_event_id(db_session, client, "Arsenal", "Chelsea", "2026-06-01")
            return e1, e2

    try:
        event_id_1, event_id_2 = asyncio.run(_run())
    finally:
        settings.BSD_API_KEY = original

    assert event_id_1 == 555
    assert event_id_2 == 555
    assert llamadas["n"] == 1, f"la 2da resolución debió pegar en caché, se hicieron {llamadas['n']} llamadas de red"


def test_enriquecer_bsd_reusa_event_id_cacheado_entre_llamadas(db_session):
    """Mismo punto 4, a nivel de `enriquecer_bsd` completo (lo que llamaría motor.py):
    2 análisis del mismo partido no deben repetir la BÚSQUEDA de event_id — sí es esperable
    que repitan los 2 GET de detalle/odds (`/events/{id}/`, `/events/{id}/odds/`), que no son
    parte de este hallazgo (cachear esos también cambiaría cuán fresco es el xG/odds de BSD,
    fuera de alcance de este punto)."""
    original = settings.BSD_API_KEY
    settings.BSD_API_KEY = "fake-key"
    llamadas_busqueda = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/events/555/" in url:
            if url.endswith("/odds/"):
                return httpx.Response(200, json={"odds": {"home_win": 1.8, "draw": 3.6, "away_win": 4.2}})
            return httpx.Response(200, json={"xg_home": 1.4, "xg_away": 1.1})
        llamadas_busqueda["n"] += 1
        return httpx.Response(
            200,
            json={"results": [{"id": 555, "home_team": {"name": "Arsenal"}, "away_team": {"name": "Chelsea"}}]},
        )

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            r1 = await gateway.enriquecer_bsd(db_session, client, "Arsenal", "Chelsea", "2026-06-01")
            r2 = await gateway.enriquecer_bsd(db_session, client, "Arsenal", "Chelsea", "2026-06-01")
            return r1, r2

    try:
        resultado_1, resultado_2 = asyncio.run(_run())
    finally:
        settings.BSD_API_KEY = original

    assert resultado_1["found"] is True
    assert resultado_2["found"] is True
    assert resultado_1["event_id"] == 555
    assert resultado_2["event_id"] == 555
    assert llamadas_busqueda["n"] == 1, (
        f"la búsqueda de event_id debió cachearse tras el 1er enriquecer_bsd, se buscó {llamadas_busqueda['n']} veces"
    )


def test_cascada_single_flight_no_duplica_llamadas_de_red_concurrentes(db_session):
    """Race condition real (auditoría 2026-09-09): sin lock, 2 requests casi simultáneas
    para la misma fecha sin caché disparaban la cascada de red completa cada una. Con el
    lock por fecha, la segunda debe esperar a que la primera termine de escribir en caché
    y leer eso — el fetch de red (mockeado acá) debe llamarse UNA sola vez, no dos."""
    original_livescore = settings.LIVESCORE6_KEY
    settings.LIVESCORE6_KEY = "fake-key"
    llamadas = {"n": 0}

    async def _run():
        primera_entro = asyncio.Event()
        segunda_puede_arrancar = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            llamadas["n"] += 1
            # La primera corutina en llegar acá avisa y espera a que la segunda ya haya
            # intentado pedir la misma fecha (y por lo tanto haya quedado bloqueada en el
            # lock) antes de "terminar" su propio fetch — así se fuerza la superposición
            # real que dispara la race condition si el lock no existiera.
            if llamadas["n"] == 1:
                primera_entro.set()
                await asyncio.wait_for(segunda_puede_arrancar.wait(), timeout=2)
            return httpx.Response(
                200,
                json={
                    "Stages": [
                        {
                            "Snm": "Premier League",
                            "Events": [
                                {
                                    "Eid": "m1",
                                    "Eps": "NS",
                                    "T1": [{"Nm": "Arsenal", "Img": ""}],
                                    "T2": [{"Nm": "Chelsea", "Img": ""}],
                                    "Esd": "202606011200",
                                    "kick_off_utc": "2026-06-01T16:00:00",
                                }
                            ],
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

            async def _segunda_llamada_diferida():
                # Arranca solo después de que la primera ya entró al handler (y por lo
                # tanto ya tomó el lock de la fecha) — simula la segunda request llegando
                # mientras la primera sigue en la cascada de red.
                await asyncio.wait_for(primera_entro.wait(), timeout=2)
                segunda_puede_arrancar.set()
                return await gateway.obtener_fixtures_cascada(db_session, client, "20260601")

            resultado_1, resultado_2 = await asyncio.gather(
                gateway.obtener_fixtures_cascada(db_session, client, "20260601"),
                _segunda_llamada_diferida(),
            )
            return resultado_1, resultado_2

    try:
        (stages_1, fuente_1), (stages_2, fuente_2) = asyncio.run(_run())
    finally:
        settings.LIVESCORE6_KEY = original_livescore

    assert llamadas["n"] == 1, f"la fuente de red debió llamarse 1 vez, se llamó {llamadas['n']}"
    assert fuente_1 == "livescore6"
    # La segunda corutina esperó el lock y encontró la caché ya poblada por la primera.
    assert fuente_2 == "bd"
    assert stages_1[0]["Events"][0]["T1"][0]["Nm"] == "Arsenal"
    assert stages_2[0]["Events"][0]["T1"][0]["Nm"] == "Arsenal"


def test_buscar_fixture_id_pide_una_sola_vez_los_partidos_del_dia_y_detecta_cuota_agotada(db_session):
    """Auditoría 2026-10-09: cada análisis repetía `fixtures?date=` (100/día y 10/min en el plan gratis → 429).
    Ahora los partidos del día se piden una vez y se reutilizan; un HTTP 200 con `errors` no se lee como 'sin partidos'."""
    original = settings.SPORTS_API_KEY
    settings.SPORTS_API_KEY = "fake-key"
    llamadas = {"n": 0}
    partido = {"fixture": {"id": 9}, "league": {"id": 128, "season": 2026},
               "teams": {"home": {"id": 1, "name": "River Plate"}, "away": {"id": 2, "name": "Boca Juniors"}}}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        assert dict(request.url.params)["timezone"] == "America/Santiago"
        return httpx.Response(200, json={"errors": [], "response": [partido]})

    try:
        async def _run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                a = await gateway.buscar_fixture_id(db_session, client, "m10", "River Plate", "Boca Juniors", "20261011")
                b = await gateway.buscar_fixture_id(db_session, client, "m11", "Otro", "Equipo", "20261011")
                return a, b

        a, b = asyncio.run(_run())
        assert a["apifootball_league_id"] == 128 and b["apifootball_league_id"] is None
        assert llamadas["n"] == 1, "el segundo partido del mismo día no debe volver a pedir todo el día"

        gateway._fixtures_apif_dia.clear()

        def sin_cuota(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errors": {"requests": "You have reached the request limit for the day"}, "response": []})

        async def _run_sin_cuota():
            async with httpx.AsyncClient(transport=httpx.MockTransport(sin_cuota)) as client:
                with pytest.raises(gateway.CuotaApiFootballError):
                    await gateway._fixtures_apifootball_del_dia(client, "2026-10-12")

        asyncio.run(_run_sin_cuota())
        assert "2026-10-12" not in gateway._fixtures_apif_dia, "un error de cuota no se cachea como 'día vacío'"
    finally:
        settings.SPORTS_API_KEY = original
