"""MA-34: IA con herramientas y control de cifras en código (IA simulada)."""
import asyncio

import pytest


from backend.api.services import agent_ia_herramientas as fc


def test_las_cifras_del_texto_deben_salir_de_las_herramientas_o_del_mensaje():
    resp = ['{"p1x2": {"local": 0.452, "empate": 0.271, "visitante": 0.277}}']
    assert fc.cifras_ajenas("El modelo da 45.2% al local y 27,1% al empate", resp) == []
    assert fc.cifras_ajenas("Probabilidad del local: 0.452", resp) == []
    assert fc.cifras_ajenas("Veo un 63% para el local", resp) == ["63"]
    assert fc.cifras_ajenas("Con la cuota 2.5 que mencionas", resp + ["over 2.5"]) == []
    assert fc.cifras_ajenas("dos equipos y 3 goles", []) == []  # conteos chicos libres


def _consultar_que(texto, llamar=True, args=None):
    async def consultar(prompt, herramientas, rol="agente", max_tokens=700):
        if llamar:
            h = next(x for x in herramientas if x.nombre == "resultados_recientes")
            await h.ejecutar(args or {"equipo": "Betis"})
        return {"texto": texto, "proveedor": "falso", "modelo": "m", "herramientas_usadas": ["resultados_recientes"]}
    return consultar


def test_una_ia_que_inventa_una_cifra_se_rechaza(db_session):
    r = asyncio.run(fc.responder(db_session, "como le va al betis", "p", _consultar_que("El Betis ganó 17 de sus últimos 20 partidos (85%).")))
    assert r is None


def test_una_ia_que_no_llamo_ninguna_herramienta_no_sirve_para_cifras(db_session):
    assert asyncio.run(fc.responder(db_session, "hola", "p", _consultar_que("Todo bien", llamar=False))) is None


def test_una_respuesta_con_herramienta_y_sin_cifras_ajenas_se_acepta(db_session):
    r = asyncio.run(fc.responder(db_session, "como le va al betis", "p", _consultar_que("No tengo resultados guardados del Betis todavía.")))
    assert r and r["proveedor"] == "falso"


def test_un_fallo_del_proveedor_devuelve_none(db_session):
    async def roto(*a, **k):
        raise RuntimeError("sin proveedor")

    assert asyncio.run(fc.responder(db_session, "x", "p", roto)) is None


def test_el_catalogo_es_cerrado_y_las_herramientas_registran_lo_que_devuelven(db_session):
    reg = []
    nombres = {h.nombre for h in fc.catalogo(db_session, reg)}
    assert nombres == {"laplace_pronosticar", "resultados_recientes", "comparar_perfiles"}
    h = next(x for x in fc.catalogo(db_session, reg) if x.nombre == "resultados_recientes")
    asyncio.run(h.ejecutar({"equipo": "Inexistente FC"}))
    assert reg and "sin_datos" in reg[0]


def test_el_runtime_usa_el_camino_normal_si_las_herramientas_no_sirven(monkeypatch, db_session):
    from backend.api.core.config import settings
    from backend.api.services import agent_runtime
    from backend.api.services.agent_runtime import procesar_mensaje

    async def ia(prompt, max_tokens=700, rol="agente"):
        return "respuesta sin herramientas", "falso", "m"

    async def none(*a, **k):
        return None

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    monkeypatch.setattr(agent_runtime.agent_ia_herramientas, "responder", none)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    monkeypatch.setattr(settings, "AGENT_FUNCTION_CALLING", True)
    r = asyncio.run(procesar_mensaje(db_session, "fc1", "dime algo del futbol", None, "web", True, False))
    assert r["respuesta"].startswith("respuesta sin herramientas") and r["herramienta"] == "llm.respond"


# ---------- H-008: la charla libre no inventa probabilidades ----------
@pytest.mark.parametrize("texto,mensaje,reemplaza", [
    ("El local tiene 87% de ganar.", "quien gana", True), ("Será un 3-1 seguro.", "pronostica", True), ("Es un resultado seguro, gana el local.", "x", True),
    ("Con probabilidad del 45.2%", "me dijiste 45.2% antes", False), ("Un over 2.5 se paga con 3-1", "over 2.5 y 3-1?", False),
    ("El fuera de juego se sanciona cuando el atacante está más cerca de la meta.", "reglas", False), ("Fue en 1966, hace 60 años.", "historia", False),
])
def test_la_charla_libre_no_deja_pasar_porcentajes_marcadores_ni_promesas(texto, mensaje, reemplaza):
    from backend.api.services import agent_guardia_chat as g

    salida, fue = g.sanear_charla(texto, mensaje)
    assert fue is reemplaza and (salida == g.AVISO) is reemplaza
