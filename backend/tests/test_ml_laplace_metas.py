"""Metas del modelo Laplace: variante del laboratorio, reentreno semanal por subproceso y sus guardas de promoción."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base
from backend.api.ml.laplace import job_reentreno, servicio
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.services import laboratorio_pronosticos as lab


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    lab.asegurar_experimentos_base(s)
    s.commit()
    yield s
    s.close()


def _salida(degradado=False, ok=True):
    from backend.api.ml.laplace import pronostico

    return {"ok": ok, "degradado": degradado, "modelo": {"version": "v9"}, **pronostico.pronosticar(1.6, 1.1)}


def _comun():
    return dict(partido_id="p1", fecha_partido="2999-01-01", local="A", visitante="B", liga="L", hora_kickoff="2999-01-01T20:00:00", datos={})


def test_el_laboratorio_registra_la_variante_laplace_modelo(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida())
    lab.registrar_modelo_laplace(db, **_comun())
    db.commit()
    fila = db.query(PronosticoExperimental).filter_by(variante="laplace_modelo").one()
    assert fila.pick in {"Local", "Empate", "Visitante"} and fila.modelo_version.endswith(":v9")
    assert abs(fila.prob_local + fila.prob_empate + fila.prob_visitante - 1) < 1e-6


def test_no_registra_dos_veces_el_mismo_partido(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida())
    lab.registrar_modelo_laplace(db, **_comun())
    db.commit()
    lab.registrar_modelo_laplace(db, **_comun())
    db.commit()
    assert db.query(PronosticoExperimental).filter_by(variante="laplace_modelo").count() == 1


def test_no_registra_si_respondio_el_respaldo_o_el_modelo_fallo(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida(degradado=True))
    lab.registrar_modelo_laplace(db, **_comun())
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida(ok=False))
    lab.registrar_modelo_laplace(db, **_comun())

    def rompe(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(servicio, "pronosticar_partido", rompe)
    lab.registrar_modelo_laplace(db, **_comun())
    db.commit()
    assert db.query(PronosticoExperimental).filter_by(variante="laplace_modelo").count() == 0


def test_rechaza_un_corte_posterior_al_inicio_del_partido(db, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: _salida())
    datos = {**_comun(), "hora_kickoff": "2000-01-01T20:00:00"}
    with pytest.raises(ValueError, match="anterior"):
        lab.registrar_modelo_laplace(db, **datos)


def test_el_experimento_base_existe_y_no_permite_consenso(db):
    from backend.api.models.predicciones import ExperimentoPronostico

    e = db.query(ExperimentoPronostico).filter_by(codigo="laplace_modelo").one()
    assert e.estado == "sombra" and e.permite_consenso == 0


# ---------- reentreno por subproceso ----------
def _proc(codigo=0, salida="", error=""):
    return SimpleNamespace(returncode=codigo, stdout=salida, stderr=error)


def test_el_reentreno_devuelve_el_resumen_del_subproceso(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("x", encoding="utf-8")
    llamadas = []

    def ejecutar(cmd, **k):
        llamadas.append(cmd)
        return _proc(0) if "-c" in cmd else _proc(0, "ruido\n" + json.dumps({"ok": True, "promovido": True, "detalle": "listo"}))

    r = job_reentreno.ejecutar_reentreno(ejecutar=ejecutar, script=script)
    assert r["ok"] and r["promovido"] and any("reentrenar" in c for c in llamadas[-1])


@pytest.mark.parametrize("caso,texto", [("sin_numpy", "numpy"), ("codigo", "código 3"), ("json", "legible"), ("timeout", "excedió"), ("oserror", "lanzar")])
def test_el_reentreno_nunca_lanza_y_explica_el_fallo(tmp_path, caso, texto):
    script = tmp_path / "s.py"
    script.write_text("x", encoding="utf-8")

    def ejecutar(cmd, **k):
        if caso == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        if caso == "oserror":
            raise OSError("x")
        if "-c" in cmd:
            return _proc(1 if caso == "sin_numpy" else 0)
        return _proc(3, "", "boom") if caso == "codigo" else _proc(0, "sin json")

    r = job_reentreno.ejecutar_reentreno(ejecutar=ejecutar, script=script)
    assert r["ok"] is False and texto in r["detalle"]


def test_el_reentreno_falla_con_motivo_si_no_existe_el_script(tmp_path):
    assert "no existe" in job_reentreno.ejecutar_reentreno(script=tmp_path / "nada.py")["detalle"]


def test_el_reentreno_se_puede_apagar(monkeypatch):
    monkeypatch.setenv("LAPLACE_REENTRENO_AUTOMATICO", "0")
    assert job_reentreno.reentreno_activo() is False
    monkeypatch.setenv("LAPLACE_REENTRENO_AUTOMATICO", "1")
    assert job_reentreno.reentreno_activo() is True


# ---------- guardas de promoción del reentreno ----------
@pytest.fixture()
def reentreno_env(tmp_path, monkeypatch):
    """Base en memoria, artefactos en tmp y un histórico sintético de dos ligas en lugar de los CSV reales."""
    from backend.api.db import session as sesion
    from backend.api.ml import datos
    from backend.api.ml.laplace import registro, simulacion
    from backend.scripts import modelo_laplace as cli

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sesion, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path / "art")
    partidos = []
    for semilla, cod in ((21, "AAA"), (22, "BBB")):
        for p in simulacion.simular(semilla, n_equipos=12, temporadas=4)["partidos"]:
            p["liga"] = cod
            p["ap_prom"] = tuple(p["ap_prom"])
            partidos.append(p)
    # cuatro temporadas desde 2020-08: el corte fijo de evaluación (2023-07-01) deja tres para entrenar y una para probar
    monkeypatch.setattr(datos, "cargar_partidos_con_vivo", lambda: (sorted(partidos, key=lambda x: x["dia"]), {"vivos_nuevos": {}}))
    monkeypatch.setattr(registro, "MEJORA_MIN_HISTORICA", 0.0)
    monkeypatch.setattr(registro, "MIN_CASOS_HISTORICOS", 100)  # el mundo sintético de prueba es chico
    return SimpleNamespace(cli=cli, registro=registro, sesion=sesion)


def test_el_primer_reentreno_queda_en_sombra_sin_auto(reentreno_env, monkeypatch):
    r = reentreno_env.cli.reentrenar(auto=False)
    assert r["ok"] and r["promovido"] is False and r["modelo_id"] == 1


def test_con_auto_se_rechaza_si_hay_menos_de_40_ligas_y_queda_en_sombra(reentreno_env):
    r = reentreno_env.cli.reentrenar(auto=True)
    assert r["promovido"] is False and "solo 2 ligas" in r["detalle"]
    with reentreno_env.sesion.SessionLocal() as db:
        assert reentreno_env.registro.modelo_vigente(db) is None


def test_con_auto_promueve_cuando_pasa_todas_las_guardas(reentreno_env, monkeypatch):
    import backend.scripts.modelo_laplace as cli

    original = cli.entrenamiento.entrenar_jerarquico

    def con_muchas_ligas(por_liga, corte, especializar=False, hiper=None, con_goles=True):
        art = original(por_liga, corte, especializar, hiper, con_goles)
        if especializar:  # la medición usa las ligas reales; solo el modelo FINAL aparenta tener 45
            return art
        base = next(iter(art["ligas"].values()))
        art["ligas"] = {f"L{i:02d}": base for i in range(45)}
        return art

    monkeypatch.setattr(cli.entrenamiento, "entrenar_jerarquico", con_muchas_ligas)
    r = cli.reentrenar(auto=True)
    assert r["promovido"] is True
    with reentreno_env.sesion.SessionLocal() as db:
        activo = reentreno_env.registro.modelo_vigente(db)
        assert activo is not None and activo.promovido_por == "reentreno-automatico"
    reentreno_env.registro._cache_puntero.clear()


def test_un_segundo_reentreno_el_mismo_dia_no_duplica(reentreno_env):
    reentreno_env.cli.reentrenar(auto=False)
    with reentreno_env.sesion.SessionLocal() as db:
        m = db.get(reentreno_env.registro.MlModelo, 1)
        m.estado = "activo"
        db.commit()
    r = reentreno_env.cli.reentrenar(auto=False)
    assert "ya existe" in r["detalle"]
