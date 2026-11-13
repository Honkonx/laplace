"""H-026: un análisis de liga menor usaba 1 módulo de 7 sin decirlo, y el modelo propio se negaba con un equipo sin historia. Aquí: línea de fuentes, referencia de liga marcada y etiqueta de procedencia."""
from __future__ import annotations

import pytest

from backend.api.ml.laplace import servicio
from backend.api.services import mensajes_analisis as m


def test_la_linea_de_fuentes_dice_que_votaron_y_que_quedo_sin_dato():
    rm = {"modulos": {"odds": {"ok": True}, "tabla": {"ok": True}, "forma": {"ok": False}}, "modulos_skip": {"h2h": "sin historial", "historico": "x", "quality_gate": "y"}, "modelo_laplace": {"degradado": True}}
    linea = m._linea_fuentes(rm)
    assert "cuotas, tabla, referencia del modelo" in linea and "sin dato: H2H, histórico" in linea and "quality_gate" not in linea and linea.endswith("\n")
    assert "ninguna" in m._linea_fuentes({})


def test_la_linea_de_fuentes_aparece_en_el_mensaje_con_ia_y_nunca_rompe_el_html():
    rm = {"modulos": {"odds": {"ok": True}}, "modulos_skip": {"forma": "x"}}
    comb = {"texto_claude": "x", "pick_unificado": "A", "confianza_final": "MEDIA", "score_consolidado": 50, "nivel_ia": "COINCIDEN", "pick_claude": "A"}
    texto = m.formatear_mensaje_con_ia(rm, comb, "canal", "https://t.me/x")
    assert "Fuentes: cuotas · sin dato: forma" in texto and "<" not in m._linea_fuentes(rm)


@pytest.mark.parametrize("fuente,degradado,esperado", [("modelo_laplace", False, "propio"), ("dixon_coles_historico", True, "respaldo Dixon-Coles"), ("referencia_de_liga", True, "referencia de la liga")])
def test_la_etiqueta_nombra_la_procedencia_real(fuente, degradado, esperado):
    assert esperado in servicio._etiqueta_fuente({"fuente": fuente, "degradado": degradado})


@pytest.fixture()
def modelo_sintetico(monkeypatch):
    """Artefacto jerárquico de dos ligas sintéticas, sin depender del modelo ni de los datos locales."""
    from backend.api.ml.laplace import entrenamiento, simulacion
    from backend.api.services import modelo_historico

    por = {}
    for cod, semilla in (("AAA", 11), ("BBB", 12)):
        ps = simulacion.simular(semilla, n_equipos=10, temporadas=3)["partidos"]
        for p in ps:
            p["liga"] = cod
            p["ap_prom"] = tuple(p["ap_prom"])
        por[cod] = ps
    art = entrenamiento.entrenar_jerarquico(por, 10**9)
    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: ({"id": 1, "nombre": "sintético", "version": "t", "estado": "activo"}, art, ""))
    monkeypatch.setattr(servicio, "_desde_historico", lambda datos, motivo: None)
    monkeypatch.setattr(servicio, "_resolver_real", lambda datos, modelo_id=None: None)
    return modelo_historico


def test_con_ningun_equipo_conocido_en_una_liga_clara_hay_referencia_de_liga_marcada(modelo_sintetico, monkeypatch):
    monkeypatch.setattr(modelo_sintetico, "ligas_candidatas", lambda d: ["AAA"])
    s = servicio.pronosticar_partido(None, {"local": "Equipo Inventado A", "visitante": "Equipo Inventado B", "liga": "AAA"})
    assert s["ok"] and s["fuente"] == "referencia_de_liga" and s["degradado"] and s["equipo_sin_historial"] and s["modelo"] is None and s["liga_modelo"] == "AAA"
    assert abs(sum(s["p1x2"].values()) - 1) < 1e-6 and s["p1x2"]["local"] > s["p1x2"]["visitante"], "con la ventaja de local de la liga"
    resumen = servicio.resumen_para_consumidores(s)
    assert "ningún equipo" in resumen["etiqueta"] and resumen["goles_esperados"] is None, "los mercados de goles no se muestran sin validación"


def test_si_la_liga_es_ambigua_no_se_inventa_nada_y_se_dice_por_que(modelo_sintetico, monkeypatch):
    monkeypatch.setattr(modelo_sintetico, "ligas_candidatas", lambda d: ["AAA", "BBB"])
    s = servicio.pronosticar_partido(None, {"local": "Equipo Inventado A", "visitante": "Equipo Inventado B", "liga": "Serie B"})
    assert s["ok"] is False and s["degradado"] is True and s["motivo"]
    monkeypatch.setattr(modelo_sintetico, "ligas_candidatas", lambda d: [])
    assert servicio.pronosticar_partido(None, {"local": "A1", "visitante": "B1", "liga": "Liga que no existe"})["ok"] is False


def test_una_falla_del_calculo_de_referencia_no_tumba_el_pronostico(modelo_sintetico, monkeypatch):
    def roto(d):
        raise RuntimeError("alias roto")

    monkeypatch.setattr(modelo_sintetico, "ligas_candidatas", roto)
    assert servicio.pronosticar_partido(None, {"local": "A1", "visitante": "B1", "liga": "AAA"})["ok"] is False


# ---- H2H desde el historial propio -------------------------------------------------------------------------------------------------------------------------------------------
def _ps(local, visitante, gl, gv, dia, liga="AAA"):
    from datetime import date

    return {"liga": liga, "dia": dia, "fecha": date.fromordinal(dia), "local": local, "visitante": visitante, "gl": gl, "gv": gv}


@pytest.fixture()
def historial(monkeypatch):
    from backend.api.services import modelo_historico, simulador_propio

    base = 739000
    partidos = [_ps("Rojo", "Azul", 2, 0, base + 1), _ps("Azul", "Rojo", 1, 1, base + 40), _ps("Rojo", "Azul", 0, 3, base + 80), _ps("Verde", "Rojo", 5, 5, base + 90),
                _ps("Rojo", "Azul", 4, 0, base + 5, liga="BBB")]  # el último es de OTRA liga: no cuenta
    monkeypatch.setattr(simulador_propio, "_partidos", lambda: partidos)
    monkeypatch.setattr(modelo_historico, "_resolver", lambda d: ("AAA", None, "Rojo", "Azul") if d["local"] in ("Rojo FC", "Azul") and d["visitante"] in ("Azul", "Rojo FC") else (None, "x"))
    return partidos


def test_los_cruces_propios_se_orientan_al_partido_actual_y_ignoran_otras_ligas(historial):
    from backend.api.services import h2h_fetch

    cruces = h2h_fetch._cruces_propios("Rojo FC", "Azul", "Liga A")
    assert [(c["local"], c["goles_local"], c["goles_visitante"]) for c in cruces] == [("Rojo FC", 0, 3), ("Azul", 1, 1), ("Rojo FC", 2, 0)], "más reciente primero, sin el de otra liga"
    assert h2h_fetch._cruces_propios("Rojo FC", "Verde", "Liga A") == [], "si un equipo no se resuelve exacto no se inventa nada"


def test_la_cascada_usa_el_historial_propio_cuando_las_fuentes_externas_no_dan_tres_cruces(historial, monkeypatch):
    import asyncio

    from backend.api.services import h2h_fetch

    async def sin_nada(*a, **k):
        return None

    monkeypatch.setattr(h2h_fetch, "_apifootball_h2h", sin_nada)
    monkeypatch.setattr(h2h_fetch, "_bsd_h2h", sin_nada)
    r = asyncio.run(h2h_fetch.obtener_h2h(None, None, 1, 2, "Rojo FC", "Azul", "Liga A"))
    assert r["h2h_disponible"] and r["h2h_total"] == 3 and r["fuente_h2h"] == "historial_propio"
    assert (r["h2h_local_wins"], r["h2h_empates"], r["h2h_visit_wins"]) == (1, 1, 1)
    # con menos de 3 cruces propios no sustituye: sigue la cascada de siempre
    historial[:] = historial[:2]
    r2 = asyncio.run(h2h_fetch.obtener_h2h(None, None, None, None, "Rojo FC", "Azul", "Liga A"))
    assert r2.get("fuente_h2h") != "historial_propio"
