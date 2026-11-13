"""Memoria del modelo en la base (`ml/laplace/estado_vivo.py`): el estado por equipo se reconstruye con todo el historial, el servicio lo usa por encima del del artefacto, un equipo recién llegado entra y
cualquier falla del accesorio nunca rompe un pronóstico."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.db.session import Base
from backend.api.ml.laplace import entrenamiento, estado_vivo, registro, servicio, simulacion
from backend.api.models.ml_modelo import MlEstadoVivo


@pytest.fixture(autouse=True)
def _limpio(monkeypatch, tmp_path):
    monkeypatch.setattr(registro, "RUTA_ARTEFACTOS", tmp_path / "artefactos")
    estado_vivo.limpiar_cache()
    yield
    estado_vivo.limpiar_cache()


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine)
    monkeypatch.setattr("backend.api.db.session.SessionLocal", fabrica)  # `estado_de` abre su propia sesión sobre esta misma base
    s = fabrica()
    try:
        yield s
    finally:
        s.close()


def _por_liga():
    a = simulacion.simular(11, n_equipos=10, temporadas=3)["partidos"]
    b = simulacion.simular(12, n_equipos=10, temporadas=3)["partidos"]
    for ps, cod in ((a, "AAA"), (b, "BBB")):
        for p in ps:
            p["liga"] = cod
    return {"AAA": a, "BBB": b}


@pytest.fixture()
def modelo_activo(db):
    por = _por_liga()
    dias = sorted(p["dia"] for ps in por.values() for p in ps)
    corte = dias[int(len(dias) * 0.8)]  # el 20 % más reciente queda DESPUÉS del corte del artefacto
    art = entrenamiento.entrenar_jerarquico(por, corte)
    mid = registro.registrar_modelo(db, "jer", "v1", art, None, None)
    db.get(registro.MlModelo, mid).estado = "activo"
    db.commit()
    todos = [p for ps in por.values() for p in ps]
    return {"id": mid, "art": art, "corte": corte, "todos": todos, "por": por}


def test_el_estado_reconstruido_hasta_el_corte_es_el_mismo_que_el_del_artefacto(db, modelo_activo):
    """Misma recurrencia que el entrenamiento: con los datos anteriores al corte, el estado de la base coincide con el del artefacto (no puede divergir)."""
    antes = [p for p in modelo_activo["todos"] if p["dia"] < modelo_activo["corte"]]
    r = estado_vivo.reconstruir(db, partidos=antes)
    assert r["ok"] and r["ligas"] == 2 and r["partidos"] == len(antes)
    for liga in ("AAA", "BBB"):
        guardado = estado_vivo.estado_de(modelo_activo["id"], liga)
        del_artefacto = entrenamiento.EstadoLiga.de_dict(modelo_activo["art"]["ligas"][liga]["estado"])
        assert guardado.total_partidos == del_artefacto.total_partidos
        assert guardado.elo == pytest.approx(del_artefacto.elo) and guardado.gf == pytest.approx(del_artefacto.gf) and guardado.n == del_artefacto.n


def test_con_los_resultados_nuevos_el_estado_avanza_y_el_servicio_usa_el_de_la_base(db, modelo_activo, monkeypatch):
    r = estado_vivo.reconstruir(db, partidos=modelo_activo["todos"])
    assert r["ok"] and db.query(MlEstadoVivo).count() == 2
    viejo = entrenamiento.EstadoLiga.de_dict(modelo_activo["art"]["ligas"]["AAA"]["estado"])
    nuevo = estado_vivo.estado_de(modelo_activo["id"], "AAA")
    assert nuevo.total_partidos > viejo.total_partidos and nuevo.elo != viejo.elo, "los resultados posteriores al corte ya cuentan"
    e = modelo_activo["por"]["AAA"][0]
    monkeypatch.setattr(servicio, "_resolver_real", lambda d, modelo_id=None: ("AAA", e["local"], e["visitante"]))
    salida = servicio.pronosticar_partido(db, {"local": "x", "visitante": "y", "liga": "Liga A"})
    esperado = entrenamiento.predecir_liga(modelo_activo["art"], "AAA", e["local"], e["visitante"], estado=nuevo)
    assert salida["ok"] and salida["p1x2"]["local"] == pytest.approx(esperado["p1x2"][0]), "el pronóstico usa el estado de la base, no el del artefacto"


def test_un_equipo_recien_llegado_con_suficientes_partidos_entra_y_el_servicio_lo_resuelve(db, modelo_activo, monkeypatch):
    base = modelo_activo["por"]["AAA"]
    rivales = sorted({p["local"] for p in base})[:6]
    ultimo = max(p["dia"] for p in base)
    nuevos = [{**base[0], "dia": ultimo + 1 + i, "local": "Nuevo FC", "visitante": rivales[i], "gl": 2, "gv": 1, "resultado": "H", "liga": "AAA"} for i in range(6)]
    r = estado_vivo.reconstruir(db, partidos=modelo_activo["todos"] + nuevos)
    assert r["equipos_nuevos"] == 1
    estado = estado_vivo.estado_de(modelo_activo["id"], "AAA")
    assert estado.conoce("Nuevo FC"), "con 6 partidos ya no es «sin historial»"

    from backend.api.services import modelo_historico

    monkeypatch.setattr(modelo_historico, "_resolver", lambda d: (None, "equipo fuera del histórico"))
    monkeypatch.setattr(modelo_historico, "_resolver_equipo_nuevo", lambda d: ("AAA", None, rivales[0], None))
    assert servicio._resolver_real({"local": rivales[0], "visitante": "Nuevo FC"}, modelo_activo["id"]) == ("AAA", rivales[0], "Nuevo FC")
    assert servicio._resolver_real({"local": rivales[0], "visitante": "Nuevo FC"}, None) is None, "sin memoria en la base sigue sin resolverse"


def test_el_nombre_de_un_equipo_nuevo_se_guarda_sin_acentos():
    assert estado_vivo.plano("  São   Bernardo ") == "Sao Bernardo" and estado_vivo.plano("") == "" and estado_vivo.plano(None) == ""


def test_sin_tabla_sin_modelo_o_con_modelo_en_sombra_el_accesorio_no_rompe_nada(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)  # sin tablas
    monkeypatch.setattr("backend.api.db.session.SessionLocal", sessionmaker(bind=engine))
    assert estado_vivo.estado_de(1, "AAA") is None and estado_vivo.estado_de(None, "AAA") is None
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    assert estado_vivo.reconstruir(s, partidos=[])["ok"] is False, "sin un modelo activo no hay estado que reconstruir"


def test_la_migracion_real_crea_la_tabla_con_clave_unica_por_modelo_y_liga(base_migrada):
    fabrica = base_migrada("head")
    with fabrica() as s:
        s.add(MlEstadoVivo(modelo_id=1, liga="AAA", estado_json="{}", hasta_dia=1, actualizado_en="2026-11-12 10:00:00"))
        s.commit()
        s.add(MlEstadoVivo(modelo_id=1, liga="AAA", estado_json="{}", hasta_dia=2, actualizado_en="2026-11-12 11:00:00"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_el_trabajo_diario_respeta_el_interruptor_y_una_falla_no_lo_rompe(monkeypatch):
    from backend.api import main
    from backend.api.core.config import settings

    llamadas = []
    monkeypatch.setattr(estado_vivo, "reconstruir", lambda db, partidos=None: llamadas.append(1) or {"ok": True})
    monkeypatch.setattr(settings, "ESTADO_VIVO_AUTOMATICO", False)
    asyncio.run(main._job_estado_vivo())
    assert llamadas == []
    monkeypatch.setattr(settings, "ESTADO_VIVO_AUTOMATICO", True)
    monkeypatch.setattr(main, "SessionLocal", lambda: _SesionFalsa())
    asyncio.run(main._job_estado_vivo())
    assert llamadas == [1]
    monkeypatch.setattr(estado_vivo, "reconstruir", lambda db, partidos=None: (_ for _ in ()).throw(RuntimeError("base caída")))
    asyncio.run(main._job_estado_vivo())  # no lanza


class _SesionFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
