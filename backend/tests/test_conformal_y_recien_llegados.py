"""Predicción conforme del 1X2 y entrada de equipos recién llegados a la capa en vivo."""
from __future__ import annotations

import random

import pytest

from backend.api.ml.laplace import conformal


# ---- predicción conforme -------------------------------------------------------------------------------------------------------------------------------------------------
def test_el_umbral_es_el_cuantil_correcto_y_sin_muestra_suficiente_no_se_inventa():
    s = [0.1 * i for i in range(1, 10)]  # 9 puntuaciones: 0.1 … 0.9
    assert conformal.umbral(s, 0.2) == pytest.approx(0.8), "k = ⌈(9+1)·0,8⌉ = 8"
    assert conformal.umbral(s, 0.01) is None, "con 9 casos no se puede garantizar el 99 %"
    assert conformal.umbral([], 0.2) is None


def test_el_conjunto_nunca_queda_vacio_y_sin_umbral_trae_los_tres_resultados():
    p = (0.5, 0.3, 0.2)
    assert conformal.conjunto(p, None) == ("H", "D", "A")
    assert conformal.conjunto(p, 0.55) == ("H",), "1 − p = 0,5 · 0,7 · 0,8: con 0,55 solo pasa H"
    assert conformal.conjunto(p, 0.75) == ("H", "D") and conformal.conjunto(p, 0.85) == ("H", "D", "A")
    assert conformal.conjunto(p, 0.0) == ("H",), "con un umbral imposible se conserva el más probable"
    assert conformal.conjunto((0.2, 0.3, 0.5), 0.0) == ("A",)


def test_la_cobertura_empirica_sigue_la_nominal_con_datos_intercambiables():
    """Resultados sorteados desde las propias probabilidades (modelo perfectamente calibrado): la cobertura sobre datos nuevos queda cerca de 1 − α."""
    rng = random.Random(7)

    def casos(n):
        salida = []
        for _ in range(n):
            a, b = rng.random(), rng.random()
            p = (a / (a + b + 1), b / (a + b + 1), 1 / (a + b + 1))
            r = rng.choices(conformal.CLASES, weights=p)[0]
            salida.append((p, r))
        return salida

    calibracion, prueba = casos(4000), casos(4000)
    for alfa in (0.2, 0.1):
        q = conformal.umbral([conformal.puntuacion(p, r) for p, r in calibracion], alfa)
        cobertura, tamano = conformal.cobertura_y_tamano(prueba, q)
        assert abs(cobertura - (1 - alfa)) < 0.03, (alfa, cobertura)
        assert 1.0 <= tamano <= 3.0
    assert conformal.cobertura_y_tamano([], 0.5) == (0.0, 0.0)


# ---- recién llegados a la capa en vivo ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def resolver(monkeypatch):
    from backend.api.services import modelo_historico as mh
    from backend.scripts import exportar_resultados_vivos as ex

    falso = lambda: {"tabla_ligas": {}}  # noqa: E731
    falso.cache_clear = lambda: None  # el conftest limpia la caché real al terminar cada prueba
    monkeypatch.setattr(mh, "_artefactos", falso)
    monkeypatch.setattr(mh, "ligas_candidatas", lambda d: ["AAA"])
    monkeypatch.setattr(mh, "_resolver", lambda d: (None, "equipo fuera del histórico"))
    monkeypatch.setattr(mh, "_resolver_equipo", lambda art, cod, n: {"Conocido FC": "Conocido", "Otro FC": "Otro"}.get(n))
    monkeypatch.setattr(mh, "_hay_candidato_ambiguo", lambda art, cod, n: n == "Parecido")
    r, _art, _mh = ex.construir_resolver()
    return r, mh


def _crudo(local, visitante):
    return {"liga": "Liga A", "liga_id": "", "local": local, "visitante": visitante}


def test_un_recien_ascendido_entra_con_su_nombre_sin_acentos_si_el_otro_equipo_confirma_la_liga(resolver):
    r, _ = resolver
    assert r(_crudo("Conocido FC", "São Nuevo")) == ("AAA", "Conocido", "Sao Nuevo")
    assert r(_crudo("São Nuevo", "Otro FC")) == ("AAA", "Sao Nuevo", "Otro")


def test_sin_un_equipo_que_confirme_la_liga_o_con_nombre_ambiguo_o_con_liga_dudosa_se_descarta_como_antes(resolver, monkeypatch):
    r, mh = resolver
    assert r(_crudo("Nuevo Uno", "Nuevo Dos"))[1] == "equipo_desconocido", "dos desconocidos: nada confirma la liga"
    assert r(_crudo("Conocido FC", "Parecido"))[1] == "equipo_desconocido", "se parece a un equipo conocido: no se duplica su historia"
    monkeypatch.setattr(mh, "ligas_candidatas", lambda d: ["AAA", "BBB"])
    assert r(_crudo("Conocido FC", "São Nuevo"))[1] == "equipo_desconocido", "dos ligas posibles: no se adivina"
