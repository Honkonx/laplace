"""Meta M2: motor, bot, agente, modelo e IA conectados en paralelo y en serie, sin que ninguno dependa de otro."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.ml.laplace import pronostico, servicio
from backend.api.services import agent_runtime_prompts, agent_tools, motor

ARGS = {"match_id": "1", "local": "A", "visitante": "B", "league": "L"}
CONSENSO = {"consenso": {"pick_final": "Local", "confianza_final": "MEDIA", "prob_ponderada": {"local": 0.5, "empate": 0.3, "visitante": 0.2}}}


def _modelo_ok():
    return {"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": ["total", "btts", "o25"], **pronostico.pronosticar(1.5, 1.0)}


def _correr(args=ARGS):
    return asyncio.run(agent_tools.ejecutar_herramienta_deportiva("sports.predict", args, authorization="Bearer x"))


def _parchear(monkeypatch, bot, modelo):
    async def post(path, payload, **k):
        r = modelo if path == "/api/v1/ml/predict" else bot
        if isinstance(r, BaseException):
            raise r
        return await r() if callable(r) else r

    monkeypatch.setattr(agent_tools, "_post", post)


def test_los_dos_responden_y_el_resumen_trae_ambos(monkeypatch):
    _parchear(monkeypatch, CONSENSO, _modelo_ok())
    r = _correr()
    assert r["resumen"]["pick"] == "Local" and r["resumen"]["modelo_laplace"]["marcador_mas_probable"]


def test_cae_el_modelo_y_el_bot_responde_igual(monkeypatch):
    _parchear(monkeypatch, CONSENSO, httpx.ConnectError("caído"))
    r = _correr()
    assert r["ok"] and r["resumen"]["pick"] == "Local" and r["resumen"]["modelo_laplace"] is None


def test_cae_el_bot_y_responde_el_modelo_y_lo_dice(monkeypatch):
    _parchear(monkeypatch, httpx.ConnectError("caído"), _modelo_ok())
    r = _correr()
    assert r["ok"] and r["prediction"] is None and r["resumen"]["bot_disponible"] is False
    texto = agent_runtime_prompts._texto_prediccion({"local": "A", "visitante": "B"}, r["resumen"])
    assert "el bot no respondió" in texto and "modelo Laplace" in texto and "estimación" in texto


def test_caen_el_bot_y_el_modelo_se_informa_el_error_del_bot(monkeypatch):
    _parchear(monkeypatch, httpx.ConnectError("bot caído"), httpx.ConnectError("modelo caído"))
    with pytest.raises(httpx.ConnectError, match="bot caído"):
        _correr()


def test_el_modelo_lento_no_retrasa_al_bot(monkeypatch):
    monkeypatch.setattr(agent_tools, "PLAZO_MODELO_SEGUNDOS", 0.05)

    async def lento():
        await asyncio.sleep(2)
        return _modelo_ok()

    _parchear(monkeypatch, CONSENSO, lento)
    inicio = asyncio.get_event_loop_policy().new_event_loop().time()
    r = _correr()
    assert r["resumen"]["pick"] == "Local" and r["resumen"]["modelo_laplace"] is None
    assert asyncio.get_event_loop_policy().new_event_loop().time() - inicio < 1.5


def test_get_odds_no_depende_del_modelo(monkeypatch):
    _parchear(monkeypatch, {"odds_info": {"1": 2.0}}, httpx.ConnectError("caído"))
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("sports.get_odds", ARGS, authorization="Bearer x"))
    assert r["odds"] == {"1": 2.0}


def test_el_motor_del_bot_responde_aunque_el_modelo_explote(monkeypatch):
    def rompe(*a, **k):
        raise RuntimeError("modelo roto")

    monkeypatch.setattr(servicio, "pronosticar_partido", rompe)
    r = motor.analizar_partido({"local": "A", "visitante": "B", "liga": "L", "partido_id": "x"})
    assert r["modelo_laplace"] is None and "consenso" in r and "modulos" in r


def test_el_modelo_sirve_aunque_el_motor_del_bot_no_exista(tmp_path, monkeypatch):
    """El servicio del modelo no importa el motor: con un artefacto vigente responde solo."""
    from backend.api.ml.laplace import entrenamiento, registro, simulacion

    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path)
    registro._cache_puntero.clear()
    art = entrenamiento.entrenar(simulacion.simular(5, n_equipos=8, temporadas=3)["partidos"], 10**9)
    import hashlib
    import json

    contenido = json.dumps(art, sort_keys=True)
    (tmp_path / "m.json").write_text(contenido, encoding="utf-8")
    (tmp_path / "vigente.json").write_text(json.dumps({"id": 1, "nombre": "m", "version": "v", "estado": "activo", "ruta": str(tmp_path / "m.json"),
                                                       "sha256": hashlib.sha256(contenido.encode()).hexdigest()}), encoding="utf-8")
    equipo = next(iter(art["estado"]["elo"]))
    otro = [e for e in art["estado"]["elo"] if e != equipo][0]
    assert servicio.pronosticar_partido(None, {"local": equipo, "visitante": otro})["fuente"] == "modelo_laplace"
    registro._cache_puntero.clear()


# ---------- M4: endpoint interno con clave y fidelidad de la redacción de la IA ----------
@pytest.fixture()
def cliente_interno(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.api.db.session import Base, get_db
    from backend.api.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()

    def _db():
        yield s

    app.dependency_overrides[get_db] = _db
    app.state.http_client = httpx.AsyncClient()
    yield TestClient(app), s
    app.dependency_overrides.clear()
    s.close()


def test_el_endpoint_interno_no_existe_sin_clave_configurada(cliente_interno, monkeypatch):
    from backend.api.core.config import settings

    monkeypatch.setattr(settings, "ML_API_KEY", "")
    c, _ = cliente_interno
    assert c.post("/api/v1/ml/predict/interno", json={"local": "A", "visitante": "B"}, headers={"x-laplace-ml-key": "x"}).status_code == 404


def test_el_endpoint_interno_rechaza_una_clave_mala_y_acepta_la_buena(cliente_interno, monkeypatch):
    from backend.api.core.config import settings
    from backend.api.services import modelo_historico

    monkeypatch.setattr(settings, "ML_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(modelo_historico, "analizar", lambda d: {"ok": True, "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "lambda_local": 1.5, "lambda_visit": 1.0})
    c, _ = cliente_interno
    cuerpo = {"local": "A", "visitante": "B", "partido_id": "fx9"}
    assert c.post("/api/v1/ml/predict/interno", json=cuerpo).status_code == 401
    assert c.post("/api/v1/ml/predict/interno", json=cuerpo, headers={"x-laplace-ml-key": "otra"}).status_code == 401
    r = c.post("/api/v1/ml/predict/interno", json=cuerpo, headers={"x-laplace-ml-key": "clave-de-prueba"})
    assert r.status_code == 200 and r.json()["ok"] and "clave-de-prueba" not in r.text


def test_el_endpoint_interno_deja_rastro_con_partido_id_cuando_hay_modelo_activo(cliente_interno, monkeypatch, tmp_path):
    from sqlalchemy import select

    from backend.api.core.config import settings
    from backend.api.ml.laplace import entrenamiento, registro, simulacion
    from backend.api.models.ml_modelo import MlPrediccion

    monkeypatch.setattr(settings, "ML_API_KEY", "k")
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path)
    c, db = cliente_interno
    partidos = simulacion.simular(5, n_equipos=8, temporadas=3)["partidos"]
    mid = registro.registrar_modelo(db, "m", "v", entrenamiento.entrenar(partidos, 10**9), None, None)
    db.get(registro.MlModelo, mid).estado = "activo"
    db.commit()
    p = partidos[0]
    r = c.post("/api/v1/ml/predict/interno", json={"local": p["local"], "visitante": p["visitante"], "partido_id": "fx7"}, headers={"x-laplace-ml-key": "k"})
    assert r.json()["fuente"] == "modelo_laplace"
    assert db.scalars(select(MlPrediccion)).one().partido_id == "fx7"


def test_la_redaccion_de_la_ia_puede_citar_las_cifras_del_modelo_pero_no_inventar():
    resumen = {"pick": "Local", "modelo_laplace": servicio.resumen_para_consumidores({"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": ["total", "btts", "o25"], **pronostico.pronosticar(1.6, 1.1)})}
    base = agent_runtime_prompts._texto_prediccion({"local": "A", "visitante": "B"}, {**resumen, "confianza": "MEDIA"})
    cifra = round(resumen["modelo_laplace"]["p1x2"]["local"] * 100, 1)
    assert str(cifra).replace(".", ",") in base or str(cifra) in base
    assert agent_runtime_prompts._redaccion_fiel(f"Pick Local; el modelo da {cifra} % al local.", resumen, base)
    assert not agent_runtime_prompts._redaccion_fiel("Pick Local; el modelo da 91,3 % al local.", resumen, base)


def test_el_telegram_del_agente_muestra_la_linea_del_modelo_solo_si_hay_modelo():
    from backend.api.bot import laplace_agent_bot_formato as fmt

    modelo = servicio.resumen_para_consumidores({"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": ["total", "btts", "o25"], **pronostico.pronosticar(1.6, 1.1)})
    base = {"pick": "Local", "confianza": "MEDIA", "prob_ponderada_pct": {"local": 50, "empate": 30, "visitante": 20}, "modulos_usados": ["poisson"]}
    partido = {"local": "A", "visitante": "B", "liga": "L"}
    con = fmt.formatear_prediccion(partido, {**base, "modelo_laplace": modelo})
    assert "Modelo Laplace:" in con and modelo["marcador_mas_probable"] in con and "publicar" not in con.lower()
    assert "Modelo Laplace" not in fmt.formatear_prediccion(partido, base)
