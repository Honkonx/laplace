"""Orquestador `pronostico_conjunto` (paralelo + serie) y la evidencia en vivo del modelo frente a las demás variantes."""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import laboratorio_pronosticos as lab
from backend.api.services import pronostico_conjunto as pc


def _correr(coro):
    return asyncio.run(coro)


async def _tarda(segundos, valor):
    await asyncio.sleep(segundos)
    return valor


async def _falla():
    raise RuntimeError("pieza rota")


def test_las_piezas_independientes_corren_a_la_vez():
    inicio = time.perf_counter()
    r = _correr(pc.ejecutar({"bot": lambda: _tarda(0.3, "b"), "modelo": lambda: _tarda(0.3, "m")}))
    assert time.perf_counter() - inicio < 0.55  # en serie serían ≥ 0,6 s
    assert r.valor("bot") == "b" and r.valor("modelo") == "m" and set(r.disponibles) == {"bot", "modelo"}


def test_una_pieza_que_cae_no_afecta_a_la_otra_y_queda_registrada():
    r = _correr(pc.ejecutar({"bot": _falla, "modelo": lambda: _tarda(0, "m")}))
    assert r.valor("modelo") == "m" and r.valor("bot") is None
    assert r.paralelas["bot"].ok is False and isinstance(r.paralelas["bot"].error, RuntimeError)
    assert r.resumen()["bot"]["error"] == "RuntimeError" and r.resumen()["modelo"]["ok"] is True


def test_una_pieza_lenta_se_agota_con_su_propio_plazo_sin_retrasar_a_las_demas():
    inicio = time.perf_counter()
    r = _correr(pc.ejecutar({"bot": lambda: _tarda(0, "b"), "modelo": lambda: _tarda(5, "m")}, plazos={"modelo": 0.1}))
    assert time.perf_counter() - inicio < 1.0
    assert r.paralelas["modelo"].agotada and r.valor("modelo") is None and r.valor("bot") == "b"


def test_la_serie_recibe_lo_que_haya_y_puede_saltarse_lo_que_falte():
    async def ia(conjunto):
        if conjunto.valor("bot") is None:
            return None  # sin el bot no hay qué explicar
        return f"explico {conjunto.valor('bot')} y {conjunto.valor('modelo')}"

    ok = _correr(pc.ejecutar({"bot": lambda: _tarda(0, "B"), "modelo": lambda: _tarda(0, "M")}, serie={"ia": ia}))
    assert ok.valor("ia") == "explico B y M"
    sin_modelo = _correr(pc.ejecutar({"bot": lambda: _tarda(0, "B"), "modelo": _falla}, serie={"ia": ia}))
    assert sin_modelo.valor("ia") == "explico B y None"
    sin_bot = _correr(pc.ejecutar({"bot": _falla, "modelo": lambda: _tarda(0, "M")}, serie={"ia": ia}))
    assert sin_bot.valor("ia") is None and "ia" not in sin_bot.disponibles


def test_una_pieza_de_la_serie_que_cae_no_tumba_el_conjunto():
    r = _correr(pc.ejecutar({"bot": lambda: _tarda(0, "B")}, serie={"ia": lambda c: _falla()}))
    assert r.valor("bot") == "B" and r.serie["ia"].ok is False


def test_sin_piezas_devuelve_un_conjunto_vacio():
    r = _correr(pc.ejecutar({}))
    assert r.disponibles == [] and r.resumen() == {}


def test_la_cancelacion_se_propaga_y_no_se_traga():
    async def principal():
        tarea = asyncio.create_task(pc.ejecutar({"lento": lambda: _tarda(5, "x")}))
        await asyncio.sleep(0.05)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    _correr(principal())


# ---------- evidencia en vivo del modelo frente a las demás variantes ----------
@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _fila(variante, partido, log_loss, rps=0.2):
    return PronosticoExperimental(experimento_codigo=variante, partido_id=partido, fecha_partido="2026-11-10", local="A", visitante="B", fuente="laplace", variante=variante,
                                  corte_datos_en="2026-11-10T00:00:00", creado_en="2026-11-10", resultado_real="1-0", log_loss=log_loss, rps=rps)


def test_sin_observaciones_dice_cuanto_falta(db):
    r = lab.comparar_en_vivo(db)
    assert r["evaluados"] == 0 and r["propia"] is None and r["falta_para_exploratoria"] == 50 and r["falta_para_promocion"] == 200


def test_compara_solo_sobre_los_mismos_partidos(db):
    for i, (propia, otra) in enumerate([(0.9, 1.0), (1.0, 1.1)]):
        db.add(_fila("laplace_modelo", f"p{i}", propia))
        db.add(_fila("dixon_coles_historico", f"p{i}", otra))
    db.add(_fila("dixon_coles_historico", "solo-otra", 5.0))   # un partido que el modelo no tuvo: no debe contar
    db.add(_fila("laplace_modelo", "solo-propia", 0.1))        # y uno que la otra variante no tuvo
    db.commit()
    r = lab.comparar_en_vivo(db)
    otra = r["otras"]["dixon_coles_historico"]
    assert otra["partidos_comunes"] == 2 and otra["log_loss_otra"] == 1.05 and otra["log_loss_propia_en_esos_partidos"] == 0.95 and otra["ventaja_log_loss"] == 0.1
    assert r["evaluados"] == 3 and r["falta_para_exploratoria"] == 47


@pytest.mark.parametrize("previo,actual,esperado", [(0, 10, []), (49, 50, ["exploratoria"]), (50, 80, []), (150, 200, ["promocion"]), (10, 210, ["exploratoria", "promocion"]), (200, 300, [])])
def test_los_avisos_saltan_una_sola_vez_al_cruzar_cada_umbral(previo, actual, esperado):
    assert lab.cruces_de_umbral(previo, actual) == esperado
