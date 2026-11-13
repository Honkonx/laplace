"""test_resultados_cobertura.py — cobertura de `services/resultados.py`: consulta a BSD y a api-football
(con un cliente HTTP falso, sin red), el flujo de `actualizar_resultados` (FT/AET/PEN, partido sin
terminar, cancelado, sin datos, cuota agotada o `errors` en un HTTP 200) y la idempotencia del guardado."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.models.partidos import PartidoDia, ResultadoPartido
from backend.api.models.predicciones import AnalisisComparativo, Prediccion
from backend.api.services import resultados as svc

FECHA = "2026-06-01"


class _Resp:
    def __init__(self, datos: dict, status: int = 200):
        self._datos, self.status_code = datos, status

    def json(self) -> dict:
        return self._datos

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("GET", "http://x"),
                                        response=httpx.Response(self.status_code))


class _ClienteFalso:
    """Reemplaza `httpx.AsyncClient`: responde según un fragmento de la URL y registra las llamadas."""

    def __init__(self, respuestas: dict[str, object]):
        self.respuestas, self.llamadas = respuestas, []

    async def get(self, url: str, **_kw):
        self.llamadas.append(url)
        for fragmento, resp in self.respuestas.items():
            if fragmento in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return _Resp({}, 404)


def _correr(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _claves(monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "bsd-de-prueba")
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "apif-de-prueba")


def _evento_bsd(local="River Plate", visita="Boca Juniors", gl=2, gv=1):
    return {"home_team": {"name": local}, "away_team": visita, "home_score": gl, "away_score": gv,
            "league": {"name": "Liga Profesional"}}


def _fixture_apif(fid=10, status="FT", gl=1, gv=1, local="Lanus", visita="Banfield"):
    return {"fixture": {"id": fid, "status": {"short": status}, "date": f"{FECHA}T20:00:00+00:00"},
            "teams": {"home": {"name": local}, "away": {"name": visita}}, "league": {"name": "Liga X"},
            "goals": {"home": gl, "away": gv}}


def _comparativo(db, pid="fx1", **extra):
    campos = dict(partido_id=pid, fecha=FECHA, local="River Plate", visitante="Boca Juniors", liga="Liga X",
                  pick_final="Local", hora_kickoff="20:00", creado_en="2026-06-01 10:00:00")
    campos.update(extra)
    fila = AnalisisComparativo(**campos)
    db.add(fila)
    db.commit()
    return fila


# ---------------------------------------------------------------------------- _pick_acerto
@pytest.mark.parametrize("pick,ganador,esperado", [
    (None, "local", False), ("", "local", False),
    ("river plate", "local", True), ("  LOCAL ", "local", True), ("Boca Juniors", "local", False),
    ("Boca Juniors", "visitante", True), ("visitante", "visitante", True), ("Local", "visitante", False),
    ("Empate", "empate", True), ("Local", "empate", False),
    ("Local", "otro", False),
])
def test_pick_acerto_tabla(pick, ganador, esperado):
    assert svc._pick_acerto(pick, ganador, "River Plate", "Boca Juniors") is esperado


# ---------------------------------------------------------------------------- BSD
def test_bsd_sin_clave_o_sin_datos_devuelve_none(monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    assert _correr(svc._bsd_buscar_resultado(_ClienteFalso({}), "River", "Boca", FECHA)) is None
    monkeypatch.setattr(settings, "BSD_API_KEY", "k")
    assert _correr(svc._bsd_buscar_resultado(_ClienteFalso({}), "", "Boca", FECHA)) is None
    assert _correr(svc._bsd_buscar_resultado(_ClienteFalso({}), "River", "Boca", "")) is None


def test_bsd_encuentra_el_partido_con_nombre_dict_o_string():
    cliente = _ClienteFalso({"/events/": _Resp({"results": [
        _evento_bsd("Otro Equipo", "Nadie FC", 0, 0), _evento_bsd(),
    ]})})
    res = _correr(svc._bsd_buscar_resultado(cliente, "River Plate", "Boca Juniors", FECHA))
    assert res == {"status": "FT", "local": "River Plate", "visitante": "Boca Juniors",
                   "liga": "Liga Profesional", "goles_local": 2, "goles_visitante": 1, "fecha": FECHA}
    assert "team_name=River Plate" in cliente.llamadas[0] and f"date_from={FECHA}" in cliente.llamadas[0]


def test_bsd_ignora_evento_sin_marcador_y_sin_coincidencia():
    sin_marcador = {"home_team": "River Plate", "away_team": "Boca Juniors", "home_score": None, "away_score": 1}
    cliente = _ClienteFalso({"/events/": _Resp({"results": [sin_marcador]})})
    assert _correr(svc._bsd_buscar_resultado(cliente, "River Plate", "Boca Juniors", FECHA)) is None
    cliente = _ClienteFalso({"/events/": _Resp({"results": [_evento_bsd("Gimnasia", "Racing")]})})
    assert _correr(svc._bsd_buscar_resultado(cliente, "River Plate", "Boca Juniors", FECHA)) is None


@pytest.mark.parametrize("resp", [_Resp({}, 500), _Resp({"results": None}), httpx.ConnectError("sin red")])
def test_bsd_error_de_red_o_http_no_lanza(resp):
    cliente = _ClienteFalso({"/events/": resp})
    assert _correr(svc._bsd_buscar_resultado(cliente, "River Plate", "Boca Juniors", FECHA)) is None


# ---------------------------------------------------------------------------- api-football
def test_apif_sin_clave_o_sin_ids_no_consulta(monkeypatch):
    cliente = _ClienteFalso({})
    assert _correr(svc._consultar_fixtures_apifootball(cliente, [])) == {}
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "")
    assert _correr(svc._consultar_fixtures_apifootball(cliente, ["1"])) == {}
    assert cliente.llamadas == []


def test_apif_agrupa_en_lotes_de_20_y_parsea_fixtures():
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({"response": [_fixture_apif(10, "AET", 2, 1)]})})
    ids = [str(i) for i in range(10, 35)]  # 25 ids => 2 llamadas
    res = _correr(svc._consultar_fixtures_apifootball(cliente, ids))
    assert len(cliente.llamadas) == 2
    assert len(cliente.llamadas[0].split("ids=")[1].split("-")) == 20
    assert res["10"] == {"status": "AET", "local": "Lanus", "visitante": "Banfield", "liga": "Liga X",
                         "goles_local": 2, "goles_visitante": 1, "fecha": FECHA}


def test_apif_cuota_agotada_http_429_se_salta_el_lote():
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({}, 429)})
    assert _correr(svc._consultar_fixtures_apifootball(cliente, ["1", "2"])) == {}


def test_apif_http_200_con_errors_se_lee_como_sin_datos():
    cuerpo = {"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
              "response": []}
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp(cuerpo)})
    assert _correr(svc._consultar_fixtures_apifootball(cliente, ["1"])) == {}


def test_apif_excepcion_de_red_no_lanza():
    cliente = _ClienteFalso({"/fixtures?ids=": httpx.ReadTimeout("lento")})
    assert _correr(svc._consultar_fixtures_apifootball(cliente, ["1"])) == {}


# ---------------------------------------------------------------------------- pendientes
def test_leer_pendientes_solo_sin_resultado_y_de_esa_fecha(db_session):
    _comparativo(db_session, "p1", hora_kickoff="21:00")
    _comparativo(db_session, "p2", hora_kickoff="18:00")
    _comparativo(db_session, "p3", resultado_real="1-0")
    _comparativo(db_session, "p4", fecha="2026-06-02")
    pend = svc.leer_pendientes_del_dia(db_session, FECHA)
    assert [p["fixture_id"] for p in pend] == ["p2", "p1"]  # ordenados por kickoff
    assert pend[0]["local"] == "River Plate" and pend[0]["hora_kickoff"] == "18:00"


# ---------------------------------------------------------------------------- _guardar_resultado
def test_guardar_resultado_empate_y_visitante(db_session):
    f_emp = _comparativo(db_session, "e1", pick_final="Empate", pick_claude="Local", over25_pred=0.50, btts_pred=0.50)
    r = svc._guardar_resultado(db_session, "e1", "River Plate", "Boca Juniors", "Liga X", 1, 1, "FT", FECHA)
    assert r["ganador"] == "empate" and r["btts_real"] == 1 and r["over25_real"] == 0
    db_session.refresh(f_emp)
    assert f_emp.pick_correcto == 1 and f_emp.pick_claude_correcto == 0
    # 0.50 está entre 0.45 y 0.55: ni Over ni Under => no se califica
    assert f_emp.over25_correcto is None and f_emp.btts_correcto is None

    f_vis = _comparativo(db_session, "v1", pick_final="Boca Juniors", over25_pred=0.40, btts_pred=0.70)
    r = svc._guardar_resultado(db_session, "v1", "River Plate", "Boca Juniors", "Liga X", 0, 3, "FT", FECHA)
    assert r["ganador"] == "visitante" and r["over25_real"] == 1 and r["btts_real"] == 0
    db_session.refresh(f_vis)
    assert f_vis.pick_correcto == 1
    assert f_vis.over25_correcto == 0   # predijo Under (0.40<=0.45), salió Over
    assert f_vis.btts_correcto == 0     # predijo BTTS (0.70), no anotó el local


def test_guardar_resultado_califica_predicciones_partido_dia_y_es_idempotente(db_session):
    _comparativo(db_session, "i1", pick_final="Local")
    db_session.add(Prediccion(partido_id="i1", fuente="python", pick="Local", creado_en="2026-06-01 10:00:00"))
    db_session.add(Prediccion(partido_id="i1", fuente="ia", pick="Visitante", creado_en="2026-06-01 10:00:00"))
    db_session.add(PartidoDia(fecha=FECHA, match_id="i1", status="scheduled"))
    db_session.commit()

    args = (db_session, "i1", "River Plate", "Boca Juniors", "Liga X", 3, 1, "FT", FECHA)
    r1 = svc._guardar_resultado(*args)
    assert r1["comparativos"] == 1 and r1["predicciones"] == 2
    r2 = svc._guardar_resultado(*args)  # idempotente: no duplica ni vuelve a calificar el comparativo
    assert r2["comparativos"] == 0 and r2["ganador"] == "local"

    assert db_session.query(ResultadoPartido).filter_by(fixture_id="i1").count() == 1
    fila = db_session.query(ResultadoPartido).filter_by(fixture_id="i1").one()
    assert (fila.goles_local, fila.goles_visitante, fila.ganador) == (3, 1, "local")
    picks = {p.fuente: p.pick_correcto for p in db_session.query(Prediccion).filter_by(partido_id="i1")}
    assert picks == {"python": 1, "ia": 0}
    pd_ = db_session.get(PartidoDia, (FECHA, "i1"))
    assert pd_.status == "finished" and (pd_.goles_local, pd_.goles_visitante) == (3, 1) and pd_.cache_invalidado == 1


def test_guardar_resultado_actualiza_resultado_existente(db_session):
    svc._guardar_resultado(db_session, "u1", "A", "B", "L", 0, 0, "FT", FECHA)
    svc._guardar_resultado(db_session, "u1", "A", "B", "L2", 2, 0, "AET", FECHA)
    fila = db_session.query(ResultadoPartido).filter_by(fixture_id="u1").one()
    assert (fila.goles_local, fila.ganador, fila.status_api, fila.liga) == (2, "local", "AET", "L2")


# ---------------------------------------------------------------------------- actualizar_resultados
def test_actualizar_resultados_bsd_gana_sobre_apif_y_califica(db_session):
    _comparativo(db_session, "fxA", pick_final="Local")
    cliente = _ClienteFalso({
        "/events/": _Resp({"results": [_evento_bsd(gl=2, gv=0)]}),
        "/fixtures?ids=": _Resp({"response": []}),
    })
    out = _correr(svc.actualizar_resultados(db_session, cliente, ["fxA"], FECHA))
    assert out["resumen"] == {"total": 1, "actualizados": 1, "pendientes": 0, "cancelados": 0, "sin_datos": 0}
    assert not any("fixtures?ids=" in u for u in cliente.llamadas)  # BSD resolvió: api-football no se gasta
    assert db_session.query(AnalisisComparativo).filter_by(partido_id="fxA").one().pick_correcto == 1


@pytest.mark.parametrize("status,gl,gv,ganador", [("FT", 1, 0, "local"), ("AET", 1, 2, "visitante"), ("PEN", 2, 2, "empate")])
def test_actualizar_resultados_marcadores_terminados(db_session, monkeypatch, status, gl, gv, ganador):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({"response": [_fixture_apif(77, status, gl, gv)]})})
    out = _correr(svc.actualizar_resultados(db_session, cliente, ["77"], FECHA))
    assert out["resumen"]["actualizados"] == 1
    assert out["detalle"][0]["resultado"]["ganador"] == ganador
    assert db_session.query(ResultadoPartido).filter_by(fixture_id="77").one().status_api == status


def test_actualizar_resultados_partido_sin_terminar_queda_pendiente(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({"response": [_fixture_apif(5, "1H", None, None),
                                                                    _fixture_apif(6, "NS", None, None)]})})
    out = _correr(svc.actualizar_resultados(db_session, cliente, ["5", "6"], FECHA))
    assert out["resumen"]["pendientes"] == 2 and out["resumen"]["actualizados"] == 0
    assert db_session.query(ResultadoPartido).count() == 0


def test_actualizar_resultados_cancelado_marca_comparativo(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    fila = _comparativo(db_session, "c1")
    db_session.add(PartidoDia(fecha=FECHA, match_id="c1"))
    db_session.commit()
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({"response": [_fixture_apif(1, "PST", None, None)]})})
    # el id del fixture devuelto es "1": se alinea con el comparativo
    fila.partido_id = "1"
    db_session.add(PartidoDia(fecha=FECHA, match_id="1"))
    db_session.commit()
    out = _correr(svc.actualizar_resultados(db_session, cliente, ["1"], FECHA))
    assert out["resumen"]["cancelados"] == 1
    db_session.refresh(fila)
    assert fila.resultado_real == "CANC" and fila.status_partido == "PST"
    assert db_session.get(PartidoDia, (FECHA, "1")).cache_invalidado == 1


def test_actualizar_resultados_sin_datos_api_cuota_agotada_o_errors(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    for resp in (_Resp({}, 429), _Resp({"errors": {"requests": "rate limit"}, "response": []})):
        cliente = _ClienteFalso({"/fixtures?ids=": resp})
        out = _correr(svc.actualizar_resultados(db_session, cliente, ["99"], FECHA))
        assert out["detalle"] == [{"fixture_id": "99", "estado": "sin_datos_api"}]
        assert out["resumen"]["sin_datos"] == 1
    assert db_session.query(ResultadoPartido).count() == 0


def test_actualizar_resultados_ya_verificado_es_idempotente(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "")
    _comparativo(db_session, "42", pick_final="Local")
    cliente = _ClienteFalso({"/fixtures?ids=": _Resp({"response": [_fixture_apif(42, "FT", 1, 0)]})})
    primera = _correr(svc.actualizar_resultados(db_session, cliente, ["42"], FECHA))
    segunda = _correr(svc.actualizar_resultados(db_session, cliente, ["42"], FECHA))
    assert primera["detalle"][0]["resultado"]["comparativos"] == 1
    assert segunda["detalle"][0]["resultado"]["comparativos"] == 0  # ya tenía resultado_real
    assert db_session.query(ResultadoPartido).filter_by(fixture_id="42").count() == 1
    assert db_session.query(AnalisisComparativo).filter_by(partido_id="42").one().pick_correcto == 1


def test_actualizar_resultados_toma_pendientes_del_dia_para_buscar_en_bsd(db_session):
    _comparativo(db_session, "fxB", pick_final="Local")
    cliente = _ClienteFalso({"/events/": _Resp({"results": []}),
                             "/fixtures?ids=": _Resp({"response": []})})
    out = _correr(svc.actualizar_resultados(db_session, cliente, ["fxB"], FECHA))
    assert out["resumen"]["sin_datos"] == 1
    assert any("/events/" in u for u in cliente.llamadas)  # tenía local/visitante => probó BSD primero
