"""test_reporte_laboratorio_vivo.py — `backend/scripts/reporte_laboratorio_vivo.py` (solo lectura, sin red)."""
from __future__ import annotations

import json
import sqlite3

from backend.scripts import reporte_laboratorio_vivo as reporte

ODDS = json.dumps({"odds_disponibles": True, "odds_local": 2.0, "odds_empate": 3.4, "odds_visit": 3.8})


def _bd(tmp_path, filas, resultados):
    ruta = tmp_path / "lab.db"
    con = sqlite3.connect(ruta)
    con.executescript("""
    CREATE TABLE pronosticos_experimentales (id INTEGER PRIMARY KEY, partido_id TEXT, variante TEXT, liga TEXT, local TEXT, visitante TEXT,
        fecha_partido TEXT, corte_datos_en TEXT, creado_en TEXT, datos_json TEXT, prob_local REAL, prob_empate REAL, prob_visitante REAL,
        goles_local_real INT, goles_visitante_real INT);
    CREATE TABLE resultados_partidos (fixture_id TEXT, goles_local INT, goles_visitante INT);
    """)
    con.executemany("INSERT INTO pronosticos_experimentales (partido_id, variante, liga, local, visitante, fecha_partido, corte_datos_en,"
                    " creado_en, datos_json, prob_local, prob_empate, prob_visitante, goles_local_real, goles_visitante_real)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    con.executemany("INSERT INTO resultados_partidos VALUES (?,?,?)", resultados)
    con.commit()
    con.close()
    return ruta


def fila(pid, variante, probs, corte="2026-10-08T10:00:00Z", datos=ODDS, real=None):
    gl, gv = real or (None, None)
    return (pid, variante, "Liga X", "L", "V", "2026-10-09", corte, corte, datos, *probs, gl, gv)


def test_compara_sobre_el_mismo_conjunto_y_con_tasa_base_y_mercado(tmp_path):
    filas, res = [], [("1", 2, 0), ("2", 0, 1), ("3", 1, 1)]
    for pid in ("1", "2", "3"):
        filas.append(fila(pid, "dixon_coles_historico", (0.5, 0.3, 0.2)))
        filas.append(fila(pid, "ia_simple", (0.4, 0.3, 0.3)))
    filas.append(fila("4", "ia_simple", (0.4, 0.3, 0.3)))  # sin resultado: no entra al conjunto común
    r = reporte.construir_reporte(reporte.leer_filas(_bd(tmp_path, filas, res)))
    comun = r["conjunto_comun"]
    assert comun["n"] == 3 and set(comun["variantes_comparadas"]) == {"dixon_coles_historico", "ia_simple"}
    k = comun["comparacion"]
    assert k["variantes"]["dixon_coles_historico"]["n"] == k["variantes"]["ia_simple"]["n"] == k["tasa_base"]["n"] == k["mercado"]["n"] == 3
    assert "insuficiente" in comun["advertencia"].lower()
    assert r["variantes"]["ia_simple"]["evaluados"] == 3 and r["variantes"]["ia_simple"]["con_probabilidades"] == 4
    assert r["variantes"]["ia_simple"]["muestra_insuficiente"] and r["variantes"]["ia_simple"]["faltan_exploratoria"] == 47
    assert r["variantes"]["ia_simple"]["faltan_promocion"] == 197


def test_cuenta_solo_la_primera_prediccion_y_excluye_el_motor_anterior(tmp_path):
    filas = [
        fila("1", "ia_simple", (0.9, 0.05, 0.05), corte="2026-10-08T10:00:00Z"),
        fila("1", "ia_simple", (0.1, 0.1, 0.8), corte="2026-10-08T12:00:00Z"),  # reintento posterior: se ignora
        fila("1", "python_baseline", (0.4, 0.3, 0.3), corte="2026-10-05T10:00:00Z"),  # motor anterior al corte
    ]
    r = reporte.construir_reporte(reporte.leer_filas(_bd(tmp_path, filas, [("1", 1, 0)])))
    ia = r["variantes"]["ia_simple"]["sobre_su_propio_conjunto"]["variantes"]["ia_simple"]
    assert ia["n"] == 1 and ia["accuracy"] == 1.0  # tomó 0.9 local, no el reintento
    pb = r["variantes"]["python_baseline"]
    assert pb["evaluados"] == 0 and pb["excluidos_por_corte_motor"] == 1


def test_resultado_desde_la_fila_o_desde_resultados_partidos_y_sin_cuotas(tmp_path):
    filas = [fila("1", "ia_simple", (0.5, 0.3, 0.2), datos="{}", real=(0, 2)), fila("2", "ia_simple", (0.5, 0.3, 0.2), datos="{}")]
    r = reporte.construir_reporte(reporte.leer_filas(_bd(tmp_path, filas, [("2", 3, 0)])))
    propio = r["variantes"]["ia_simple"]["sobre_su_propio_conjunto"]
    assert propio["variantes"]["ia_simple"]["n"] == 2 and propio["mercado"] is None
    assert r["conjunto_comun"].get("comparacion") is None  # una sola variante con datos: no hay comparación


def test_base_vacia_no_inventa_nada(tmp_path):
    r = reporte.construir_reporte(reporte.leer_filas(_bd(tmp_path, [], [])))
    assert r["conjunto_comun"]["n"] == 0 and all(v["muestra_insuficiente"] for v in r["variantes"].values())
    reporte.imprimir(r)  # no falla con datos vacíos


def test_es_solo_lectura(tmp_path):
    ruta = _bd(tmp_path, [fila("1", "ia_simple", (0.5, 0.3, 0.2))], [])
    antes = ruta.read_bytes()
    reporte.construir_reporte(reporte.leer_filas(ruta))
    assert ruta.read_bytes() == antes
