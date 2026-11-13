"""Propiedades y fuzzing (Hypothesis) de las piezas donde un caso raro cambia lo que ve una persona (el plan de pruebas «como usuario» (repositorio de trabajo), capa 3).

Cada propiedad es un invariante del dominio, no un ejemplo: probabilidades que suman 1, el pick es el máximo, redactar es idempotente y nunca falla, ningún texto rompe el enrutador del agente,
ninguna cuota válida rompe el desmargen, ninguna liga válida da posiciones imposibles. Hypothesis busca el contraejemplo mínimo si lo hay.
"""
from __future__ import annotations

import math
import string

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CFG = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])

prob = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
cuota = st.floats(min_value=1.01, max_value=500.0, allow_nan=False, allow_infinity=False)
texto = st.text(min_size=0, max_size=400)


# ------------------------------------------------------------------ mercado y consenso
@CFG
@given(cuota, cuota, cuota)
def test_el_desmargen_da_probabilidades_validas_que_suman_uno(h, d, a):
    from backend.api.ml import mercado

    for f in (mercado.quitar_margen_proporcional, mercado.quitar_margen_shin):
        p = f(h, d, a)
        assert all(0.0 <= x <= 1.0 and math.isfinite(x) for x in p) and abs(sum(p) - 1.0) < 1e-6
    # la cuota más baja es la más probable
    p = mercado.quitar_margen_proporcional(h, d, a)
    assert p.index(max(p)) == [h, d, a].index(min([h, d, a]))


def _modulo(draw_ok, pl, pe, pv, pick, score):
    return {"ok": draw_ok, "pick": pick, "prob_local": pl, "prob_empate": pe, "prob_visitante": pv, "confianza_score": score}


modulos = st.builds(_modulo, st.booleans(), prob, prob, prob, st.sampled_from(["Local", "Empate", "Visitante", "", None, "otro"]), st.one_of(st.integers(-50, 300), st.none(), st.floats(allow_nan=True)))
resultados = st.dictionaries(st.sampled_from(["poisson", "historico", "forma", "h2h", "odds", "tabla", "bsd_ml", "desconocido"]), st.one_of(modulos, st.none(), st.just({}), st.just("basura")), max_size=8)


@CFG
@given(resultados)
def test_el_consenso_nunca_falla_y_sus_numeros_son_coherentes(res):
    from backend.api.services import consenso

    r = consenso.calcular_consenso(res)
    assert r["pick_final"] in ("Local", "Empate", "Visitante", "Sin pronóstico")
    assert r["contrato"] == "consenso.v1" or r["nivel"] == "SIN_MODULOS"
    if r["pick_final"] != "Sin pronóstico":
        p = r["prob_ponderada"]
        assert abs(sum(p.values()) - 1.0) < 0.01, p
        assert 0 <= r["score_consenso"] <= 100
        assert r["prob_ponderada"][{"Local": "local", "Empate": "empate", "Visitante": "visitante"}[r["pick_final"]]] >= max(p.values()) - 1e-9, "el pick no es el de mayor probabilidad"


# ------------------------------------------------------------------ modelo
@CFG
@given(st.lists(st.lists(st.floats(-3, 3, allow_nan=False), min_size=5, max_size=5), min_size=3, max_size=3), st.lists(st.floats(-3, 3, allow_nan=False), min_size=5, max_size=5))
def test_el_modelo_lineal_da_probabilidades_validas_y_la_explicacion_suma_el_logit(pesos, x):
    from backend.api.ml.laplace import entrenamiento as e
    from backend.api.ml.laplace import explicacion

    p = e.probs_lineal(pesos, x)
    assert abs(sum(p) - 1.0) < 1e-9 and all(0.0 <= v <= 1.0 for v in p)
    r = explicacion.contribuciones(pesos, x, ["sesgo", "a", "b", "c", "d"])
    suma = (r["sesgo"]["local_vs_visitante"] if r["sesgo"] else 0) + sum(f["local_vs_visitante"] for f in r["variables"])
    assert abs(suma - r["logit_local_vs_visitante"]) < 1e-2
    if min(p) > 1e-12:
        assert abs(r["logit_local_vs_visitante"] - math.log(p[0] / p[2])) < 2e-2


@CFG
@given(st.integers(2, 6), st.integers(1, 40), st.integers(0, 10_000), st.floats(0.0, 0.3))
def test_toda_liga_valida_da_posiciones_y_puntos_posibles(n, n_sim, semilla, sigma):
    from backend.api.ml.laplace import liga

    eq = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    pend = [{"local": a, "visitante": b} for a in eq for b in eq if a != b]
    r = liga.simular_temporada(tabla, pend, lambda l, v: (1.3, 1.0), n_sim=n_sim, semilla=semilla, sigma_fuerza=sigma, motor="python")
    pos = r["resultado"]["posiciones"]
    for e in eq:
        assert abs(sum(pos[e]) - 1.0) < 1e-9
        assert 0 <= r["resultado"]["puntos"][e]["p05"] <= r["resultado"]["puntos"][e]["p95"] <= 3 * 2 * (n - 1)
    for k in range(n):
        assert abs(sum(pos[e][k] for e in eq) - 1.0) < 1e-9, "cada posición la ocupa exactamente un equipo"
    assert r["huella_salida"] == liga.simular_temporada(tabla, pend, lambda l, v: (1.3, 1.0), n_sim=n_sim, semilla=semilla, sigma_fuerza=sigma, motor="python")["huella_salida"]


@CFG
@given(st.lists(st.text(alphabet=string.ascii_letters, min_size=1, max_size=8), min_size=0, max_size=12), st.lists(st.text(alphabet=string.ascii_letters, min_size=1, max_size=8), max_size=3))
def test_ordenar_por_favoritos_es_una_permutacion_que_no_pierde_ni_inventa_elementos(nombres, favoritos):
    from backend.api.db import bot_memoria_repo as m

    elementos = [{"local": n, "visitante": "~rival~"} for n in nombres]
    orden = m.ordenar_por_favoritos(elementos, nombres_equipo=lambda p: (p["local"], p["visitante"]), equipos=favoritos)
    assert sorted(map(id, orden)) == sorted(map(id, elementos)) and len(orden) == len(elementos)
    favs = {f.lower() for f in favoritos}
    es_fav = [p["local"].lower() in favs for p in orden]
    assert es_fav == sorted(es_fav, reverse=True), "los favoritos deben ir primero"


# ------------------------------------------------------------------ texto del usuario
@CFG
@given(texto)
def test_redactar_nunca_falla_es_idempotente_y_no_crece_sin_control(t):
    from backend.api.services.agent_privacidad import redactar

    r1, n1 = redactar(t)
    r2, n2 = redactar(r1)
    assert r2 == r1 and n2 == 0 and len(r1) <= len(t) + 12 * max(n1, 1)


@CFG
@given(st.text(alphabet=string.ascii_letters + string.digits, min_size=24, max_size=60))
def test_una_clave_con_forma_de_clave_siempre_se_oculta(cuerpo):
    from backend.api.services.agent_privacidad import redactar

    for prefijo in ("sk-", "ghp_", "AIzaSy", "xoxb-"):
        clave = prefijo + cuerpo
        assert cuerpo[:20] not in redactar(f"mi clave es {clave} gracias")[0]


@CFG
@given(texto)
def test_ningun_texto_rompe_el_enrutador_de_reglas_del_agente(t):
    from backend.api.services.agent_runtime_reglas import _fuera_de_alcance, _normalizar_humano, _partido_desde_mensaje, _respuesta_reglas

    for admin in (False, True):
        respuesta, modo, herramienta = _respuesta_reglas(_normalizar_humano(t), admin)
        assert isinstance(respuesta, str) and respuesta and isinstance(modo, str) and (herramienta is None or isinstance(herramienta, str))
        assert not (herramienta == "admin.route" and not admin), "una persona normal llegó a la ruta de administración"
    assert isinstance(_fuera_de_alcance(t), bool)
    par = _partido_desde_mensaje(t)
    assert par is None or (len(par) == 2 and all(isinstance(x, str) and x for x in par))


@CFG
@given(texto, texto)
def test_la_charla_libre_nunca_deja_pasar_porcentajes_ajenos(t, mensaje):
    import re

    from backend.api.services.agent_guardia_chat import AVISO, sanear_charla

    salida, fue = sanear_charla(t, mensaje)
    assert (salida == AVISO) == fue and (fue or salida == t)
    if not fue:
        ajenos = [m for m in re.findall(r"\d+(?:[.,]\d+)?\s*%", salida) if re.sub(r"\s+", "", m) not in re.sub(r"\s+", "", mensaje)]
        assert not ajenos


@CFG
@given(texto, st.lists(texto, max_size=3))
def test_el_control_de_cifras_nunca_falla(t, respaldos):
    from backend.api.services.agent_ia_herramientas import cifras_ajenas

    assert isinstance(cifras_ajenas(t, respaldos), list)


@CFG
@given(st.one_of(texto, st.builds(lambda a: "```json\n" + a + "\n```", texto), st.builds(lambda a: "{" + a, texto)))
def test_la_salida_de_la_ia_solo_falla_con_la_excepcion_prevista(t):
    from backend.api.services import ai_salida

    try:
        ai_salida.extraer_json(t)
        if t.strip().startswith("{"):
            ai_salida.validar_analisis(t, "Local", "Visitante")
    except ai_salida.SalidaInvalida:
        pass


# ------------------------------------------------------------------ API ml-2 con entradas arbitrarias
json_raro = st.recursive(st.one_of(st.none(), st.booleans(), st.integers(-10**12, 10**12), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=20)), lambda hijos: st.one_of(st.lists(hijos, max_size=4), st.dictionaries(st.text(max_size=8), hijos, max_size=4)), max_leaves=12)


@pytest.fixture(scope="module")
def cliente_ml():
    from backend.api.core.config import settings as s
    from backend.api.main import app

    original = s.ML_API_KEY
    s.ML_API_KEY = "clave-de-prueba-para-fuzzing-0123456789"
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        s.ML_API_KEY = original


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(json_raro, st.sampled_from(["/sim/temporada", "/sim/escenario", "/sim/caminos", "/eval/comparar", "/verificar"]))
def test_ml2_con_cualquier_cuerpo_responde_200_o_un_error_cerrado_nunca_5xx(cliente_ml, cuerpo, ruta):
    r = cliente_ml.post("/api/v2/ml" + ruta, json=cuerpo, headers={"x-laplace-ml-key": "clave-de-prueba-para-fuzzing-0123456789"})
    assert r.status_code < 500, (ruta, cuerpo, r.text[:150])
    assert "Traceback" not in r.text
