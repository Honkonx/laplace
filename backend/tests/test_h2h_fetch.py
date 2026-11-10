"""test_h2h_fetch.py — ponderación por antigüedad (media vida 180 días) y fallback sin
historial (goles estimados desde el promedio de liga)."""
from __future__ import annotations

import asyncio

import httpx

from backend.api.core.config import settings
from backend.api.services import h2h_fetch


def test_sin_h2h_usa_promedio_liga():
    resultado = h2h_fetch._sin_h2h("Real Madrid", "Betis", "La Liga", 2.6)

    assert resultado["h2h_disponible"] is False
    assert resultado["h2h_total"] == 0
    # LIGA_AVG["la liga"] = 2.52 -> local 1.26, visitante 1.13
    assert resultado["goles_local_avg"] == 1.26
    assert resultado["goles_visit_avg"] == round(1.26 * 0.9, 2)


def test_ponderar_y_resumir_partido_reciente_pesa_mas():
    from datetime import datetime, timedelta, timezone

    reciente = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    antiguo = (datetime.now(timezone.utc) - timedelta(days=900)).isoformat()

    partidos = [
        {"fecha_iso": reciente, "local": "River", "visitante": "Boca", "goles_local": 3, "goles_visitante": 0},
        {"fecha_iso": antiguo, "local": "River", "visitante": "Boca", "goles_local": 0, "goles_visitante": 0},
    ]

    resultado = h2h_fetch._ponderar_y_resumir(partidos)

    assert resultado["h2h_disponible"] is True
    assert resultado["h2h_total"] == 2
    assert resultado["h2h_local_wins"] == 1
    assert resultado["h2h_empates"] == 1
    # El partido reciente (peso ~1.0) domina el promedio ponderado sobre el de hace 900 días
    # (peso ~exp(-900/180)=exp(-5)≈0.0067) -> goles_local_avg debe quedar cerca de 3, no de 1.5
    assert resultado["goles_local_avg"] > 2.5


def test_dias_desde_fecha_vacia_devuelve_default_alto():
    assert h2h_fetch._dias_desde("") == h2h_fetch.MEDIA_VIDA_DIAS * 2


def test_bsd_h2h_no_revienta_si_home_team_es_string_plano(monkeypatch):
    """Regresión del bug real de producción (2026-09-05): BSD devolvió `home_team` como
    string plano en vez de `{"name": ...}` y tumbaba TODO el análisis
    (`AttributeError: 'str' object has no attribute 'get'`, confirmado en el log real)."""
    monkeypatch.setattr(settings, "BSD_API_KEY", "fake")

    async def _fake_get(self, url, **kw):
        return httpx.Response(200, request=httpx.Request("GET", url), json={"results": [
            {"home_team": "River Plate", "away_team": {"name": "Boca Juniors"},
             "start_time": "2026-01-01T00:00:00Z", "home_score": 2, "away_score": 1},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch._bsd_h2h(client, "River Plate", "Boca Juniors")

    resultado = asyncio.run(_run())
    assert resultado is not None
    assert resultado[0]["local"] == "River Plate"
    assert resultado[0]["visitante"] == "Boca Juniors"


# ─── Segundo fallback: stats reales de temporada por equipo (2026-09-09) ────────────────────
# Hallazgo real (auditoría de uniformidad de predicciones, ver el registro de decisiones del proyecto): sin
# historial H2H entre los 2 equipos específicos (el caso más común — la mayoría de los pares de
# equipos nunca jugaron entre sí), el sistema caía DIRECTO al promedio genérico de liga —
# produciendo la MISMA predicción para cualquier partido de la misma liga (o del mismo default,
# para ligas desconocidas). Ahora intenta primero el promedio real de temporada de cada equipo.


def test_desde_stats_equipo_usa_datos_reales_de_cada_equipo(monkeypatch):
    from backend.api.services import team_stats_fetch

    async def _fake_stats(client, db, team_id, league_id, season):
        # Datos reales DISTINTOS por equipo — a diferencia de _sin_h2h, que da el mismo valor
        # a cualquier par de equipos de la misma liga.
        if team_id == 100:
            return {"goals": {"for": {"average": {"total": "2.10"}}, "against": {"average": {"total": "0.80"}}}}
        return {"goals": {"for": {"average": {"total": "1.20"}}, "against": {"average": {"total": "1.50"}}}}

    monkeypatch.setattr(team_stats_fetch, "enriquecer_stats_equipo", _fake_stats)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch._desde_stats_equipo(client, None, 100, 200, league_id=39, season=2026)

    resultado = asyncio.run(_run())

    assert resultado is not None
    assert resultado["fuente_goles"] == "stats_equipo_real"
    assert resultado["h2h_disponible"] is False  # no es head-to-head real, es stats por equipo
    assert resultado["goles_local_avg"] == 2.10
    assert resultado["goles_visit_avg"] == 1.20
    assert resultado["goles_contra_local_avg"] == 0.80
    assert resultado["goles_contra_visit_avg"] == 1.50


def test_desde_stats_equipo_sin_ids_devuelve_none():
    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch._desde_stats_equipo(client, None, None, None, league_id=None, season=None)

    assert asyncio.run(_run()) is None


def test_desde_stats_equipo_si_falta_un_equipo_devuelve_none(monkeypatch):
    """Si SOLO un equipo tiene stats reales, no se mezcla con un genérico — se cae al
    fallback totalmente genérico en vez de un híbrido sesgado."""
    from backend.api.services import team_stats_fetch

    async def _fake_stats(client, db, team_id, league_id, season):
        if team_id == 100:
            return {"goals": {"for": {"average": {"total": "2.10"}}, "against": {"average": {"total": "0.80"}}}}
        return None

    monkeypatch.setattr(team_stats_fetch, "enriquecer_stats_equipo", _fake_stats)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch._desde_stats_equipo(client, None, 100, 200, league_id=39, season=2026)

    assert asyncio.run(_run()) is None


def test_obtener_h2h_sin_historial_pero_con_stats_equipo_usa_stats_no_generico(monkeypatch):
    """Regresión end-to-end del hallazgo real: dos equipos sin historial H2H entre sí, pero
    CON stats de temporada reales — antes de este fix, `obtener_h2h` hubiera devuelto el
    promedio genérico de liga (mismo resultado para cualquier partido); ahora usa datos reales
    del equipo."""
    from backend.api.services import team_stats_fetch

    async def _sin_apif(client, db, a, b):
        return None

    async def _sin_bsd(client, local, visitante):
        return None

    async def _fake_stats(client, db, team_id, league_id, season):
        if team_id == 100:
            return {"goals": {"for": {"average": {"total": "2.10"}}, "against": {"average": {"total": "0.80"}}}}
        return {"goals": {"for": {"average": {"total": "1.20"}}, "against": {"average": {"total": "1.50"}}}}

    monkeypatch.setattr(h2h_fetch, "_apifootball_h2h", _sin_apif)
    monkeypatch.setattr(h2h_fetch, "_bsd_h2h", _sin_bsd)
    monkeypatch.setattr(team_stats_fetch, "enriquecer_stats_equipo", _fake_stats)

    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch.obtener_h2h(
                client, None, 100, 200, "Equipo A", "Equipo B", "Liga Desconocida XYZ", 2.6,
                league_id=39, season=2026,
            )

    resultado = asyncio.run(_run())
    assert resultado["fuente_goles"] == "stats_equipo_real"
    assert resultado["goles_local_avg"] == 2.10  # NO el promedio genérico de liga (1.3)


def test_obtener_h2h_sin_nada_real_cae_al_generico_como_antes():
    """Sin H2H, sin league_id/season (o sin datos reales de equipo tampoco) — sigue cayendo al
    fallback genérico de siempre, mismo comportamiento que antes de este cambio."""
    async def _run():
        async with httpx.AsyncClient() as client:
            return await h2h_fetch.obtener_h2h(
                client, None, None, None, "Equipo A", "Equipo B", "Liga Desconocida XYZ", 2.6,
            )

    resultado = asyncio.run(_run())
    assert resultado["fuente_goles"] == "liga_generico"


def test_ponderar_y_resumir_orienta_los_cruces_al_local_actual_y_usa_defensa_neutra():
    """Hoy juega River de local; el cruce histórico fue Boca 3-0 River (localía invertida): para
    River son 0 goles a favor y 3 en contra, y la victoria cuenta como del VISITANTE actual."""
    from datetime import datetime, timezone

    reciente = datetime.now(timezone.utc).isoformat()
    partidos = [{"fecha_iso": reciente, "local": "Boca Juniors", "visitante": "River Plate",
                 "goles_local": 3, "goles_visitante": 0}]
    sin_orientar = h2h_fetch._ponderar_y_resumir(partidos)
    orientado = h2h_fetch._ponderar_y_resumir(partidos, "River Plate", "Boca Juniors", 1.2)

    assert sin_orientar["h2h_local_wins"] == 1  # comportamiento anterior (compatibilidad)
    assert orientado["h2h_local_wins"] == 0 and orientado["h2h_visit_wins"] == 1
    assert orientado["goles_local_avg"] == 0.0 and orientado["goles_visit_avg"] == 3.0
    assert orientado["goles_contra_local_avg"] == 1.2 and orientado["goles_contra_visit_avg"] == 1.2


def test_orientacion_no_confunde_equipos_de_nombre_parecido():
    partidos = [{"fecha_iso": "2026-01-01T00:00:00Z", "local": "Manchester City", "visitante": "Arsenal",
                 "goles_local": 2, "goles_visitante": 1}]
    r = h2h_fetch._ponderar_y_resumir(partidos, "Manchester United", "Arsenal", 1.3)
    assert r["h2h_local_wins"] == 1  # City != United: no se invierte


def test_obtener_h2h_con_un_solo_cruce_prefiere_las_stats_de_temporada(monkeypatch):
    """Auditoría 2026-10-09: con 1-2 cruces el H2H cortaba el flujo sin probar las estadísticas de cada equipo, y esos
    cruces no alcanzan para contar como fuente (mínimo 3). Ahora cae a las stats; sin ellas, conserva el H2H corto."""
    from backend.api.services import team_stats_fetch

    cruce = [{"fecha": "2025-01-01", "goles_local": 1, "goles_visitante": 0, "local": "Equipo A", "visitante": "Equipo B"}]

    async def _un_cruce(client, db, a, b):
        return cruce

    async def _sin_bsd(client, local, visitante):
        return None

    async def _fake_stats(client, db, team_id, league_id, season):
        return {"goals": {"for": {"average": {"total": "1.80"}}, "against": {"average": {"total": "0.90"}}}}

    async def _sin_stats(client, db, team_id, league_id, season):
        return None

    monkeypatch.setattr(h2h_fetch, "_apifootball_h2h", _un_cruce)
    monkeypatch.setattr(h2h_fetch, "_bsd_h2h", _sin_bsd)
    llamadas = []
    monkeypatch.setattr(h2h_fetch, "_ponderar_y_resumir", lambda partidos, *a, **k: llamadas.append(len(partidos)) or {"fuente_goles": "h2h_real", "h2h_total": len(partidos)})

    async def _run(stats):
        monkeypatch.setattr(team_stats_fetch, "enriquecer_stats_equipo", stats)
        async with httpx.AsyncClient() as client:
            return await h2h_fetch.obtener_h2h(client, None, 100, 200, "Equipo A", "Equipo B", "Liga X", 2.6, league_id=39, season=2026)

    assert asyncio.run(_run(_fake_stats))["fuente_goles"] == "stats_equipo_real"
    assert llamadas == []
    assert asyncio.run(_run(_sin_stats))["fuente_goles"] == "h2h_real"  # sin stats se conserva el cruce corto
    assert llamadas == [1]
