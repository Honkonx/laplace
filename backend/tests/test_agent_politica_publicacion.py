"""Política de publicación del agente: por defecto pide aprobación; publicar solo exige habilitación del administrador Y evidencia en vivo."""
from backend.api.services import agent_politica_publicacion as pol


def _pick(local=0.6, empate=0.25, visitante=0.15):
    return {"prob_consenso": {"local": local, "empate": empate, "visitante": visitante}}


def test_sin_picks_no_publica():
    assert pol.evaluar({"sin_picks_validos": True, "picks": []})["decision"] == "no_publicar"
    assert pol.evaluar({"sin_candidatos": True})["decision"] == "no_publicar"


def test_baja_confianza_o_pick_flojo_no_publica():
    assert pol.evaluar({"picks": [_pick()], "baja_confianza": True})["decision"] == "no_publicar"
    r = pol.evaluar({"picks": [_pick(0.40, 0.30, 0.30)]})
    assert r["decision"] == "no_publicar" and "probabilidad" in r["motivos"][0]


def test_por_defecto_pide_aprobacion():
    assert pol.evaluar({"picks": [_pick()]})["decision"] == "publicar_con_aprobacion"
    assert pol.evaluar({"picks": [_pick()]}, evidencia_en_vivo=5000)["decision"] == "publicar_con_aprobacion"  # sin habilitar, ni con evidencia publica solo


def test_habilitado_pero_sin_evidencia_sigue_pidiendo_aprobacion():
    r = pol.evaluar({"picks": [_pick()]}, evidencia_en_vivo=12, publica_solo_habilitado=True)
    assert r["decision"] == "publicar_con_aprobacion" and "12 de 200" in r["motivos"][0]


def test_publica_solo_exige_habilitacion_y_evidencia():
    r = pol.evaluar({"picks": [_pick()]}, evidencia_en_vivo=200, publica_solo_habilitado=True)
    assert r["decision"] == "publicar_solo"


def test_porcentajes_en_escala_0_100_tambien_se_leen():
    assert pol.evaluar({"picks": [_pick(60, 25, 15)]})["decision"] == "publicar_con_aprobacion"
