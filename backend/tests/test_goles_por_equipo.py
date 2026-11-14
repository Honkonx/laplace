"""GO-2: los goles de cada equipo llegan al contrato del modelo y a los mensajes, validados contra la media de la liga (medido el 2026-11-14)."""
from __future__ import annotations

import math
import random

import pytest

from backend.api.ml.laplace import goles, servicio
from backend.api.services import agent_runtime_prompts as prompts, mensajes_analisis as ma


def _poisson(rng: random.Random, lam: float) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def test_la_distribucion_de_goles_de_un_equipo_suma_uno_y_marca_es_uno_menos_cero_goles():
    for lam in (0.4, 1.3, 2.8):
        d = goles.por_equipo(lam)
        assert d["p0"] + d["p1"] + d["p2"] + d["p3_o_mas"] == pytest.approx(1.0, abs=2e-4)
        assert d["marca"] == pytest.approx(1 - d["p0"], abs=1e-4) and d["esperados"] == round(lam, 2)
    assert goles.por_equipo(2.5)["marca"] > goles.por_equipo(0.7)["marca"]


def _salida(validados):
    return {"ok": True, "fuente": "modelo", "degradado": False, "p1x2": {"local": 0.5, "empate": 0.27, "visitante": 0.23}, "goles_esperados": {"local": 1.7, "visitante": 0.9, "total": 2.6},
            "btts": {"si": 0.5, "no": 0.5}, "over_under": {"2.5": {"mas": 0.52, "menos": 0.48}}, "marcadores": [{"marcador": "1-0", "prob": 0.12}], "confianza": 0.1, "validados": validados}


def test_el_resumen_para_consumidores_trae_los_goles_por_equipo_solo_si_estan_validados():
    con = servicio.resumen_para_consumidores(_salida(["equipo"]))["goles_por_equipo"]
    assert con["local"]["esperados"] == 1.7 and con["visitante"]["marca"] == pytest.approx(1 - math.exp(-0.9), abs=1e-3) and con["acierto_historico_marcador"] == 0.124
    assert servicio.resumen_para_consumidores(_salida(["total"]))["goles_por_equipo"] is not None        # artefactos anteriores: el total validado los habilitaba
    assert servicio.resumen_para_consumidores(_salida([]))["goles_por_equipo"] is None


def test_los_mensajes_del_bot_y_del_agente_nombran_la_probabilidad_de_marcar_y_el_acierto_real_del_marcador():
    modelo = servicio.resumen_para_consumidores(_salida(["equipo", "total"]))
    texto = ma._goles_validados(modelo)
    assert "marca local 82% · visitante 59%" in texto and "marcador más probable 1-0 (acierta ~12% de las veces)" in texto
    agente = prompts._mercados_de_goles(modelo)
    assert "cada equipo marque: local 82%, visitante 59%" in agente and "acierta ~12%" in agente
    sin = servicio.resumen_para_consumidores(_salida([]))
    assert "marca local" not in ma._goles_validados(sin) and "cada equipo marque" not in prompts._mercados_de_goles(sin)


def test_la_calibracion_valida_los_goles_de_cada_equipo_solo_si_ganan_a_la_media_de_la_liga():
    rng = random.Random(7)
    filas = []
    for _ in range(2600):
        th, ta = rng.uniform(0.8, 2.4), rng.uniform(0.6, 1.8)
        filas.append((th, ta, 1.5, 1.1, _poisson(rng, th), _poisson(rng, ta)))
    r = goles.calibrar({"X": filas})
    assert r["util"]["equipo"] is True and r["reserva"]["goles_por_equipo"]["poisson_mejora_por_partido"] > 0
    # una λ que no informa nada (aleatoria e independiente de los goles) no debe quedar validada con holgura
    ruido = [(rng.uniform(0.8, 2.4), rng.uniform(0.6, 1.8), 1.5, 1.1, _poisson(rng, 1.5), _poisson(rng, 1.1)) for _ in range(2600)]
    assert goles.calibrar({"X": ruido})["reserva"]["goles_por_equipo"]["poisson_mejora_por_partido"] < r["reserva"]["goles_por_equipo"]["poisson_mejora_por_partido"] / 4
