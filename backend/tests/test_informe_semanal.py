"""AU-6 y GO-3: el informe semanal sale de lo que el sistema verificó solo (cola → cierre → observaciones del laboratorio), sobre una base de migraciones reales."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from backend.api.models.predicciones import ExperimentoPronostico
from backend.api.services import informe_semanal as inf, laboratorio_pronosticos as lab, verificacion as v

AHORA = datetime(2026, 11, 20, 12, 0)


@pytest.fixture()
def db(base_migrada):
    s = base_migrada("head")()
    lab.asegurar_experimentos_base(s)
    yield s
    s.close()


def _codigo(db):
    return db.query(ExperimentoPronostico).filter(ExperimentoPronostico.permite_consenso == 0).first().codigo


def _registrar(db, pid, probs, esperados, variante="laplace_modelo", liga="Chile"):
    lab.registrar_pronostico(db, experimento_codigo=_codigo(db), partido_id=pid, fecha_partido="2026-11-19", local=f"L{pid}", visitante=f"V{pid}", liga=liga, fuente="t", variante=variante,
                             corte_datos_en="2026-11-19T10:00:00Z", hora_kickoff="2026-11-19T21:00:00", pick="local", prob_local=probs[0], prob_empate=probs[1], prob_visitante=probs[2],
                             marcador_probable="1-0", goles_local_esperados=esperados[0], goles_visitante_esperados=esperados[1])


class Fuente:
    def __init__(self, resultados):
        self.resultados = resultados

    async def __call__(self, client, fila):
        gl, gv = self.resultados[fila.partido_id]
        return {"status": "FT", "goles_local": gl, "goles_visitante": gv, "liga": "Chile"}


def _jornada(db, n=40):
    resultados = {}
    for i in range(n):
        _registrar(db, f"M{i}", (0.55, 0.25, 0.20), (1.7, 0.9))
        resultados[f"M{i}"] = (2, 0) if i % 3 else (0, 1)       # 2/3 locales, 1/3 visitantes
    db.commit()
    asyncio.run(v.procesar_vencidas(db, None, ahora=datetime(2026, 11, 20, 0, 0), fuente=Fuente(resultados), limite=500))
    return resultados


def test_el_informe_mide_solo_lo_verificado_solo_y_declara_el_embudo(db):
    _jornada(db, 40)
    _registrar(db, "PEND", (0.4, 0.3, 0.3), (1.2, 1.1))      # aún sin resultado
    db.commit()
    r = inf.generar(db, dias=7, ahora=AHORA)
    assert r["embudo"]["cerrados"] == 40 and r["embudo"]["sin_resultado_aun"] == 1 and r["embudo"]["por_estado"]["final"] == 40
    p = r["por_variante"]["laplace_modelo"]
    assert p["n"] == 40 and p["acierto"] == pytest.approx(26 / 40, abs=1e-4)   # 26 locales de 40: el pick «local» acierta en esos
    assert p["log_loss"] > 0 and p["rps"] > 0 and len(p["ic95_mejora"]) == 2


def test_el_informe_compara_los_goles_de_cada_equipo_con_la_media_de_la_ventana(db):
    _jornada(db, 40)
    g = inf.generar(db, dias=7, ahora=AHORA)["goles"]
    assert g["n"] == 40 and set(g) >= {"local", "visitante", "marcador_probable_acertado"}
    # esperados 1.7 y 0.9; reales 2 o 0 (media ≈ 1.33) y 0 o 1 (media ≈ 0.33): el error absoluto sale de los datos y no de un número fijo
    assert g["local"]["error_abs"] == pytest.approx(sum(abs(1.7 - (2 if i % 3 else 0)) for i in range(40)) / 40, abs=1e-3)
    assert g["visitante"]["error_abs"] == pytest.approx(sum(abs(0.9 - (0 if i % 3 else 1)) for i in range(40)) / 40, abs=1e-3)


def test_con_poca_muestra_el_informe_dice_que_es_pronto_y_no_inventa(db):
    _registrar(db, "A", (0.5, 0.3, 0.2), (1.5, 1.0))
    db.commit()
    asyncio.run(v.procesar_vencidas(db, None, ahora=datetime(2026, 11, 20, 0, 0), fuente=Fuente({"A": (1, 0)})))
    r = inf.generar(db, dias=7, ahora=AHORA)
    assert "pronto" in r["lectura"] and r["goles"] is None and r["por_variante"] == {}


def test_una_ventana_sin_nada_no_falla(db):
    r = inf.generar(db, dias=7, ahora=AHORA)
    assert r["embudo"]["cerrados"] == 0 and r["por_variante"] == {} and r["por_liga"] == []
    assert inf.texto(r).count("\n") <= 9


def test_lo_pronosticado_fuera_de_la_ventana_no_cuenta(db):
    _jornada(db, 10)
    assert inf.generar(db, dias=7, ahora=AHORA + timedelta(days=30))["embudo"]["pronosticos_en_la_ventana"] == 0
