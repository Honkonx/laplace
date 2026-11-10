"""Degradación honesta cuando no hay datos (2026-10-19): el bot dice por qué, da la frecuencia histórica como
referencia y NUNCA inventa un pick ni gasta IA. Cubre los hallazgos medidos en el sandbox y la auditoría
(`SANDBOX_MUNDO_SINTETICO_Y_DIAGNOSTICO_VIVO_2026-10-09.md`)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings

from backend.api.services import analisis_completo, calidad_datos, mensajes_analisis, modelo_historico


def _datos_base(**extra) -> dict:
    d = {
        "local": "Club Fantasma", "visitante": "Atletico Inexistente", "liga": "Liga Fantasma",
        "partido": "x", "partido_id": "t-1", "pos_local": 10, "pos_visit": 10, "forma_datos_reales": False,
        "odds_disponibles": False, "odds_info": "Sin odds", "goles_local_avg": 1.3, "goles_visit_avg": 1.0,
        "goles_contra_local_avg": 1.0, "goles_contra_visit_avg": 1.3, "fuente_goles": "liga_generico", "liga_goles_avg": 2.6,
        "h2h_total": 0, "h2h_disponible": False, "h2h_resumen": "", "standings_info": "", "bsd_prediccion": None,
    }
    d.update(extra)
    d["calidad_datos"] = calidad_datos.calcular_calidad_datos(
        {"estadisticas_equipo": d["fuente_goles"] == "stats_equipo_real", "odds": d["odds_disponibles"]}, d)
    return d


def _analizar(db_session, d: dict) -> dict:
    async def _run():
        async with httpx.AsyncClient() as client:
            return await analisis_completo.analizar_y_persistir(
                db_session, client, match_id="t-1", local=d["local"], visitante=d["visitante"], liga=d["liga"],
                fecha="20261010", con_ia=True, usuario_id="u", datos_enriquecidos=d)
    return asyncio.run(_run())


def test_sin_ninguna_fuente_explica_el_motivo_y_da_la_referencia_general(db_session):
    r = _analizar(db_session, _datos_base())
    assert r["pick_final"] == "Sin pronóstico" and r["confianza_final"] == "SIN DATOS"
    assert r["ia_llamada_real"] is False
    texto = r["texto_final"]
    assert "Sin pronóstico propio" in texto and "no hay cuotas reales" in texto
    assert "Referencia, no pronóstico" in texto and "No distingue a estos dos equipos" in texto
    assert r["resultado_motor"]["referencia_tasa_base"]["nivel"] == "general"


def test_solo_estadisticas_de_equipo_no_se_disfraza_de_analisis_exploratorio(db_session):
    """Escenario C del sandbox: había una fuente (estadísticas) pero Poisson pesa 0; antes quedaba 'BAJA' con
    score 0 y pick 'Sin pronóstico'. Ahora es un 'sin pronóstico' coherente, sin IA y con motivo."""
    d = _datos_base(fuente_goles="stats_equipo_real", goles_local_avg=1.9, goles_visit_avg=0.8,
                    goles_contra_local_avg=0.7, goles_contra_visit_avg=1.8)
    r = _analizar(db_session, d)
    consenso = r["resultado_motor"]["consenso"]
    assert consenso["nivel"] == "SIN_MODULOS"
    assert r["pick_final"] == "Sin pronóstico" and r["confianza_final"] == "SIN DATOS" and r["score_final"] == 0
    assert r["ia_llamada_real"] is False and r["combinado"] is None
    assert "rinden peor que la frecuencia de la liga" in r["texto_final"]


def test_formatear_mensaje_sin_pronostico_es_corto_y_sin_numeros_inventados():
    texto = mensajes_analisis.formatear_mensaje_sin_pronostico(
        {"local": "A", "visitante": "B", "liga": "L", "referencia_tasa_base": {
            "nivel": "liga", "partidos": 1673, "pct_local": 42.7, "pct_empate": 32.5, "pct_visitante": 24.7}},
        ["no hay cuotas reales de este partido"], "canal", "https://t.me/x")
    assert "42.7%" in texto and "1673 partidos" in texto and "en esta liga" in texto
    assert "PICK" not in texto and "Bankroll" not in texto
    assert len(texto.splitlines()) < 16


def test_competiciones_continentales_resuelven_por_nombre_y_por_id():
    artefactos = modelo_historico._artefactos()
    if artefactos is None:
        return  # sin artefactos reales no hay nada que resolver
    for liga, liga_id, esperado in (
        ("UEFA Champions League", None, "UCL"), ("UEFA Europa League", None, "UEL"),
        ("CONMEBOL Libertadores", None, "CLI"), ("CONMEBOL Sudamericana", None, "CSU"),
        ("Cualquier nombre", 2, "UCL"), ("Cualquier nombre", 13, "CLI"),
    ):
        candidatas = modelo_historico.ligas_candidatas({"liga": liga, "liga_id": liga_id})
        if esperado in artefactos["ligas"]:
            assert candidatas == [esperado], (liga, liga_id, candidatas)


def test_liga_sin_pais_no_queda_filtrada_por_las_entradas_continentales():
    """Antes, una entrada sin país hacía que `pais in {...}` fuese verdadero para pais='' y descartaba toda liga."""
    candidatas = modelo_historico.ligas_candidatas({"liga": "Liga Profesional Argentina"})
    if modelo_historico._artefactos() and "ARG" in modelo_historico._artefactos()["ligas"]:
        assert candidatas == ["ARG"]


def test_el_mensaje_sin_pronostico_escapa_html_de_telegram():
    texto = mensajes_analisis.formatear_mensaje_sin_pronostico(
        {"local": "Harland & Wolff", "visitante": "<Club>", "liga": "A & B"}, ["x < y"], "canal", "https://t.me/x")
    assert "Harland &amp; Wolff" in texto and "&lt;Club&gt;" in texto and "x &lt; y" in texto


def test_endpoint_pronosticables_solo_lista_partidos_con_modelo(db_session, monkeypatch):
    from backend.api.models.partidos import PartidoDia
    from backend.api.routers import partidos as router_partidos

    def falso(d):
        return (True, "ok") if d["local"] == "Con Modelo" else (False, "fuera") if d["local"] != "Nuevo" else (True, "equipo_sin_historial")

    monkeypatch.setattr(modelo_historico, "validar_historico", falso)
    for i, local in enumerate(("Con Modelo", "Sin Modelo", "Nuevo")):
        db_session.add(PartidoDia(fecha="2026-10-20", match_id=str(i), liga_nombre="Liga X", local=local, visitante="Rival",
                                  hora_chile=f"1{i}:00", status="scheduled"))
    db_session.add(PartidoDia(fecha="2026-10-20", match_id="9", liga_nombre="Liga X", local="Con Modelo", visitante="R", status="finished"))
    db_session.commit()
    r = router_partidos.partidos_pronosticables("20261020", db_session)
    assert r["total_programados"] == 3 and r["total_pronosticables"] == 2
    assert [p["local"] for p in r["partidos"]] == ["Con Modelo", "Nuevo"]
    assert r["partidos"][1]["cobertura"] == "equipo_sin_historial"


def test_catalogo_web_marca_el_partido_pronosticable(monkeypatch):
    from backend.api.models.partidos import PartidoDia
    from backend.api.routers import web_catalog

    monkeypatch.setattr(modelo_historico, "validar_historico", lambda d: (d["local"] == "Con Modelo", "ok"))
    fila = PartidoDia(fecha="2026-10-20", match_id="1", liga_nombre="Liga X", local="Con Modelo", visitante="R", status="scheduled")
    assert web_catalog._fixture(fila)["pronosticable"] is True
    fila.local = "Otro"
    assert web_catalog._fixture(fila)["pronosticable"] is False


def test_listado_para_la_app_trae_las_claves_que_lee_android(db_session, monkeypatch):
    """HomeScreen/MatchesScreen leen id, hora, gol_local, gol_visitante y pronosticable; antes solo llegaban match_id/hora_chile/
    goles_local y tocar un partido navegaba con matchId vacío."""
    from backend.api.db import partidos_repo
    from backend.api.models.partidos import PartidoDia

    monkeypatch.setattr(modelo_historico, "validar_historico", lambda d: (True, "ok"))
    db_session.add(PartidoDia(fecha="2026-10-21", match_id="777", liga_slug="liga-x", liga_nombre="Liga X", local="A", visitante="B",
                              hora_chile="20:30", status="finished", goles_local=2, goles_visitante=0, cache_invalidado=0))
    db_session.commit()
    resultado = partidos_repo.leer_partidos_dia_agrupado(db_session, "20261021")
    partido = resultado["buttons"][0]
    assert partido["id"] == "777" and partido["match_id"] == "777"
    assert partido["hora"] == "20:30" and partido["hora_chile"] == "20:30"
    assert partido["gol_local"] == "2" and partido["gol_visitante"] == "0" and partido["pronosticable"] is True


def test_el_agente_recibe_y_muestra_los_motivos_del_sin_pronostico():
    from backend.api.bot import laplace_agent_bot as bot
    from backend.api.services import agent_tools

    data = {"consenso": {"pick_final": "Sin pronóstico"}, "motivos_sin_pronostico": ["no hay cuotas reales de este partido", "a", "b", "c"],
            "referencia_tasa_base": {"nivel": "liga", "pct_local": 42.7, "pct_empate": 32.5, "pct_visitante": 24.7}}
    resumen = agent_tools.resumir_prediccion(data, {"local": "A", "visitante": "B", "liga": "Liga X"})
    assert resumen["pick"] is None and len(resumen["motivos_sin_pronostico"]) == 3
    texto = bot.formatear_prediccion({"local": "A", "visitante": "B"}, resumen)
    assert "no hay cuotas reales de este partido" in texto and "Referencia, no pronóstico (esta liga)" in texto
    assert "No distingue a estos dos equipos" in texto


def test_la_ia_no_puede_colar_porcentajes_que_no_estan_en_el_prompt():
    from backend.api.services import consenso_ia

    prompt = "Referencia estadística: Local 45.2% | Empate 26.1% | Visitante 28.7%. Forma local 60%."
    texto = "\n".join([
        "El local llega mejor, con 45% según la referencia.",
        "Tiene un 83% de probabilidad de ganar.",
        "Su forma reciente es de 60% de puntos.",
        "El visitante cae al 12,5 % fuera de casa.",
        "⚖️ Balance y PICK: Local",
    ])
    limpio, quitadas = consenso_ia.depurar_cifras(texto, prompt)
    assert quitadas == ["Tiene un 83% de probabilidad de ganar.", "El visitante cae al 12,5 % fuera de casa."]
    assert "45%" in limpio and "60%" in limpio and "83%" not in limpio and "PICK: Local" in limpio
    assert consenso_ia.depurar_cifras("Sin cifras.", prompt) == ("Sin cifras.", [])
    # la línea del PICK nunca se descarta aunque traiga un porcentaje
    assert consenso_ia.depurar_cifras("⚖️ Balance y PICK: Local (91%)", prompt)[1] == []


def test_nivel_de_evidencia_ordena_de_donde_sale_el_pronostico():
    from backend.api.services.nivel_evidencia import calcular_nivel_evidencia

    def motor(modulos: dict, pesos: dict, pick: str = "Local") -> dict:
        return {"modulos": modulos, "consenso": {"pick_final": pick, "peso_efectivo": pesos}}

    ok = {"ok": True}
    assert calcular_nivel_evidencia(motor({"odds": ok, "historico": ok}, {"odds": .7, "historico": .25}))["codigo"] == "N4"
    assert calcular_nivel_evidencia(motor({"odds": ok}, {"odds": 1.0}))["codigo"] == "N3"
    assert calcular_nivel_evidencia(motor({"historico": ok}, {"historico": 1.0}))["codigo"] == "N2"
    assert calcular_nivel_evidencia(motor({"historico": {"ok": True, "equipo_sin_historial": True}}, {"historico": 1.0}))["codigo"] == "N1"
    assert calcular_nivel_evidencia(motor({"tabla": ok}, {"tabla": 1.0}))["codigo"] == "DEBIL"
    assert calcular_nivel_evidencia(motor({}, {}, pick="Sin pronóstico"))["codigo"] == "N0"
    # un histórico de equipo nuevo con cuotas reales es N3: manda el mercado
    assert calcular_nivel_evidencia(motor({"odds": ok, "historico": {"ok": True, "equipo_sin_historial": True}}, {"odds": .7, "historico": .25}))["codigo"] == "N3"


def test_el_analisis_completo_adjunta_el_nivel_de_evidencia(db_session):
    r = _analizar(db_session, _datos_base())
    assert r["resultado_motor"]["nivel_evidencia"]["codigo"] == "N0"


@pytest.mark.skipif(
    not list((settings.repo_root / "backend" / "knowledge" / "sports").glob("equipos-*.json")),
    reason="falta el conocimiento por equipo (se genera con datos históricos propios)",
)
def test_la_forma_solo_se_atribuye_dentro_de_la_liga_dada():
    """Sandbox del agente 2026-11-09: 'Club Fenix' (inventado) recibía la forma del Fénix de Uruguay."""
    from backend.api.services import conocimiento_texto

    assert conocimiento_texto.linea_forma("Club Fenix", "Liga Sintetica") is None  # liga desconocida: no se busca por nombre a secas
    assert conocimiento_texto.linea_forma("Fenix", "Premier League") is None  # liga conocida donde ese equipo no juega
    assert conocimiento_texto.linea_forma("Fenix") is not None  # sin liga (solo nombres escritos por el usuario) sí se busca por nombre


def test_mis_picks_cuenta_solo_pronosticos_con_pick_y_partidos_terminados(db_session):
    from backend.api.models.partidos import PartidoDia
    from backend.api.models.predicciones import HistorialPrediccionWeb
    from backend.api.services.precision_usuario import calcular_precision_usuario

    def historial(partido, pick, confianza="MEDIA", creado="2026-11-01T10:00:00"):
        db_session.add(HistorialPrediccionWeb(user_id="u1", partido_id=partido, fecha="20261101", liga="L", local="A", visitante="B",
                                              pick=pick, confianza=confianza, resultado_json="{}", creado_en=creado))

    def partido(match_id, gl, gv, status="finished"):
        db_session.add(PartidoDia(fecha="2026-11-01", match_id=match_id, liga_nombre="L", local="A", visitante="B", status=status,
                                  goles_local=gl, goles_visitante=gv, cache_invalidado=0))

    historial("1", "Local"); partido("1", 2, 0)            # acierto
    historial("2", "Visitante"); partido("2", 1, 1)        # fallo (empate)
    historial("3", "Empate"); partido("3", 0, 0, status="scheduled")   # pendiente
    historial("4", "Sin pronóstico"); partido("4", 1, 0)   # no es una predicción
    historial("1", "Empate", creado="2026-11-01T09:00:00")  # consulta anterior del mismo partido: cuenta solo la última
    db_session.add(HistorialPrediccionWeb(user_id="otro", partido_id="1", fecha="20261101", liga="L", local="A", visitante="B",
                                          pick="Visitante", confianza="BAJA", resultado_json="{}", creado_en="2026-11-01T10:00:00"))
    db_session.commit()
    r = calcular_precision_usuario(db_session, "u1")
    assert (r["picks_consultados"], r["sin_pronostico"], r["verificados"], r["aciertos"], r["pendientes"]) == (3, 1, 2, 1, 1)
    assert r["acierto_pct"] == 50.0 and r["concluyente"] is False and "no concluyente" in r["nota"]
    assert r["por_confianza"]["MEDIA"] == {"verificados": 2, "aciertos": 1}
