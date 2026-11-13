"""Estado de diálogo (MA-31): los seguimientos cortos heredan el último partido de la sesión."""
import asyncio

import pytest

from backend.api.services import agent_dialogo as d
from backend.api.services.agent_runtime import procesar_mensaje

P = ("Real Madrid", "Barcelona")


@pytest.mark.parametrize("frase,esperado", [
    ("¿y mañana?", "analiza Real Madrid vs Barcelona mañana"), ("y hoy?", "analiza Real Madrid vs Barcelona"),
    ("y las cuotas?", "cuotas Real Madrid vs Barcelona"), ("y el over 3.5?", "over 3.5 en Real Madrid vs Barcelona"), ("y mas de 2,5", "over 2.5 en Real Madrid vs Barcelona"),
    ("y ambos marcan?", "ambos marcan en Real Madrid vs Barcelona"), ("y con IA?", "predicción solo IA Real Madrid vs Barcelona"), ("y con el bot?", "predicción bot Real Madrid vs Barcelona"),
    ("y el visitante?", "analiza Real Madrid vs Barcelona"), ("y el empate?", "analiza Real Madrid vs Barcelona"),
])
def test_los_seguimientos_se_reescriben_con_el_ultimo_partido(frase, esperado):
    assert d.reescribir(frase, P) == esperado


@pytest.mark.parametrize("frase", ["hola", "partidos de hoy", "y que opinas de la situacion economica del pais en general", "y", "mis tareas", "y el clima?"])
def test_lo_que_no_es_seguimiento_no_se_toca(frase):
    assert d.reescribir(frase, P) is None


def test_la_fecha_del_partido_original_se_conserva_en_las_cuotas():
    assert d.reescribir("y las cuotas?", P, "mañana") == "cuotas Real Madrid vs Barcelona mañana"


def test_conversacion_de_tres_turnos_sin_repetir_datos(db_session):
    r1 = asyncio.run(procesar_mensaje(db_session, "dlg", "analiza Real Madrid vs Barcelona", None, "web", False, False))
    sid = r1["session_id"]
    r2 = asyncio.run(procesar_mensaje(db_session, "dlg", "y las cuotas?", sid, "web", False, False))
    assert r2["herramienta"] == "sports.get_odds"
    r3 = asyncio.run(procesar_mensaje(db_session, "dlg", "y con IA?", sid, "web", False, False))
    assert r3["herramienta"] in ("agent.ai_prediction", "agent.prediction_choice")


def test_sin_partido_previo_el_seguimiento_no_inventa_equipos(db_session):
    r = asyncio.run(procesar_mensaje(db_session, "dlg2", "y las cuotas?", None, "web", False, False))
    assert r["herramienta"] not in ("sports.get_odds", "sports.predict")


# ---------- MA-35: niveles de permisividad con IA ----------
def _con_ia_falsa(monkeypatch, texto="El fuera de juego se sanciona cuando el atacante está más cerca de la meta que el penúltimo defensor."):
    from backend.api.core.config import settings
    from backend.api.services import agent_runtime

    llamadas = []

    async def falsa(prompt, max_tokens=700, rol="agente"):
        llamadas.append(prompt)
        return texto, "falso", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", falsa)
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    return llamadas, settings


def test_en_modo_normal_la_charla_de_futbol_lleva_la_etiqueta_de_no_verificado(monkeypatch, db_session):
    llamadas, settings = _con_ia_falsa(monkeypatch)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "normal")
    r = asyncio.run(procesar_mensaje(db_session, "pm1", "dime algo del futbol", None, "web", True, False))
    assert llamadas and r["herramienta"] == "llm.respond" and "no verificada por el modelo de Laplace" in r["respuesta"]


def test_en_modo_estricto_la_ia_no_conversa_libremente(monkeypatch, db_session):
    llamadas, settings = _con_ia_falsa(monkeypatch)
    monkeypatch.setattr(settings, "AGENT_PERMISIVIDAD", "estricto")
    r = asyncio.run(procesar_mensaje(db_session, "pm2", "dime algo del futbol", None, "web", True, False))
    assert not llamadas and r["herramienta"] != "llm.respond"
