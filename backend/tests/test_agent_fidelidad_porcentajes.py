"""La redacción de la IA puede expresar como porcentaje una fracción del JSON verificado; una cifra inventada sigue rechazada."""
from __future__ import annotations

from backend.api.services import agent_runtime_prompts as p

RESUMEN = {"pick": "Manchester City", "modelo_laplace": {"p1x2": {"local": 0.5169, "empate": 0.245, "visitante": 0.2381}, "btts_si": 0.6436}}
BASE = "Análisis: pick Manchester City."


def test_una_fraccion_puede_citarse_como_porcentaje_con_2_1_o_0_decimales():
    for cifra in ("51,69", "51.69", "51,7", "52"):
        assert p._redaccion_fiel(f"Manchester City tiene {cifra} % de ganar.", RESUMEN, BASE), cifra
    assert p._redaccion_fiel("Manchester City: el empate es de 24,5 % y ambos marcan 64,36 %.", RESUMEN, BASE)


def test_una_cifra_inventada_se_rechaza_aunque_parezca_cercana():
    assert not p._redaccion_fiel("Manchester City tiene 55 % de ganar.", RESUMEN, BASE)
    assert not p._redaccion_fiel("Manchester City gana con 91,7 % de probabilidad.", RESUMEN, BASE)


def test_los_enteros_no_se_derivan_como_porcentaje():
    assert p._porcentajes_derivados('{"n": 1, "m": 0}') == set()
    assert p._porcentajes_derivados('{"x": 0.5}') >= {"50"}


def test_sigue_exigiendo_conservar_el_pick():
    assert not p._redaccion_fiel("Liverpool tiene 51,69 % de ganar.", RESUMEN, BASE)
