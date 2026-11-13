"""Las hipótesis «solo IA» del agente se califican al llegar el resultado (si se guardaron con partido), igual que el resto del track record."""
from __future__ import annotations

from backend.api.models.predicciones import PrediccionVarianteAgente
from backend.api.services import resultados


def _variante(db, partido_id, pick, **kw):
    fila = PrediccionVarianteAgente(user_id="u1", partido_id=partido_id, fecha="20260601", local="Boca", visitante="River", via="ai_scout",
                                    pick=pick, respuesta_cruda="{}", resultado_json="{}", creado_en="2026-06-01 10:00:00", **kw)
    db.add(fila)
    db.commit()
    return fila


def _guardar(db, fixture="77", gl=2, gv=1):
    return resultados._guardar_resultado(db, fixture, "Boca", "River", "Liga", gl, gv, "FT", "20260601")  # noqa: SLF001


def test_la_hipotesis_con_partido_se_califica_como_acierto(db_session):
    v = _variante(db_session, "77", "Boca")
    _guardar(db_session)
    db_session.refresh(v)
    assert (v.resultado_real, v.pick_correcto) == ("2-1", 1)


def test_la_hipotesis_con_otro_pick_se_califica_como_fallo(db_session):
    v = _variante(db_session, "77", "River")
    _guardar(db_session)
    db_session.refresh(v)
    assert (v.resultado_real, v.pick_correcto) == ("2-1", 0)


def test_acepta_local_visitante_y_empate_como_palabras(db_session):
    a, b = _variante(db_session, "78", "Local"), _variante(db_session, "79", "Empate")
    _guardar(db_session, "78", 1, 0)
    _guardar(db_session, "79", 1, 1)
    db_session.refresh(a)
    db_session.refresh(b)
    assert (a.pick_correcto, b.pick_correcto) == (1, 1)


def test_sin_partido_resuelto_no_se_califica(db_session):
    v = _variante(db_session, None, "Boca")
    _guardar(db_session)
    db_session.refresh(v)
    assert v.resultado_real is None and v.pick_correcto is None


def test_otro_partido_no_se_toca_y_no_se_recalifica(db_session):
    otra = _variante(db_session, "99", "Boca")
    ya = _variante(db_session, "77", "Boca", resultado_real="0-3", pick_correcto=0)
    _guardar(db_session)
    db_session.refresh(otra)
    db_session.refresh(ya)
    assert otra.resultado_real is None
    assert (ya.resultado_real, ya.pick_correcto) == ("0-3", 0)   # idempotente: lo ya calificado no cambia
