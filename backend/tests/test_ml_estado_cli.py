"""`modelo_laplace.py estado`: foto de solo lectura de la evidencia del modelo."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db import session as sesion
from backend.api.db.session import Base
from backend.api.ml.laplace import entrenamiento, registro, simulacion
from backend.api.models.predicciones import PronosticoExperimental
from backend.scripts import modelo_laplace as cli


def _entorno(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sesion, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path)
    return sesion.SessionLocal


def test_estado_sin_nada_devuelve_ceros_y_lo_que_falta(tmp_path, monkeypatch):
    _entorno(tmp_path, monkeypatch)
    e = cli.estado()
    assert e["modelos"] == [] and e["laboratorio_laplace_modelo"] == {"observaciones": 0, "con_resultado": 0, "log_loss_medio": None, "falta_para_exploratoria": 50, "falta_para_promocion": 200}


def test_estado_cuenta_la_evidencia_en_vivo_del_laboratorio(tmp_path, monkeypatch):
    Sesion = _entorno(tmp_path, monkeypatch)
    with Sesion() as db:
        ps = simulacion.simular(5, n_equipos=8, temporadas=3)["partidos"]
        registro.registrar_modelo(db, "m", "v", entrenamiento.entrenar(ps, 10**9), None, None)
        for i in range(3):
            db.add(PronosticoExperimental(experimento_codigo="laplace_modelo", partido_id=f"p{i}", fecha_partido="2026-11-10", local="A", visitante="B", fuente="laplace", variante="laplace_modelo",
                                          corte_datos_en="2026-11-10T00:00:00", creado_en="2026-11-10", resultado_real="1-0" if i < 2 else None, log_loss=1.0 if i < 2 else None))
        db.commit()
    e = cli.estado()
    assert e["modelos"][0]["estado"] == "sombra"
    lab = e["laboratorio_laplace_modelo"]
    assert lab["observaciones"] == 3 and lab["con_resultado"] == 2 and lab["falta_para_exploratoria"] == 48 and lab["falta_para_promocion"] == 198 and lab["log_loss_medio"] == 1.0
