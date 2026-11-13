"""test_consenso.py — verifica que el port preserva PESOS_BASE y los umbrales de nivel
(FUERTE >=0.70, MODERADO >=0.55) de consenso.py."""
from __future__ import annotations

import pytest

from backend.api.services import consenso


def _modulo(pick, score, ok=True, **extra):
    probabilidades = {
        "Local": (0.5, 0.25, 0.25),
        "Empate": (0.25, 0.5, 0.25),
        "Visitante": (0.25, 0.25, 0.5),
    }[pick]
    d = {"ok": ok, "pick": pick, "confianza_score": score, "prob_local": probabilidades[0],
         "prob_empate": probabilidades[1], "prob_visitante": probabilidades[2]}
    d.update(extra)
    return d


def test_pesos_base_reflejan_la_evaluacion_del_consenso_2026_10_07():
    assert consenso.PESOS_BASE == {
        "poisson": 0.0, "historico": 0.25, "forma": 0.02, "h2h": 0.0, "odds": 0.70, "tabla": 0.03,
        "bsd_ml": 0.0,
    }
    assert sum(consenso.PESOS_BASE.values()) == pytest.approx(1.0)


def _alto(pick, score):
    """Módulo con una probabilidad clara (0,65) para el pick, para ejercitar la banda ALTA."""
    probs = {"Local": (0.65, 0.20, 0.15), "Empate": (0.20, 0.60, 0.20), "Visitante": (0.15, 0.20, 0.65)}[pick]
    return _modulo(pick, score, prob_local=probs[0], prob_empate=probs[1], prob_visitante=probs[2])


def test_todos_los_modulos_coinciden_nivel_fuerte():
    resultados = {
        "historico": _alto("Local", 80),
        "forma": _alto("Local", 70),
        "odds": _alto("Local", 78),
        "tabla": _alto("Local", 60),
    }
    r = consenso.calcular_consenso(resultados, {})
    assert r["pick_final"] == "Local"
    assert r["nivel"] == "FUERTE"
    assert r["coinciden"] == 4
    assert r["confianza_final"] == "ALTA"
    assert r["score_consenso"] >= 65


def test_modulos_con_peso_cero_son_ausentes_del_consenso():
    """poisson y h2h tienen peso 0 desde la evaluación 2026-10-07: corren (y se registran en el
    laboratorio) pero no votan ni cuentan como módulos disponibles."""
    resultados = {"poisson": _alto("Local", 90), "h2h": _alto("Local", 90), "bsd_ml": _alto("Local", 90),
                  "odds": _alto("Visitante", 60), "historico": _alto("Visitante", 60)}
    r = consenso.calcular_consenso(resultados, {})
    assert r["total_modulos"] == 2
    assert r["pick_final"] == "Visitante"
    assert r["peso_efectivo"]["poisson"] == 0 and r["peso_efectivo"]["h2h"] == 0 and r["peso_efectivo"]["bsd_ml"] == 0
    assert r["votos"]["Local"] == 0


def test_confianza_sale_de_la_probabilidad_ponderada_calibrada():
    def con_prob(p_local):
        resto = (1 - p_local) / 2
        kw = dict(prob_local=p_local, prob_empate=resto, prob_visitante=resto)
        return consenso.calcular_consenso({"odds": _modulo("Local", 70, **kw), "historico": _modulo("Local", 70, **kw)})

    assert con_prob(0.66)["confianza_final"] == "ALTA"
    assert con_prob(0.55)["confianza_final"] == "MEDIA"
    assert 45 <= con_prob(0.55)["score_consenso"] <= 64
    assert con_prob(0.45)["confianza_final"] == "BAJA"
    assert con_prob(0.45)["score_consenso"] <= 44


def test_solo_historico_disponible():
    resultados = {"historico": _modulo("Visitante", 65)}
    r = consenso.calcular_consenso(resultados, {})
    assert r["nivel"] == "SOLO_HISTORICO"
    assert r["pick_final"] == "Visitante"


def test_solo_poisson_ya_no_produce_pronostico():
    """Con peso 0 el Poisson no basta para publicar: peor que las cuotas y el histórico (evaluación 2026-10-07)."""
    r = consenso.calcular_consenso({"poisson": _modulo("Visitante", 65)}, {})
    assert r["nivel"] == "SIN_MODULOS" and r["pick_final"] == "Sin pronóstico"


def test_un_ancla_aislado_se_etiqueta_por_su_probabilidad_calibrada_y_un_no_ancla_nunca_pasa_de_baja():
    """Medido 2026-10-19 (periodo de prueba): cuotas con p>=0,60 aciertan 71 % y Dixon-Coles 69 % — están calibrados, así
    que un ancla único ya no se degrada a BAJA solo por ser único (tope de 2026-10-05, sin calibración detrás)."""
    solo_odds = consenso.calcular_consenso({"odds": _alto("Local", 90)}, {})
    assert solo_odds["nivel"] == "SOLO_ODDS" and solo_odds["confianza_final"] == "ALTA"
    debil = consenso.calcular_consenso({"odds": _modulo("Local", 90)}, {})  # p=0,50: banda MEDIA, no ALTA
    assert debil["confianza_final"] == "MEDIA"
    solo_tabla = consenso.calcular_consenso({"tabla": _alto("Local", 90)}, {})
    assert solo_tabla["confianza_final"] == "BAJA" and solo_tabla["score_consenso"] <= 44


def test_historico_con_equipo_sin_historial_o_modelo_viejo_no_llega_a_alta():
    base = _alto("Local", 80)
    assert consenso.calcular_consenso({"historico": dict(base)}, {})["confianza_final"] == "ALTA"
    assert consenso.calcular_consenso({"historico": dict(base, equipo_sin_historial=True)}, {})["confianza_final"] == "BAJA"
    assert consenso.calcular_consenso({"historico": dict(base, edad_modelo_dias=900)}, {})["confianza_final"] == "MEDIA"


def test_ningun_modulo_ok_fallback():
    resultados = {"poisson": _modulo("Local", 50, ok=False)}
    r = consenso.calcular_consenso(resultados, {})
    assert r["nivel"] == "SIN_MODULOS"
    assert r["pick_final"] == "Sin pronóstico"
    assert r["score_consenso"] == 0
    assert r["confianza_final"] == "SIN DATOS"


def test_modulo_score_muy_bajo_pierde_peso():
    """SCORE_UMBRAL_MUY_BAJO=25 -> factor 0.20 (peso casi anulado)."""
    resultados = {
        "poisson": _modulo("Local", 20),  # score < 25 -> factor 0.20
        "forma": _modulo("Visitante", 80),
    }
    pesos, modulos_ok = consenso.calcular_pesos_efectivos(resultados)
    # poisson: peso_base 0.32 * 0.20 = 0.064 (antes de renormalizar)
    # forma:   peso_base 0.15 * factor(score=80) > 0.15
    # tras renormalizar, forma debe pesar mucho más que poisson
    assert pesos["forma"] > pesos["poisson"]


def test_disidentes_y_en_consenso_correctos():
    resultados = {
        "historico": _modulo("Local", 70),
        "odds": _modulo("Empate", 60),
    }
    r = consenso.calcular_consenso(resultados, {})
    assert set(r["modulos_en_consenso"]) | set(r["modulos_disidentes"]) == {"historico", "odds"}
    assert len(r["modulos_en_consenso"]) == 1


def test_pick_usa_probabilidad_ponderada_no_solo_el_voto():
    """Un módulo de baja calidad no puede forzar Empate si el agregado favorece al local."""
    resultados = {
        "historico": _modulo("Empate", 40, prob_local=0.356, prob_empate=0.446, prob_visitante=0.198),
        "odds": _modulo("Local", 78, prob_local=0.5615, prob_empate=0.2626, prob_visitante=0.1759),
    }
    r = consenso.calcular_consenso(resultados, {})
    assert r["pick_final"] == "Local"
    assert r["criterio_pick"] == "probabilidad_ponderada"
    assert r["votos"]["Empate"] == 1


def test_probabilidad_ganadora_baja_no_se_presenta_como_confianza_media_o_alta():
    resultados = {
        "historico": _modulo("Empate", 70, prob_local=0.37, prob_empate=0.39, prob_visitante=0.24),
        "forma": _modulo("Visitante", 70, prob_local=0.25, prob_empate=0.31, prob_visitante=0.44),
        "odds": _modulo("Local", 85, prob_local=0.47, prob_empate=0.27, prob_visitante=0.26),
    }
    r = consenso.calcular_consenso(resultados, {})
    assert max(r["prob_ponderada"].values()) < 0.48
    assert r["nivel"] == "DEBIL"
    assert r["confianza_final"] == "BAJA"
    assert r["score_consenso"] <= 44


def test_resumen_probabilidad_consenso_incluye_procedencia_ordenada_por_peso():
    resultados = {
        "odds": {"ok": True, "pick": "Visitante", "prob_local": 0.30, "prob_empate": 0.25, "prob_visitante": 0.45, "confianza_score": 50},
        "historico": {"ok": True, "pick": "Local", "prob_local": 0.50, "prob_empate": 0.28, "prob_visitante": 0.22, "confianza_score": 50},
    }
    res = consenso.calcular_consenso(resultados)
    resumen = consenso.resumen_probabilidad_consenso(res)
    assert [m for m, _ in resumen["procedencia"]] == ["odds", "historico"]
    assert abs(resumen["local"] + resumen["empate"] + resumen["visitante"] - 1.0) < 0.01
    texto = consenso.texto_probabilidad_consenso(res, "River", "Boca")
    assert texto.startswith("River ") and "Boca " in texto and "odds " in texto


def test_resumen_probabilidad_consenso_sin_modulos_es_none():
    assert consenso.resumen_probabilidad_consenso(consenso.calcular_consenso({})) is None
    assert consenso.texto_probabilidad_consenso(None) == ""


def test_ajuste_nivel_trata_cualquier_solo_modulo_como_neutro_y_solo_fallback_penaliza():
    resultados = {"odds": {"ok": True, "pick": "Local", "confianza_score": 60}}
    kwargs = dict(resultados=resultados, pesos_efectivos={"odds": 1.0}, modulos_ok=["odds", "poisson"],
                  pick_final="Local", votos_peso={"Local": 1.0})
    # `modulos_ok` de 2 evita el tope de un módulo y deja ver el ajuste por nivel
    neutro = consenso.calcular_score_consenso(**kwargs, nivel="SOLO_ODDS")
    assert neutro == consenso.calcular_score_consenso(**kwargs, nivel="SOLO_POISSON")
    assert neutro == consenso.calcular_score_consenso(**kwargs, nivel="NIVEL_DESCONOCIDO")
    assert consenso.calcular_score_consenso(**kwargs, nivel="SOLO_FALLBACK") == neutro - 15


def test_sin_modulo_ancla_la_confianza_nunca_pasa_de_baja():
    """Sandbox 2026-10-09 (escenario D): solo tabla + forma (3% y 2%) renormalizadas daban ALTA con 9 puntos de
    error en P(local). Sin mercado ni histórico no hay respaldo medido para ALTA/MEDIA."""
    resultados = {
        "tabla": {"ok": True, "pick": "Local", "prob_local": 0.72, "prob_empate": 0.18, "prob_visitante": 0.10, "confianza_score": 80},
        "forma": {"ok": True, "pick": "Local", "prob_local": 0.70, "prob_empate": 0.20, "prob_visitante": 0.10, "confianza_score": 80},
    }
    r = consenso.calcular_consenso(resultados)
    assert r["pick_final"] == "Local" and r["confianza_final"] == "BAJA"
    con_ancla = dict(resultados, historico={"ok": True, "pick": "Local", "prob_local": 0.72, "prob_empate": 0.18,
                                            "prob_visitante": 0.10, "confianza_score": 70})
    assert consenso.calcular_consenso(con_ancla)["confianza_final"] in ("ALTA", "MEDIA")


# ---------- MB-40: contrato consenso.v1 con procedencia ----------
def test_el_consenso_declara_su_procedencia_sin_cambiar_ninguna_cifra():
    from backend.api.services import consenso

    res = {"odds": {"ok": True, "pick": "Local", "prob_local": 0.5, "prob_empate": 0.27, "prob_visitante": 0.23, "confianza_score": 70, "metodo": "cuotas sin margen"},
           "historico": {"ok": True, "pick": "Local", "prob_local": 0.48, "prob_empate": 0.28, "prob_visitante": 0.24, "confianza_score": 60, "metodo": "dixon_coles_mas_laplace",
                         "laplace_en_mezcla": {"peso": 0.55, "version": "20261111-real-g3"}}}
    r = consenso.calcular_consenso(res)
    proc = r["procedencia"]
    assert r["contrato"] == proc["contrato"] == "consenso.v1"
    assert {m["modulo"] for m in proc["modulos"]} == {"odds", "historico"} and "forma" in proc["modulos_sin_respuesta"]
    historico = next(m for m in proc["modulos"] if m["modulo"] == "historico")
    assert historico["version_modelo_propio"] == "20261111-real-g3" and historico["peso_modelo_propio"] == 0.55 and historico["peso"] > 0
    assert proc["pesos_configurados"] == consenso.PESOS_BASE and proc["calculado_en"].endswith("Z")
    sin = {k: v for k, v in r.items() if k not in ("procedencia", "contrato")}
    assert sin["pick_final"] == "Local" and abs(sum(sin["prob_ponderada"].values()) - 1) < 1e-6  # las cifras son las de siempre


def test_sin_modulos_el_consenso_no_inventa_procedencia():
    from backend.api.services import consenso

    r = consenso.calcular_consenso({})
    assert r["pick_final"] == "Sin pronóstico" and r["total_modulos"] == 0


def test_el_health_del_bot_declara_el_contrato_y_los_pesos_del_consenso():
    """MB-44: el registro de piezas del agente lee la versión del consenso y sus pesos del /health."""
    from fastapi.testclient import TestClient

    from backend.api.main import app
    from backend.api.services import consenso

    r = TestClient(app).get("/health").json()
    assert r["status"] == "ok" and r["consenso"]["contrato"] == "consenso.v1" and r["consenso"]["pesos"] == consenso.PESOS_BASE
