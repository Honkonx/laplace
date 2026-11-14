"""SM-1 a SM-4: la «máquina del tiempo» repite el pasado con reloj simulado sobre una base con las migraciones reales.

Solo la fuente de resultados (el exterior) es falsa; la cola, el cierre, el laboratorio y los modelos son los reales. Las ligas de estas pruebas son sintéticas y chicas (10 equipos,
3 fechas) para que cada repetición cierre en segundos; la corrida con datos reales va por la línea de comandos (`backend/scripts/maquina_del_tiempo.py`) y una prueba corta de
datos reales se omite si los CSV no están (no se publican)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from backend.api.ml import datos
from backend.api.ml.laplace import repeticion as rep, simulacion
from backend.api.models.partidos import ResultadoPartido
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.models.verificacion import Verificacion

PASO = 120   # minutos del reloj simulado: suficiente para las pruebas y rápido


def _mundo(semilla: int = 1, equipos: int = 10, rondas: int = 3):
    """Dos temporadas sintéticas: la primera entrena, las primeras `rondas` fechas de la segunda son la ventana."""
    ps = simulacion.simular(semilla, n_equipos=equipos, temporadas=2)["partidos"]
    codigo = ps[0]["liga"]
    segunda = [p for p in ps if p["temporada"] == "S2"]
    desde = date.fromordinal(min(p["dia"] for p in segunda))
    return {codigo: ps}, codigo, desde, desde + timedelta(days=7 * (rondas - 1))


@pytest.fixture(scope="module")
def mundo():
    por_liga, codigo, desde, hasta = _mundo()
    return {"por_liga": por_liga, "codigo": codigo, "desde": desde, "hasta": hasta, "artefacto": rep.entrenar_sin_fuga(por_liga, desde, [codigo])}


@pytest.fixture()
def fabrica(base_migrada):
    return base_migrada("head")


def _repetir(m, fabrica, **k):
    return rep.repetir(m["por_liga"], [m["codigo"]], m["desde"], m["hasta"], fabrica, paso_min=PASO, artefacto=m["artefacto"], n_boot=50, **k)


def _ids(m):
    programados, _ = rep.programar(m["por_liga"], [m["codigo"]], m["desde"], m["hasta"])
    return [p.partido_id for p in programados], programados


# ---------------------------------------------------------------- SM-1: el arnés completo
def test_la_repeticion_cierra_todo_sola_y_coincide_con_el_calculo_independiente(mundo, fabrica):
    r = _repetir(mundo, fabrica)
    n = r["programados"]
    assert n == 15 and r["registrados"] == n and r["verificados"] == n
    assert r["cola"]["por_estado"] == {"final": n} and r["cola"]["atrasadas"] == 0
    assert r["diferencia_con_calculo_independiente"] < 1e-9               # informe de la base == cálculo directo de las métricas
    assert r["diferencia_con_recorrido_directo"] < 1e-9                   # probabilidades y goles esperados == recorrido walk-forward independiente
    assert r["casos_de_la_base_iguales_a_los_directos"] is True
    inf = r["informe"]
    assert inf["n"] == n and inf["acierto_1x2"]["ic95"][0] <= inf["acierto_1x2"]["valor"] <= inf["acierto_1x2"]["ic95"][1]
    assert {"rps", "log_loss", "brier", "goles_local", "goles_visitante"} <= set(inf)
    assert inf["rps"]["ic95_modelo"][0] <= inf["rps"]["modelo"] <= inf["rps"]["ic95_modelo"][1]


def test_cero_fugas_el_marcador_sale_solo_a_inicio_mas_140_y_ningun_pronostico_usa_su_futuro(mundo, fabrica):
    r = _repetir(mundo, fabrica)
    assert r["fugas"]["cero_fugas"] is True and r["fugas"]["entregas"] == r["programados"] and r["fugas"]["revisados"] == r["registrados"]


def test_la_auditoria_de_fugas_detecta_las_tres_clases_de_fuga(mundo):
    art, ultimo = mundo["artefacto"]
    programados, ocultos = rep.programar(mundo["por_liga"], [mundo["codigo"]], mundo["desde"], mundo["hasta"])
    p = programados[0]
    fuente = rep.FuenteOculta(programados, ocultos)
    limpio = {"partido_id": p.partido_id, "dia": p.dia, "inicio": p.inicio, "corte": datetime.fromordinal(p.dia), "estado_hasta": p.dia - 1}
    assert rep.auditar_fugas([limpio], fuente, mundo["desde"], ultimo)["cero_fugas"]
    assert not rep.auditar_fugas([{**limpio, "estado_hasta": p.dia}], fuente, mundo["desde"], ultimo)["cero_fugas"]                         # el estado ya traía el día del partido
    assert not rep.auditar_fugas([{**limpio, "corte": p.inicio}], fuente, mundo["desde"], ultimo)["cero_fugas"]                             # pronosticado al empezar el partido
    fuente.entregas[p.partido_id] = p.inicio + timedelta(minutes=139)
    assert not rep.auditar_fugas([limpio], fuente, mundo["desde"], ultimo)["cero_fugas"]                                                    # marcador entregado un minuto antes
    assert not rep.auditar_fugas([limpio], rep.FuenteOculta(programados, ocultos), mundo["desde"], {"X": mundo["desde"].toordinal()})["cero_fugas"]   # entrenamiento que toca la ventana


def test_la_fuente_oculta_no_da_el_marcador_antes_de_inicio_mas_140_y_el_pronosticador_no_lo_ve(mundo):
    import asyncio

    programados, ocultos = rep.programar(mundo["por_liga"], [mundo["codigo"]], mundo["desde"], mundo["hasta"])
    p = programados[0]
    fuente = rep.FuenteOculta(programados, ocultos)
    fila = Verificacion(partido_id=p.partido_id)
    resp = {}
    for minutos in (-30, 0, 139, 140, 141):
        fuente.reloj = p.inicio + timedelta(minutes=minutos)
        resp[minutos] = asyncio.run(fuente(None, fila))
    assert resp[-30] is None and resp[0] == {"status": "2H"} and resp[139] == {"status": "2H"}
    assert resp[140]["status"] == "FT" and (resp[140]["goles_local"], resp[140]["goles_visitante"]) == ocultos[p.partido_id]
    assert fuente.entregas[p.partido_id] == p.inicio + timedelta(minutes=140)
    assert set(rep.Programado.__dataclass_fields__) == {"partido_id", "liga", "local", "visitante", "dia", "inicio"}       # sin marcador


def test_el_inicio_sintetico_es_estable_y_cae_entre_las_12_y_las_20_utc():
    dia = date(2025, 10, 4).toordinal()
    a = rep.inicio_sintetico("E0", "Arsenal", "Chelsea", dia)
    assert a == rep.inicio_sintetico("E0", "Arsenal", "Chelsea", dia) and a.date() == date(2025, 10, 4)
    horas = {rep.inicio_sintetico("E0", f"Club{i}", "Rival", dia) for i in range(60)}
    assert all(12 <= h.hour <= 20 and h.minute in (0, 30) for h in horas) and len(horas) > 5 and max(horas).hour <= 20


def test_la_repeticion_deja_pronosticos_en_el_laboratorio_con_corte_anterior_al_inicio_y_goles_reales(mundo, fabrica):
    _repetir(mundo, fabrica)
    s = fabrica()
    filas = s.query(PronosticoExperimental).filter_by(variante=rep.VARIANTE).all()
    assert len(filas) == 15 and all(f.corte_datos_en < f.hora_kickoff and f.goles_local_real is not None and f.pick_correcto in (0, 1) for f in filas)
    assert s.query(ResultadoPartido).count() == 15
    s.close()


# ---------------------------------------------------------------- SM-2: liga inventada con verdad conocida
def test_sm2_el_modelo_queda_cerca_del_oraculo_con_una_temporada_de_entrenamiento(fabrica):
    ps = simulacion.simular(1, n_equipos=16, temporadas=2)["partidos"]
    codigo = ps[0]["liga"]
    prueba = [p for p in ps if p["temporada"] == "S2"]
    desde, hasta = date.fromordinal(min(p["dia"] for p in prueba)), date.fromordinal(max(p["dia"] for p in prueba))
    r = rep.repetir({codigo: ps}, [codigo], desde, hasta, fabrica, paso_min=PASO, oraculo_de=lambda p: tuple(p["verdad"]), n_boot=50)
    o = r["informe"]["frente_al_oraculo"]
    assert r["verificados"] == 240 and r["fugas"]["cero_fugas"] and r["diferencia_con_calculo_independiente"] < 1e-9
    assert o["log_loss_oraculo"] < o["log_loss_modelo"]                    # el que conoce la verdad no pierde frente a quien la estima
    assert 0 < o["exceso_de_log_loss"] < 0.08                              # referencia de la corrida del 2026-11-14: semilla 1 → +0,0710 (cinco semillas: +0,017 a +0,071, media +0,047)


# ---------------------------------------------------------------- SM-3: escenarios adversos a nivel de arnés completo
def test_un_partido_aplazado_se_juega_dos_dias_despues_y_se_verifica_entonces(mundo, fabrica):
    ids, programados = _ids(mundo)
    pid, inicio = ids[0], programados[0].inicio
    guion = {pid: [(timedelta(0), {"status": "PST"}), (timedelta(days=2), {"status": "FT"})]}
    r = _repetir(mundo, fabrica, guion=guion)
    s = fabrica()
    v = s.get(Verificacion, pid)
    assert v.estado == "final" and v.intentos >= 3 and v.resuelto_en >= (inicio + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    assert r["verificados"] == 15 and r["fugas"]["cero_fugas"] and r["diferencia_con_calculo_independiente"] < 1e-9
    s.close()


def test_un_partido_suspendido_se_cierra_sin_resultado_y_no_entra_a_las_metricas(mundo, fabrica):
    ids, _ = _ids(mundo)
    r = _repetir(mundo, fabrica, guion={ids[1]: [(timedelta(0), {"status": "CANC"})]})
    s = fabrica()
    assert s.get(Verificacion, ids[1]).estado == "sin_resultado" and s.query(ResultadoPartido).filter_by(fixture_id=ids[1]).count() == 0
    assert r["verificados"] == 14 and r["informe"]["n"] == 14 and r["fugas"]["cero_fugas"]
    s.close()


def test_una_fuente_caida_y_un_429_solo_cuentan_como_intento_y_el_partido_se_cierra_despues(mundo, fabrica):
    ids, _ = _ids(mundo)
    guion = {ids[2]: [(timedelta(0), RuntimeError("503 del proveedor")), (timedelta(hours=6), {"status": "FT"})],
             ids[3]: [(timedelta(0), RuntimeError("HTTP 429 Too Many Requests")), (timedelta(hours=9), {"status": "FT"})]}
    r = _repetir(mundo, fabrica, guion=guion)
    s = fabrica()
    a, b = s.get(Verificacion, ids[2]), s.get(Verificacion, ids[3])
    assert (a.estado, b.estado) == ("final", "final") and a.intentos >= 2 and b.intentos >= 2 and "503" in a.ultimo_error and "429" in b.ultimo_error
    assert r["verificados"] == 15 and r["cola"]["por_estado"] == {"final": 15}
    s.close()


def test_un_resultado_tardio_dentro_del_horizonte_se_recupera_y_uno_fuera_no_se_inventa(mundo, fabrica):
    ids, _ = _ids(mundo)
    guion = {ids[4]: [(timedelta(0), None), (timedelta(hours=30), {"status": "FT"})], ids[5]: [(timedelta(0), None), (timedelta(days=5), {"status": "FT"})]}
    r = _repetir(mundo, fabrica, guion=guion)
    s = fabrica()
    assert s.get(Verificacion, ids[4]).estado == "final"
    perdido = s.get(Verificacion, ids[5])
    assert perdido.estado == "sin_resultado" and perdido.goles_local is None and s.query(ResultadoPartido).filter_by(fixture_id=ids[5]).count() == 0
    assert r["verificados"] == 14 and r["fugas"]["cero_fugas"]
    s.close()


def test_un_pronostico_duplicado_del_mismo_partido_no_duplica_la_cola_ni_las_metricas(mundo, fabrica):
    ids, _ = _ids(mundo)
    r = _repetir(mundo, fabrica, duplicar={ids[0], ids[7]})
    s = fabrica()
    assert s.query(Verificacion).count() == 15 and s.query(ResultadoPartido).count() == 15
    assert s.query(PronosticoExperimental).filter_by(partido_id=ids[0]).count() == 2
    assert all(f.goles_local_real is not None for f in s.query(PronosticoExperimental).filter_by(partido_id=ids[0]))      # los dos quedan calificados
    assert r["registrados"] == 17 and r["verificados"] == 15 and r["informe"]["n"] == 15 and r["diferencia_con_calculo_independiente"] < 1e-9
    s.close()


def test_un_equipo_sin_historia_se_pronostica_igual_y_queda_marcado(mundo, fabrica):
    por_liga = {mundo["codigo"]: list(mundo["por_liga"][mundo["codigo"]])}
    modelo = next(p for p in por_liga[mundo["codigo"]] if p["dia"] == mundo["desde"].toordinal())
    por_liga[mundo["codigo"]].append({**modelo, "local": "Club Recien Llegado", "visitante": "Club Sin Pasado", "gl": 2, "gv": 1, "resultado": "H"})
    r = rep.repetir(por_liga, [mundo["codigo"]], mundo["desde"], mundo["hasta"], fabrica, paso_min=PASO, artefacto=mundo["artefacto"], n_boot=50)
    assert r["verificados"] == 16 and r["informe"]["sin_historia"] >= 1 and r["fugas"]["cero_fugas"]
    sin = [c for c in r["casos"] if c["sin_historia"]]
    assert sin and all(abs(sum(c["p"]) - 1) < 1e-9 and all(0 < x < 1 for x in c["p"]) for c in sin)


def test_un_reinicio_a_mitad_de_dia_recupera_la_corrida_perdida_sin_duplicar(mundo, fabrica):
    primer_dia = datetime.fromordinal(mundo["desde"].toordinal())
    r = _repetir(mundo, fabrica, apagado=(primer_dia + timedelta(hours=13), primer_dia + timedelta(hours=23)))
    s = fabrica()
    assert r["reinicios"] == 1 and s.query(Verificacion).count() == 15 and s.query(ResultadoPartido).count() == 15
    assert r["cola"]["por_estado"] == {"final": 15} and r["fugas"]["cero_fugas"] and r["diferencia_con_calculo_independiente"] < 1e-9
    del_dia = s.query(Verificacion).filter(Verificacion.fecha_partido == mundo["desde"].isoformat()).all()
    assert del_dia and all(v.intentos == 1 and v.resuelto_en >= (primer_dia + timedelta(hours=23)).strftime("%Y-%m-%dT%H:%M:%S") for v in del_dia)   # una sola recuperación por partido
    s.close()


# ---------------------------------------------------------------- SM-4: umbral × acierto × cobertura
def _casos_falsos(prob: float, acierto: float, n: int) -> list[dict]:
    """n casos cuyo pick (Local) tiene probabilidad `prob` y acierta la fracción `acierto`."""
    resto = (1 - prob) / 2
    return [{"p": (prob, resto, resto), "resultado": "H" if i < round(n * acierto) else "A"} for i in range(n)]


def test_la_tabla_de_umbrales_cubre_todo_y_la_cobertura_no_crece_con_el_umbral(mundo, fabrica):
    casos = _repetir(mundo, fabrica)["casos"]
    t = rep.tabla_umbrales(casos)
    assert t["n"] == 15 and sum(b["n"] for b in t["bandas"].values()) == 15
    coberturas = [r["cobertura"] for r in t["umbrales"].values()]
    assert coberturas == sorted(coberturas, reverse=True) and t["umbrales"]["0.40"]["cobertura"] > 0.9
    for r in t["umbrales"].values():
        if r["n"]:
            assert r["ic95"][0] <= r["acierto"] <= r["ic95"][1]


def test_una_banda_bien_calibrada_se_confirma_y_una_sobreconfiada_se_corrige():
    bien = rep.tabla_umbrales(_casos_falsos(0.72, 0.72, 400) + _casos_falsos(0.55, 0.55, 400) + _casos_falsos(0.42, 0.42, 400))
    assert all(bien["bandas"][b]["veredicto"] == "calibrada" for b in ("BAJA", "MEDIA", "ALTA")) and bien["las_bandas_se_separan_con_ic95"]
    sobre = rep.tabla_umbrales(_casos_falsos(0.72, 0.55, 600))
    assert sobre["bandas"]["ALTA"]["veredicto"] == "sobreconfiada" and sobre["bandas"]["MEDIA"]["n"] == 0
    sub = rep.tabla_umbrales(_casos_falsos(0.62, 0.80, 600))
    assert sub["bandas"]["ALTA"]["veredicto"] == "subconfiada"


def test_wilson_da_un_intervalo_conocido():
    lo, hi = rep.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3) and rep.wilson(0, 0) == (0.0, 1.0)


# ---------------------------------------------------------------- SM-1 con partidos reales (se omite sin los CSV, que no se publican)
@pytest.mark.skipif(not (datos.RUTA_DATOS / "partidos.csv.gz").exists() and not (datos.RUTA_DATOS / "partidos.csv").exists(), reason="los CSV históricos no están (no se publican)")
def test_sm1_ventana_real_de_una_semana_cierra_sola_y_coincide_con_el_calculo_independiente(fabrica):
    por_liga = datos.agrupar_por_liga(datos.cargar_partidos_con_vivo()[0])
    if "E0" not in por_liga:
        pytest.skip("sin la Premier League en el histórico")
    ultimo = date.fromordinal(max(p["dia"] for p in por_liga["E0"]))
    desde = ultimo - timedelta(days=20)
    r = rep.repetir(por_liga, ["E0"], desde, ultimo, fabrica, paso_min=PASO, n_boot=50)
    assert r["programados"] >= 3 and r["verificados"] == r["programados"]
    assert r["fugas"]["cero_fugas"] and r["diferencia_con_calculo_independiente"] < 1e-9 and r["diferencia_con_recorrido_directo"] < 1e-9
    json.dumps({k: v for k, v in r.items() if k != "casos"}, default=str)       # el informe se puede guardar
