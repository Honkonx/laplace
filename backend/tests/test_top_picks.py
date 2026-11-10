"""test_top_picks.py — lógica pura de WF-D (filtro de candidatos, consolidación de picks,
formateo del mensaje del canal, guarda de idempotencia de publicación). Los pasos que llaman a
api-football/Claude (scoring, fetch de stats) se prueban en `generar_top_picks_dia` vía
integración manual — acá se cubre lo que no requiere red, siguiendo el mismo criterio que
`test_gateway.py`.

Fix 2026-09-09 (bug real de consistencia entre pipelines): antes, el pick de cada candidato de
Top Picks salía de un voto ad-hoc a 3 vías (Poisson/Forma/IA) que ignoraba h2h/odds/tabla —
`test_consolidar_pick_usa_h2h_y_odds_igual_que_analisis_completo` es la verificación empírica
(regla `empirical-verification-before-fix.md`) de que el pick consolidado ahora SÍ coincide con
el que calcularía `services/motor.py` + `services/consenso.py` (el mismo motor que usa
`services/analisis_completo.py` para el bot/app) — no con un asumido "debería coincidir"."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from backend.api.services import motor, top_picks, top_picks_publicacion


def _fixture(fixture_id=1, league_id=39, hora_utc=15, home="River", away="Boca") -> dict:
    # nombre de liga "La Liga" (no "Premier League") a propósito: desde 2026-09-09
    # "Premier League" es una clave ambigua en el origen de datos y ya no matchea
    # `es_liga_conocida` (ver test_services_ligas.py) — se cambió el nombre del fixture
    # sintético, no el `league_id=39` (que sigue siendo el id real de LIGAS_PREMIUM usado
    # por estos tests para la lógica de score_liga, sin relación con el nombre de texto).
    return {
        "fixture": {"id": fixture_id, "timestamp": None, "status": {"short": "NS"}},
        "league": {"id": league_id, "name": "La Liga", "logo": ""},
        "teams": {"home": {"id": 10, "name": home, "logo": ""}, "away": {"id": 20, "name": away, "logo": ""}},
        "goals": {"home": None, "away": None},
    }


def test_filtrar_candidatos_descarta_liga_no_prioritaria():
    fixtures = [_fixture(league_id=99999)]
    # sin timestamp -> se descarta también por falta de hora; probamos liga primero con hora válida
    fixtures[0]["fixture"]["timestamp"] = 1780000000
    candidatos = top_picks._filtrar_candidatos(fixtures, "20260601", "01/06/2026")
    assert candidatos == []


def test_filtrar_candidatos_descarta_partido_que_ya_inicio_o_termino():
    import datetime as dt
    ts = int(dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp())
    fixture = _fixture(league_id=39)
    fixture["fixture"]["timestamp"] = ts
    fixture["fixture"]["status"]["short"] = "FT"
    assert top_picks._filtrar_candidatos([fixture], "20261001", "01/10/2026") == []


def test_filtrar_candidatos_acepta_liga_premium_con_hora_valida():
    import datetime as dt
    # timestamp correspondiente a las 12:00 UTC -> 08:00 Chile (UTC-4), dentro del rango >=7
    ts = int(dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp())
    fixtures = [_fixture(league_id=39, hora_utc=ts)]
    fixtures[0]["fixture"]["timestamp"] = ts
    candidatos = top_picks._filtrar_candidatos(fixtures, "20260601", "01/06/2026")
    assert len(candidatos) == 1
    assert candidatos[0]["score_liga"] == 2  # premium


def test_estadisticas_desde_prediccion_son_datos_y_no_un_pick_externo():
    prediccion = {"teams": {"home": {"league": {"form": "WDWWL", "goals": {
        "for": {"average": {"total": "1.4"}}, "against": {"average": {"total": "0.8"}},
    }}}}}
    assert top_picks._estadisticas_desde_prediccion(prediccion, "home") == (1.4, 0.8, 3, "WDWWL")


def test_filtrar_candidatos_excluye_antes_de_las_7am_chile():
    import datetime as dt
    ts = int(dt.datetime(2026, 6, 1, 8, 0, tzinfo=dt.timezone.utc).timestamp())  # 04:00 Chile (UTC-4)
    fixtures = [_fixture(league_id=39)]
    fixtures[0]["fixture"]["timestamp"] = ts
    assert top_picks._filtrar_candidatos(fixtures, "20260601", "01/06/2026") == []


def test_filtrar_candidatos_acepta_liga_curada_por_id_aunque_nombre_no_sea_confiable():
    """Filtro de calidad agregado 2026-09-08: aunque `league_id` esté en `LIGAS_OK`, si el
    NOMBRE de la liga no matchea ninguna entrada de `services/ligas.py::LIGAS` (ni promedio de
    gol, ni tabla, ni odds), el candidato se descarta antes de gastar cálculo/IA en él — caso
    objetivo de desalineación entre el id curado a mano y el nombre real que trae la fuente."""
    import datetime as dt
    ts = int(dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp())
    fixtures = [_fixture(league_id=39)]  # 39 = Premier League, está en LIGAS_OK
    fixtures[0]["fixture"]["timestamp"] = ts
    fixtures[0]["league"]["name"] = "Liga Completamente Desconocida XYZ"
    candidatos = top_picks._filtrar_candidatos(fixtures, "20260601", "01/06/2026")
    assert len(candidatos) == 1
    assert candidatos[0]["league_id"] == 39


def test_filtrar_candidatos_respeta_cap():
    import datetime as dt
    ts = int(dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp())
    fixtures = [_fixture(fixture_id=i, league_id=39) for i in range(30)]
    for f in fixtures:
        f["fixture"]["timestamp"] = ts
    candidatos = top_picks._filtrar_candidatos(fixtures, "20260601", "01/06/2026")
    assert len(candidatos) == top_picks.CAP_CANDIDATOS


# ---------------------------------------------------------------------------------------------
# Fix real 2026-09-09 — consistencia de pick entre Top Picks (canal) y analisis_completo.py
# (bot/app): `_consolidar_pick` reusa `services/consenso_ia.py::combinar_con_claude()` sobre el
# `resultado_motor` de `services/motor.py::analizar_partido()` — el MISMO motor que usa
# `analisis_completo.py` — en vez del voto ad-hoc a 3 vías (poisson/forma/IA) que existía antes
# y nunca pesaba h2h/odds/tabla en la decisión, aunque el mensaje del canal ya los mostraba.
# ---------------------------------------------------------------------------------------------

def _d_h2h_odds_favorecen_visitante() -> dict:
    """Partido armado a propósito para que diverjan poisson-solo (lo que decidía el pick antes)
    y el consenso completo de 5 módulos (lo que decide el pick ahora): poisson da "Empate",
    pero h2h+odds+tabla favorecen fuerte al Visitante y arrastran el consenso a "Visitante" —
    valores confirmados corriendo `motor.analizar_partido(d)` real, no asumidos."""
    return {
        "local": "Real Madrid", "visitante": "Barcelona", "liga": "La Liga", "partido_id": "1",
        "goles_local_avg": 1.5, "goles_visit_avg": 1.1,
        "goles_contra_local_avg": 1.1, "goles_contra_visit_avg": 1.3,
        "liga_goles_avg": 2.6,
        "forma_local_wins": 3, "forma_visit_wins": 2,
        "pos_local": 15, "pos_visit": 2,
        "h2h_disponible": True, "h2h_total": 8,
        "h2h_local_wins": 1, "h2h_visit_wins": 6, "h2h_empates": 1,
        "odds_disponibles": True, "odds_local": 3.60, "odds_empate": 3.80, "odds_visit": 1.65,
    }


def test_consolidar_pick_usa_h2h_y_odds_igual_que_analisis_completo():
    """Regresión del bug real: antes Top Picks solo votaba poisson/forma/IA, nunca h2h/odds/
    tabla. Acá `motor.analizar_partido(d)` (el mismo que llama `analisis_completo.py`) da
    consenso "Visitante" mientras poisson solo (lo que el código viejo usaba como pick) da
    "Empate" — `_consolidar_pick` (sin IA disponible) debe coincidir EXACTO con el consenso
    completo, no con poisson."""
    resultado_motor = motor.analizar_partido(_d_h2h_odds_favorecen_visitante())
    consenso_est = resultado_motor["consenso"]
    poisson_pick = resultado_motor["modulos"]["poisson"]["pick"]

    # Confirma el escenario real de divergencia antes de afirmar el fix.
    assert consenso_est["pick_final"] == "Visitante"
    assert poisson_pick != consenso_est["pick_final"]

    ia_no_disponible = {"pick": None, "razon": "IA no disponible", "confianza": None}
    combinado = top_picks._consolidar_pick(resultado_motor, ia_no_disponible)

    assert combinado["nivel_ia"] == "SOLO_ESTADISTICO"
    assert combinado["pick_unificado"] == "Barcelona"  # equipo visitante real del `d`
    # Verificación empírica pedida: el pick de Top Picks coincide con lo que analisis_completo.py
    # calcularía para el mismo partido (mismo `resultado_motor`, mismo consenso).
    assert combinado["pick_estadistico"] == combinado["pick_unificado"]


def test_consolidar_pick_ia_coincide_sube_el_score_vs_sin_ia():
    resultado_motor = motor.analizar_partido(_d_h2h_odds_favorecen_visitante())

    sin_ia = top_picks._consolidar_pick(resultado_motor, {"pick": None, "razon": "", "confianza": None})
    ia_coincide = top_picks._consolidar_pick(resultado_motor, {"pick": "Barcelona", "razon": "", "confianza": 80})

    assert ia_coincide["nivel_ia"] == "COINCIDEN"
    assert ia_coincide["pick_unificado"] == sin_ia["pick_unificado"] == "Barcelona"
    assert ia_coincide["score_consolidado"] == sin_ia["score_consolidado"]
    assert ia_coincide["confianza_final"] == sin_ia["confianza_final"]


def test_consolidar_pick_ia_diverge_no_cambia_el_pick_estadistico():
    """Igual que `analisis_completo.py`/`consenso_ia.py`: el pick final sigue siendo el
    estadístico consolidado aunque la IA opine distinto — la IA solo mueve el score y el
    `nivel_ia`, nunca reemplaza el pick de los 5 módulos."""
    resultado_motor = motor.analizar_partido(_d_h2h_odds_favorecen_visitante())

    combinado = top_picks._consolidar_pick(
        resultado_motor, {"pick": "Real Madrid", "razon": "", "confianza": 70}
    )

    assert combinado["nivel_ia"] == "DIVERGEN"
    assert combinado["pick_unificado"] == "Barcelona"


# ---------------------------------------------------------------------------------------------
# Guarda de idempotencia real antes de `publicar_top_picks` — hoy `RecomendacionDia` (sobrantes)
# ya era delete+reinsert idempotente, pero el ENVÍO real al canal de Telegram no tenía ninguna
# protección contra doble disparo (cron 9AM + `/api/v1/scheduler/top-picks` manual, o una
# segunda corrida del mismo día).
# ---------------------------------------------------------------------------------------------

def test_publicar_top_picks_primera_vez_envia_y_marca_publicado(db_session, monkeypatch):
    envio_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(top_picks_publicacion, "enviar_mensaje", envio_mock)
    resultado = {"sin_candidatos": True, "fecha_display": "01/06/2026", "fecha_db": "20260601"}

    enviado = asyncio.run(top_picks.publicar_top_picks(db_session, None, resultado))

    assert enviado is True
    envio_mock.assert_awaited_once()
    assert top_picks._ya_publicado_hoy(db_session, "20260601") is True


def test_publicar_top_picks_persiste_el_pick_del_canal_para_verificar_resultado(db_session, monkeypatch):
    from backend.api.models.partidos import RecomendacionDia
    from backend.api.models.predicciones import AnalisisComparativo, Prediccion

    monkeypatch.setattr(top_picks_publicacion, "enviar_mensaje", AsyncMock(return_value=True))
    resultado = {
        "fecha_display": "01/06/2026", "fecha_db": "20260601", "picks": [{
            "fixture_id": "99", "local": "River", "visitante": "Boca", "liga": "Liga", "hora_chile": "20:00",
            "pick_python": "River", "pick_form": "River", "pick_claude": "River", "pick_externo": None,
            "pick_final": "River", "score_consolidado": 70, "score_py": 68, "score_form": 64,
            "prob_local_py": 0.55, "prob_empate_py": 0.25, "prob_visit_py": 0.20,
            "nivel_ia": "COINCIDEN", "razon_ia": "Mejor forma local.", "score_ia": 75, "odds_texto": "River @1.8 | Emp @3.2 | Boca @4.0",
            "modulos_consenso": "4/5 modelos coinciden en Local",
        }],
    }

    assert asyncio.run(top_picks.publicar_top_picks(db_session, None, resultado)) is True
    assert db_session.query(AnalisisComparativo).filter_by(partido_id="99", fecha="2026-06-01").count() == 1
    assert db_session.query(Prediccion).filter_by(partido_id="99", fuente="top_picks_canal").count() == 1
    assert db_session.query(RecomendacionDia).filter_by(fixture_id="99", fecha="20260601").count() == 1


def test_publicar_top_picks_segunda_vez_mismo_dia_no_reenvia_al_canal(db_session, monkeypatch):
    envio_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(top_picks_publicacion, "enviar_mensaje", envio_mock)
    resultado = {"sin_candidatos": True, "fecha_display": "01/06/2026", "fecha_db": "20260601"}

    primero = asyncio.run(top_picks.publicar_top_picks(db_session, None, resultado))
    segundo = asyncio.run(top_picks.publicar_top_picks(db_session, None, resultado))

    assert primero is True
    assert segundo is False
    envio_mock.assert_awaited_once()  # post-condición real: solo se llamó una vez a Telegram


def test_publicar_top_picks_fecha_distinta_si_envia(db_session, monkeypatch):
    """La guarda es por fecha, no global — un día distinto no queda bloqueado por la marca del
    día anterior."""
    envio_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(top_picks_publicacion, "enviar_mensaje", envio_mock)

    asyncio.run(top_picks.publicar_top_picks(
        db_session, None, {"sin_candidatos": True, "fecha_display": "01/06/2026", "fecha_db": "20260601"}
    ))
    segundo = asyncio.run(top_picks.publicar_top_picks(
        db_session, None, {"sin_candidatos": True, "fecha_display": "02/06/2026", "fecha_db": "20260602"}
    ))

    assert segundo is True
    assert envio_mock.await_count == 2


def test_formatear_mensaje_sin_candidatos():
    texto = top_picks._formatear_mensaje_canal({"sin_candidatos": True, "fecha_display": "01/06/2026"})
    assert "no hay partidos" in texto.lower()


def test_formatear_mensaje_sin_picks_validos():
    texto = top_picks._formatear_mensaje_canal(
        {"sin_candidatos": False, "sin_picks_validos": True, "fecha_display": "01/06/2026"}
    )
    assert "umbral mínimo de confianza" in texto


def test_formatear_mensaje_con_picks():
    resultado = {
        "sin_candidatos": False, "sin_picks_validos": False, "fecha_display": "01/06/2026",
        "picks": [{
            "local": "River", "visitante": "Boca", "liga": "Liga Profesional", "hora_chile": "20:00",
            "odds_texto": "River @1.8 | Emp @3.2 | Boca @4.0",
            "prob_local_py": 0.55, "prob_empate_py": 0.25, "prob_visit_py": 0.20,
            "razon_ia": "River llega mejor en localía", "pick_externo": "River Plate",
            "nivel_ia": "COINCIDEN", "modulos_consenso": "4/5 modelos coinciden en Local",
            "pick_final": "River", "score_consolidado": 72,
            "score_py": 70, "score_form": 60, "score_ia": 75,
        }],
    }
    texto = top_picks._formatear_mensaje_canal(resultado)
    assert "River vs Boca" in texto
    assert "Pick: <b>River</b>" in texto
    assert "72/100" in texto
    assert "4/5 modelos coinciden en Local" in texto
    assert "IA coincide" in texto


def test_formatear_mensaje_con_picks_sin_ia_usa_texto_correcto():
    """Confirma que el mensaje del canal queda coherente cuando no hubo IA disponible (nivel
    SOLO_ESTADISTICO) — no debe seguir hablando de "acuerdo" entre poisson/forma/IA."""
    resultado = {
        "sin_candidatos": False, "sin_picks_validos": False, "fecha_display": "01/06/2026",
        "picks": [{
            "local": "River", "visitante": "Boca", "liga": "Liga Profesional", "hora_chile": "20:00",
            "odds_texto": "Sin odds", "prob_local_py": 0.4, "prob_empate_py": 0.3, "prob_visit_py": 0.3,
            "razon_ia": "", "pick_externo": None,
            "nivel_ia": "SOLO_ESTADISTICO", "modulos_consenso": "2/2 modelos coinciden en Local",
            "pick_final": "River", "score_consolidado": 55,
            "score_py": 55, "score_form": 50, "score_ia": 0,
        }],
    }
    texto = top_picks._formatear_mensaje_canal(resultado)
    assert "sin IA" in texto
    assert "Pick: <b>River</b>" in texto


def test_top_picks_exige_dos_fuentes_reales_para_publicar():
    calidad_insuficiente = {"score_calidad": 90, "calidad_datos": {"eligible": False}}
    calidad_suficiente = {"score_calidad": 55, "calidad_datos": {"eligible": True}}
    elegibles = [item for item in (calidad_insuficiente, calidad_suficiente)
                 if item["score_calidad"] >= top_picks.UMBRAL_PUBLICAR and item["calidad_datos"]["eligible"]]
    assert elegibles == [calidad_suficiente]


def _pick_para_mensaje(**extra):
    base = {
        "local": "River", "visitante": "Boca", "liga": "Liga", "hora_chile": "20:00", "odds_texto": "Sin odds",
        "razon_ia": "", "pick_final": "Boca", "score_consolidado": 60, "nivel_ia": "COINCIDEN",
        "modulos_consenso": "2/3 modelos votan Visitante", "score_py": 50, "score_form": 50, "score_ia": 50,
        "prob_local_py": 0.55, "prob_empate_py": 0.25, "prob_visit_py": 0.20,
    }
    base.update(extra)
    return base


def test_mensaje_canal_muestra_probabilidad_del_consenso_y_poisson_solo_como_detalle():
    """El pick sale de la probabilidad ponderada: es la que se muestra. El Poisson (River 55%)
    contradice al pick Boca y por eso solo puede ser detalle secundario."""
    pick = _pick_para_mensaje(prob_consenso={
        "local": 0.30, "empate": 0.25, "visitante": 0.45, "procedencia": [("odds", 70), ("poisson", 10)],
    })
    texto = top_picks._formatear_mensaje_canal(
        {"fecha_display": "06/10/2026", "picks": [pick], "sin_candidatos": False, "sin_picks_validos": False}
    )
    assert "Probabilidad (consenso): River 30.0% | Emp 25.0% | Boca 45.0% (odds 70%, poisson 10%)" in texto
    assert "Detalle Poisson: 55.0% | 25.0% | 20.0%" in texto
    assert "📐 Poisson" not in texto
    assert "Value" not in texto


def test_probabilidad_del_pick_toma_la_del_resultado_elegido():
    consenso = {"pick_final": "Visitante", "prob_ponderada": {"local": 0.3, "empate": 0.25, "visitante": 0.45}}
    assert top_picks._probabilidad_del_pick(consenso) == 0.45
    assert top_picks._probabilidad_del_pick({"pick_final": "Sin pronóstico"}) == 0.0


def test_ranking_ordena_por_probabilidad_ponderada_y_desempata_por_score():
    candidatos = [
        {"id": "acuerdo-alto-prob-baja", "prob_pick": 0.40, "score_calidad": 80},
        {"id": "prob-alta", "prob_pick": 0.62, "score_calidad": 60},
        {"id": "prob-alta-score-mayor", "prob_pick": 0.62, "score_calidad": 70},
    ]
    candidatos.sort(key=top_picks._clave_ranking, reverse=True)
    assert [c["id"] for c in candidatos] == ["prob-alta-score-mayor", "prob-alta", "acuerdo-alto-prob-baja"]
