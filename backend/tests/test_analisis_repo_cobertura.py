"""test_analisis_repo_cobertura.py — cobertura de `db/analisis_repo.py`: caché de consenso, guardado de
predicciones/comparativos/multimodelo, stats y winrate, historial de la app, top picks y
`verificar_partido_completo`. BD en memoria (fixture `db_session`), sin red."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.api.core.config import settings
from backend.api.db import analisis_repo as repo
from backend.api.models.jobs import Job
from backend.api.models.partidos import RecomendacionDia
from backend.api.models.predicciones import (
    AnalisisComparativo, AnalisisIndividual, AnalisisModulo, CacheConsenso, CachePrediccion, Prediccion,
)
from backend.api.models.usuarios import Usuario, UsoDiarioApp

AHORA = repo._now_str()
FUTURO = (datetime.utcnow() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
PASADO = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
HOY = datetime.now().strftime("%Y-%m-%d")


def _individual(db, pid, pick, fuente="python", score=50, creado="2026-11-01 10:00:00"):
    db.add(AnalisisIndividual(partido_id=pid, pick_final=pick, confianza="MEDIA", score_final=score,
                              texto_completo=f"texto {pick} {score}", fuente=fuente, creado_en=creado))
    db.commit()


def _job(db, job_id, match="m1", device="dev1", status="listo", **extra):
    campos = dict(job_id=job_id, match_id=match, fecha_partido=HOY, chat_id="c", origen="app",
                  status=status, device_id_app=device, creado_en=AHORA, completado_en=AHORA)
    campos.update(extra)
    db.add(Job(**campos))
    db.commit()


def _comparativo(db, pid="m1", fecha=HOY, **extra):
    campos = dict(partido_id=pid, fecha=fecha, local="Lanus", visitante="Banfield", liga="Liga X",
                  pick_final="Local", confianza="ALTA", score_final=70, creado_en=AHORA)
    campos.update(extra)
    fila = AnalisisComparativo(**campos)
    db.add(fila)
    db.commit()
    return fila


# ------------------------------------------------------------------ individual y caché de consenso
def test_guardar_analisis_individual_cuenta_los_del_partido(db_session):
    repo.guardar_analisis_individual(db_session, "p1", "Local", "ALTA", 80, "t1")
    r = repo.guardar_analisis_individual(db_session, "p1", "Local", "ALTA", 75, "t2", fuente="ia")
    assert r == {"guardado": True, "total_analisis": 2, "partido_id": "p1"}


def test_activar_consenso_requisitos(db_session):
    assert repo.activar_cache_consenso(db_session, "p")["activado"] is False  # 0/2
    _individual(db_session, "p", "Local", creado="2026-11-01 10:00:01")
    assert "Solo 1/2" in repo.activar_cache_consenso(db_session, "p")["razon"]
    _individual(db_session, "p", "Visitante", creado="2026-11-01 10:00:02")
    r = repo.activar_cache_consenso(db_session, "p")
    assert r["activado"] is False and "Picks divergen" in r["razon"]


def test_activar_consenso_python_crea_y_luego_actualiza(db_session):
    _individual(db_session, "p", "Local", score=40, creado="2026-11-01 10:00:01")
    _individual(db_session, "p", "Local", score=90, creado="2026-11-01 10:00:02")
    r = repo.activar_cache_consenso(db_session, "p", max_usos=2, horas_ttl=1)
    assert r["activado"] and r["tipo_consenso"] == "python" and r["min_requerido"] == 2
    cc = db_session.query(CacheConsenso).filter_by(partido_id="p").one()
    assert cc.texto_consenso == "texto Local 90"  # el de mayor score
    cc.usos = 2
    db_session.commit()
    repo.activar_cache_consenso(db_session, "p", max_usos=7)
    db_session.refresh(cc)
    assert db_session.query(CacheConsenso).filter_by(partido_id="p").count() == 1
    assert (cc.usos, cc.max_usos) == (0, 7)


def test_activar_consenso_mixto_e_ia_piden_tres(db_session):
    _individual(db_session, "mx", "Local", "python", creado="2026-11-01 10:00:01")
    _individual(db_session, "mx", "Local", "ia", creado="2026-11-01 10:00:02")
    assert "mixto" in repo.activar_cache_consenso(db_session, "mx")["razon"]
    _individual(db_session, "mx", "Local", "python", creado="2026-11-01 10:00:03")
    assert repo.activar_cache_consenso(db_session, "mx")["tipo_consenso"] == "mixto"

    for i in range(2):
        _individual(db_session, "ia", "Empate", "gemini", creado=f"2026-11-01 10:00:0{i}")
    assert "ia" in repo.activar_cache_consenso(db_session, "ia")["razon"]


def test_verificar_consenso_cache_hit_job_en_vuelo_y_generar(db_session):
    db_session.add(CacheConsenso(partido_id="h", pick_consenso="Local", texto_consenso="x", total_analisis=2,
                                 usos=0, max_usos=2, expira_en=FUTURO, creado_en=AHORA, tipo_consenso="python"))
    db_session.commit()
    r1 = repo.verificar_consenso_cache(db_session, "h")
    assert r1["cache_consenso_hit"] and r1["usos_restantes"] == 1 and r1["pick_consenso"] == "Local"
    r2 = repo.verificar_consenso_cache(db_session, "h")
    assert r2["cache_consenso_hit"] and r2["usos_restantes"] == 0
    r3 = repo.verificar_consenso_cache(db_session, "h")  # agotó max_usos
    assert r3["cache_consenso_hit"] is False and r3["debe_generar"] is True

    _job(db_session, "j1", match="enviuelo", status="procesando")
    r = repo.verificar_consenso_cache(db_session, "enviuelo")
    assert r["job_en_vuelo"] is True and r["debe_generar"] is False


def test_verificar_consenso_cache_expirado_no_sirve(db_session):
    db_session.add(CacheConsenso(partido_id="e", pick_consenso="Local", texto_consenso="x", total_analisis=2,
                                 usos=0, max_usos=5, expira_en=PASADO, creado_en=AHORA, tipo_consenso="python"))
    db_session.commit()
    assert repo.verificar_consenso_cache(db_session, "e")["debe_generar"] is True


# ------------------------------------------------------------------ predicción, caché genérica
def test_guardar_prediccion_marca_job_listo(db_session):
    _job(db_session, "jp", match="mp", status="procesando", completado_en=None)
    assert repo.guardar_prediccion(db_session, "mp", "python", "Local", "ALTA", 80, "r", "t", job_id="jp") == {"guardado": True}
    job = db_session.query(Job).filter_by(job_id="jp").one()
    assert job.status == "listo" and job.completado_en
    repo.guardar_prediccion(db_session, "mp", "ia", "Local", "ALTA", 80, "r", "t", job_id="no_existe")
    assert db_session.query(Prediccion).filter_by(partido_id="mp").count() == 2


def test_guardar_cache_y_verificar_cache(db_session):
    import hashlib

    h = hashlib.md5("m9" "2026-11-01".encode()).hexdigest()
    r = repo.guardar_cache(db_session, h, '{"a":1}', "m9")
    assert r["hash"] == h
    repo.guardar_cache(db_session, h, '{"a":2}', "m9")  # upsert
    assert db_session.query(CachePrediccion).count() == 1
    hit = repo.verificar_cache(db_session, "m9", "2026-11-01")
    assert hit == {"cache_hit": True, "respuesta_json": '{"a":2}', "hash": h}
    assert db_session.query(CachePrediccion).one().hits == 1
    assert repo.verificar_cache(db_session, "otro", "x")["cache_hit"] is False
    assert "match_id vacío" in repo.verificar_cache(db_session, "")["error_debug"]


def test_verificar_cache_expirada_no_es_hit(db_session):
    import hashlib

    h = hashlib.md5(b"m8").hexdigest()
    db_session.add(CachePrediccion(input_hash=h, respuesta_json="{}", partido_id="m8", expira_en=PASADO,
                                   hits=0, creado_en=AHORA))
    db_session.commit()
    assert repo.verificar_cache(db_session, "m8")["cache_hit"] is False


# ------------------------------------------------------------------ comparativos
def test_existe_comparativo(db_session):
    _comparativo(db_session, "c1", fecha="2026-11-01")
    assert repo.existe_comparativo(db_session, "c1", "2026-11-01") is True
    assert repo.existe_comparativo(db_session, "c1", "2026-11-02") is False


def test_guardar_comparativo_convierte_tipos_y_aplica_defaults(db_session):
    assert repo.guardar_comparativo(db_session, partido_id=123, local="A", visitante="B", pick_final="Local",
                                    prob_local_py="0.5", score_py="60", fuentes_disponibles=3) == {"guardado": True}
    f = db_session.query(AnalisisComparativo).one()
    assert (f.partido_id, f.prob_local_py, f.score_py, f.fuentes_disp) == ("123", 0.5, 60, 3)
    assert (f.peso_python, f.peso_ia, f.fecha) == (0.5, 0.5, HOY)


def test_guardar_analisis_multimodelo_inserta_comparativo_y_modulos(db_session):
    r = repo.guardar_analisis_multimodelo(
        db_session, partido_id="mm", local="A", visitante="B", liga="L", pick_python="Local", score_py=55,
        pick_final="Local", confianza="ALTA", consenso_nivel="COINCIDEN", total_modulos=4, coinciden_modulos=3,
        over25_pred="0.61", btts_pred=0.4, bloque_claude_json={"k": "ñ"}, pick_externo_detalle={"x": 1},
        job_id="jx", fuente_externo="odds", hora_kickoff="20:00",
        modulos_data=[{"modulo": "poisson", "pick": "Local", "datos_json": {"l": 1.2}},
                      {"modulo": "forma", "pick": "Empate"}, {"sin": "modulo"}, "basura"],
    )
    assert r["modulos_insertados"] == 2 and r["guardado"] is True
    f = db_session.query(AnalisisComparativo).one()
    assert f.pick_python == "Local" and f.score_poisson == 55 and f.consenso == "COINCIDEN"
    assert f.over25_pred == 0.61 and json.loads(f.bloque_claude_json) == {"k": "ñ"}
    assert json.loads(f.pick_externo_detalle) == {"x": 1} and f.fuentes_disp == 4
    mods = {m.modulo: m for m in db_session.query(AnalisisModulo)}
    assert json.loads(mods["poisson"].datos_json) == {"l": 1.2} and mods["poisson"].job_id == "jx"
    assert mods["forma"].datos_json is None


def test_guardar_analisis_multimodelo_exige_partido_id(db_session):
    with pytest.raises(ValueError):
        repo.guardar_analisis_multimodelo(db_session, local="A")
    assert db_session.query(AnalisisComparativo).count() == 0


# ------------------------------------------------------------------ stats / winrate
def test_leer_stats_cuenta_predicciones_y_jobs(db_session):
    for conf in ("ALTA", "ALTA", "MEDIA", "BAJA"):
        db_session.add(Prediccion(partido_id="p", fuente="python", pick="L", confianza=conf, creado_en=AHORA))
    db_session.commit()
    _job(db_session, "a", status="listo")
    _job(db_session, "b", status="error")
    _job(db_session, "c", status="pendiente")
    s = repo.leer_stats(db_session)
    assert s["predicciones"] == {"total": 4, "alta": 2, "media": 1, "baja": 1}
    assert s["jobs"] == {"completados": 1, "errores": 1, "pendientes": 1}


def test_leer_stats_aciertos_winrate_por_fuente_y_por_confianza(db_session):
    for fuente, correctos in (("python", [1, 1, 0, None]), ("ia", [0])):
        for c in correctos:
            db_session.add(Prediccion(partido_id="p", fuente=fuente, pick="L", creado_en=AHORA, pick_correcto=c))
    db_session.commit()
    _comparativo(db_session, "w1", pick_correcto=1, confianza="ALTA", consenso="COINCIDEN")
    _comparativo(db_session, "w2", pick_correcto=0, confianza="ALTA", consenso="COINCIDEN")
    _comparativo(db_session, "w3", pick_correcto=1, confianza="MEDIA")
    _comparativo(db_session, "w4", pick_correcto=None, confianza="ALTA")  # sin verificar: no cuenta
    _comparativo(db_session, "w5", pick_correcto=1, creado_en="2026-01-01 00:00:00")  # motor anterior al corte

    s = repo.leer_stats_aciertos(db_session, dias=30)
    por = {f["fuente"]: f for f in s["por_fuente"]}
    assert por["python"] == {"fuente": "python", "total": 4, "evaluados": 3, "aciertos": 2, "winrate": 66.7}
    assert por["ia"]["winrate"] == 0.0
    pf = s["pick_final"]
    assert (pf["total"], pf["aciertos"], pf["winrate"]) == (3, 2, 66.7)
    assert pf["alta_winrate"] == 50.0 and pf["media_winrate"] == 100.0 and pf["consenso_winrate"] == 50.0


def test_leer_stats_aciertos_sin_datos_devuelve_none_no_cero(db_session):
    s = repo.leer_stats_aciertos(db_session)
    assert s["por_fuente"] == [] and s["pick_final"]["winrate"] is None
    assert s["pick_final"]["alta_winrate"] is None and s["periodo_dias"] == 30


# ------------------------------------------------------------------ historial app
def test_leer_historial_app_resultado_y_fuente(db_session):
    _comparativo(db_session, "ok", pick_correcto=1)
    _comparativo(db_session, "mal", pick_correcto=0)
    _comparativo(db_session, "real", resultado_real="CANC")
    _job(db_session, "j1", match="ok", completado_en="2026-11-01 12:00:01",
         resultado_app=json.dumps({"fuente": "ia", "pick": "X"}))
    _job(db_session, "j2", match="mal", completado_en="2026-11-01 12:00:02", local_app="Mi Local")
    _job(db_session, "j3", match="real", completado_en="2026-11-01 12:00:03")
    _job(db_session, "j4", match="sinan", completado_en="2026-11-01 12:00:04",
         resultado_app=json.dumps({"source": "python", "pick": "Empate", "confianza": "BAJA"}))
    _job(db_session, "j5", match="roto", completado_en="2026-11-01 12:00:05", resultado_app="{no json")
    _job(db_session, "otro_dev", match="ok", device="otro")
    _job(db_session, "pend", match="ok", status="procesando")

    h = repo.leer_historial_app(db_session, "dev1")
    assert h["total"] == 5 and h["device_id"] == "dev1"
    por_job = {x["job_id"]: x for x in h["historial"]}
    assert [x["job_id"] for x in h["historial"]] == ["j5", "j4", "j3", "j2", "j1"]  # más reciente primero
    assert por_job["j1"]["resultado"] == "acertado" and por_job["j1"]["fuente"] == "ia" and por_job["j1"]["pick"] == "Local"
    assert por_job["j2"]["resultado"] == "fallado" and por_job["j2"]["local"] == "Mi Local"
    assert por_job["j3"]["resultado"] == "CANC"
    assert por_job["j4"]["pick"] == "Empate" and por_job["j4"]["fuente"] == "python"
    assert por_job["j4"]["resultado"] == "pendiente" and por_job["j4"]["pick_correcto"] is None
    assert por_job["j5"]["fuente"] is None  # JSON roto no rompe el historial
    assert len(repo.leer_historial_app(db_session, "dev1", limit=2)["historial"]) == 2
    assert repo.leer_historial_app(db_session, "nadie") == {"historial": [], "total": 0, "device_id": "nadie"}


# ------------------------------------------------------------------ top picks de la app
def test_leer_top_picks_app_tres_fuentes(db_session):
    fecha_compacta = HOY.replace("-", "")
    db_session.add_all([
        RecomendacionDia(fixture_id="r1", local="A", visitante="B", liga="L", hora_chile="19:00", fecha=fecha_compacta, creado_en=AHORA),
        RecomendacionDia(fixture_id="r2", local="C", visitante="D", liga="L", hora_chile="18:00", fecha=fecha_compacta, creado_en=AHORA),
    ])
    db_session.commit()
    _comparativo(db_session, "r1", score_final=90, fuentes_disp=3, pick_final="Local")
    # r2 sin comparativo => valores por defecto
    _comparativo(db_session, "u1", score_final=60)
    # El carrusel del usuario toma los 3 más recientes: ju1, ju3 y ju4 (ju4 sin pick y con JSON roto => se omite).
    _job(db_session, "ju1", match="u1", completado_en="2026-11-01 12:00:04", resultado_app=json.dumps({"fuente": "ia"}))
    _job(db_session, "ju3", match="rd", completado_en="2026-11-01 12:00:03",
         resultado_app=json.dumps({"pick": "Visitante", "score": 33}), local_app="X", visitante_app="Y")
    _job(db_session, "ju4", match="roto", completado_en="2026-11-01 12:00:02", resultado_app="{{", local_app="X")
    _job(db_session, "ju2", match="sin_pick", completado_en="2026-11-01 12:00:01")  # fuera del límite de 3
    _comparativo(db_session, "cc1", local="P", visitante="Q", pick_final="Empate")
    db_session.add(CacheConsenso(partido_id="cc1", pick_consenso="Empate", texto_consenso="t", total_analisis=3, usos=0,
                                 max_usos=5, expira_en=FUTURO, creado_en=AHORA, tipo_consenso="mixto"))
    db_session.add(CacheConsenso(partido_id="sin_comp", pick_consenso="Local", texto_consenso="t", total_analisis=2,
                                 usos=0, max_usos=5, expira_en=FUTURO, creado_en=AHORA, tipo_consenso="python"))
    db_session.add(CacheConsenso(partido_id="uno", pick_consenso="Local", texto_consenso="t", total_analisis=1,
                                 usos=0, max_usos=5, expira_en=FUTURO, creado_en=AHORA, tipo_consenso="python"))
    db_session.commit()

    r = repo.leer_top_picks_app(db_session, "dev1", fecha_compacta)
    assert r["fecha"] == HOY and r["tiene_contenido"] is True
    canal = r["canal"]
    assert [p["match_id"] for p in canal] == ["r1", "r2"]  # score None al final
    assert canal[0]["consenso"] == "3/3" and canal[1]["pick"] == "Por definir" and canal[1]["consenso"] == "2/3"
    usuario = {p["match_id"]: p for p in r["usuario"]}
    assert set(usuario) == {"u1", "rd"}
    assert usuario["u1"]["fuente"] == "ia" and usuario["u1"]["pick"] == "Local"
    assert usuario["rd"]["pick"] == "Visitante" and usuario["rd"]["score"] == 33 and usuario["rd"]["confianza"] == "MEDIA"
    assert [p["match_id"] for p in r["compartido"]] == ["cc1"]
    assert r["compartido"][0]["fuente"] == "compartido_mixto" and r["compartido"][0]["partido"] == "P vs Q"


def test_leer_top_picks_app_sin_nada_y_sin_device(db_session):
    r = repo.leer_top_picks_app(db_session, "", "basura")  # fecha mal formada => hoy
    assert r["fecha"] == HOY and r["tiene_contenido"] is False
    assert r["usuario"] == [] and r["canal"] == [] and r["compartido"] == []


# ------------------------------------------------------------------ verificar_partido_completo
def _cc(db, pid, tipo, pick="Local", usos=0, max_usos=5):
    db.add(CacheConsenso(partido_id=pid, pick_consenso=pick, texto_consenso=f"txt {tipo}", total_analisis=2, usos=usos,
                         max_usos=max_usos, expira_en=FUTURO, creado_en=AHORA, tipo_consenso=tipo))
    db.commit()


def test_verificar_partido_completo_consensos_y_analisis_propio(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")
    _cc(db_session, "vp", "python")
    db_session.add(CacheConsenso(partido_id="vp2", pick_consenso="L", texto_consenso="t", total_analisis=2, usos=5,
                                 max_usos=5, expira_en=FUTURO, creado_en=AHORA, tipo_consenso="ia"))
    db_session.commit()
    _job(db_session, "jv", match="vp", resultado_app=json.dumps({"pick": "Local"}))

    r = repo.verificar_partido_completo(db_session, "vp", "dev1", "")  # sin fecha => sin filtro de día
    assert r["consenso_python"]["existe"] and r["consenso_python"]["pick"] == "Local"
    assert r["consenso_ia"]["existe"] is False
    assert r["analisis_propio"] == {"existe": True, "content": {"pick": "Local"}}
    assert r["plan"] == "free" and r["cuota_ia_restante"] == 0

    assert repo.verificar_partido_completo(db_session, "vp2", "dev1", "")["consenso_ia"]["existe"] is False  # agotó usos


def test_verificar_partido_completo_filtra_por_dia_de_chile_y_texto_plano(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")
    _cc(db_session, "vq", "mixto")
    _job(db_session, "jt", match="vq", resultado_app="texto plano")
    ahora_chile_dia = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d")
    r = repo.verificar_partido_completo(db_session, "vq", "dev1", ahora_chile_dia + "T10:00")
    assert r["consenso_ia"]["existe"] is True
    assert r["analisis_propio"] == {"existe": True, "content": "texto plano"}
    lejano = repo.verificar_partido_completo(db_session, "vq", "dev1", "2020-01-01")
    assert lejano["analisis_propio"] == {"existe": False, "content": None}


@pytest.mark.parametrize("plan,rol,activo_hasta,esperado_plan,esperada_cuota", [
    ("max", "usuario", "2099-01-01", "max", 9999),
    ("pro", "usuario", "2099-01-01", "pro", 6 - 2),
    ("pro", "usuario", "2000-01-01", "free", 0),   # vencido => baja a free
    ("free", "admin", None, "admin", 9999),
    ("pro", "admin", "2000-01-01", "admin", 9999),  # el admin nunca vence
])
def test_verificar_partido_completo_plan_y_cuota(db_session, monkeypatch, plan, rol, activo_hasta, esperado_plan, esperada_cuota):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")
    db_session.add(Usuario(device_id="dev1", plan=plan, rol=rol, activo_hasta=activo_hasta, creado_en=AHORA))
    db_session.add(UsoDiarioApp(device_id="dev1", fecha=HOY, predicciones_usadas=2))
    db_session.commit()
    r = repo.verificar_partido_completo(db_session, "m", "dev1", HOY)
    assert (r["plan"], r["cuota_ia_restante"]) == (esperado_plan, esperada_cuota)


def test_verificar_partido_completo_admin_de_env_y_pro_sin_uso(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "boss,otro")
    assert repo.verificar_partido_completo(db_session, "m", "boss", HOY)["plan"] == "admin"
    monkeypatch.setattr(settings, "SPORTS_ADMIN_IDS", "")
    db_session.add(Usuario(device_id="pro1", plan="pro", activo_hasta="2099-01-01", creado_en=AHORA))
    db_session.commit()
    assert repo.verificar_partido_completo(db_session, "m", "pro1", HOY)["cuota_ia_restante"] == 6
