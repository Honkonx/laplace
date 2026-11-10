"""test_ml_reajuste.py — reajuste de modelos con la capa en vivo (`ml/reajuste.py`, `backend/scripts/reajustar_modelos.py`).

La lógica de validación se prueba con un ajustador simulado (no necesita numpy). Las pruebas con el
ajuste real usan `importorskip`: el venv del backend no trae numpy/scipy (corren con el Python del sistema)."""
from __future__ import annotations

import json
import random
from datetime import date

import pytest

from backend.api.ml import dixon_coles, reajuste, vivo

HP = {"xi": 0.0019, "ridge": 2.0, "rho": -0.05}
D0 = date(2026, 1, 1).toordinal()


def partido(dia, local, visitante, gl, gv, es_vivo=False, liga="T1"):
    p = {"liga": liga, "liga_nombre": "Torneo", "temporada": "2026", "fecha": date.fromordinal(dia), "dia": dia, "local": local,
         "visitante": visitante, "gl": gl, "gv": gv, "resultado": "H" if gl > gv else "A" if gv > gl else "D"}
    return {**p, "vivo": True} if es_vivo else p


def modelo_falso(partidos, fecha_ref, xi, ridge, rho, gamma=0.2):
    equipos = sorted({p[1] for p in partidos} | {p[2] for p in partidos})
    return dixon_coles.ModeloLiga(mu=0.2, gamma=gamma, ataque=dict.fromkeys(equipos, 0.0), defensa=dict.fromkeys(equipos, 0.0), rho=rho,
                                  n_partidos=len(partidos), fecha_corte=max(p[0] for p in partidos))


def artefacto(ligas=("T1",), equipos=("A", "B", "C", "D")):
    return {"version": "dc-decay-v1", "hiperparametros": dict(HP), "ligas": {
        c: {"nombre": "Torneo", "mu": 0.2, "gamma": 0.2, "rho": -0.05, "n_partidos": 60, "fecha_corte": D0 + 100,
            "ataque": dict.fromkeys(equipos, 0.0), "defensa": dict.fromkeys(equipos, 0.0)} for c in ligas}}


def datos_sinteticos(n_maestro=60, n_vivos=20, semilla=1):
    rnd = random.Random(semilla)
    eq = ["A", "B", "C", "D"]
    maestro, vivos = [], []
    for i in range(n_maestro + n_vivos):
        local, visit = rnd.sample(eq, 2)
        es_vivo = i >= n_maestro
        (vivos if es_vivo else maestro).append(partido(D0 + i * 3, local, visit, rnd.randint(0, 3), rnd.randint(0, 2), es_vivo))
    return maestro, vivos


# --- validación estructural ---------------------------------------------------------------------

def test_estructura_sana_no_tiene_problemas():
    assert reajuste.validar_estructura(artefacto(), artefacto()) == []


def test_rechaza_ligas_o_equipos_que_desaparecen_y_parametros_invalidos():
    viejo = artefacto(ligas=("T1", "T2"))
    nuevo = artefacto(ligas=("T1",))
    assert any("menos ligas" in p for p in reajuste.validar_estructura(viejo, nuevo))
    nuevo = artefacto(ligas=("T1", "T2"))
    del nuevo["ligas"]["T2"]["ataque"]["D"], nuevo["ligas"]["T2"]["defensa"]["D"]
    assert any("T2" in p and "equipos" in p for p in reajuste.validar_estructura(viejo, nuevo))
    nuevo = artefacto()
    nuevo["ligas"]["T1"]["mu"] = float("nan")
    assert any("no finitos" in p for p in reajuste.validar_estructura(artefacto(), nuevo))
    nuevo = artefacto()
    nuevo["ligas"]["T1"]["ataque"]["A"] = 9.0
    assert any("fuera de" in p for p in reajuste.validar_estructura(artefacto(), nuevo))


# --- decisión -----------------------------------------------------------------------------------

def test_decision_sin_datos_suficientes_no_reemplaza():
    ok, motivo = reajuste.decidir([], {"n": 5, "log_loss_maestro": 1.0, "log_loss_con_vivo": 0.9})
    assert not ok and "insuficientes" in motivo


def test_decision_rechaza_artefacto_peor_y_acepta_mejor_o_equivalente():
    peor = {"n": 150, "log_loss_maestro": 1.00, "log_loss_con_vivo": 1.05}
    assert not reajuste.decidir([], peor)[0]
    assert "peor" in reajuste.decidir([], peor)[1]
    assert reajuste.decidir([], {"n": 150, "log_loss_maestro": 1.00, "log_loss_con_vivo": 0.99})[0]
    assert reajuste.decidir([], {"n": 150, "log_loss_maestro": 1.00, "log_loss_con_vivo": 1.001})[0]  # dentro de la tolerancia
    assert not reajuste.decidir(["x"], {"n": 150, "log_loss_maestro": 1.0, "log_loss_con_vivo": 0.9})[0]


# --- walk-forward: sin fuga y con ajustador peor --------------------------------------------------

def test_walk_forward_nunca_usa_partidos_posteriores_al_bloque():
    maestro, vivos = datos_sinteticos()
    por_maestro, por_con = {"T1": maestro}, {"T1": maestro + vivos}
    llamadas = []

    def espia(partidos, fecha_ref, xi, ridge, rho):
        llamadas.append((max(p[0] for p in partidos), fecha_ref))
        return modelo_falso(partidos, fecha_ref, xi, ridge, rho)

    wf = reajuste.walk_forward_vivo(por_maestro, por_con, vivos, HP, semanas=52, bloque_dias=14, ajustador=espia)
    assert wf["n"] > 0 and llamadas
    assert all(ultimo < ref for ultimo, ref in llamadas)  # cada ajuste solo vio días anteriores al bloque


def test_walk_forward_solo_cuenta_partidos_de_ligas_con_vivos_previos():
    maestro, vivos = datos_sinteticos()
    wf = reajuste.walk_forward_vivo({"T1": maestro}, {"T1": maestro}, vivos, HP, ajustador=modelo_falso)
    assert wf["n"] == 0  # sin partidos "vivo" en el entrenamiento, A y B coinciden: no informa


def test_un_artefacto_peor_no_pasa_la_validacion():
    maestro, vivos = datos_sinteticos()

    def ajustador_malo(partidos, fecha_ref, xi, ridge, rho):
        con_vivo = max(p[0] for p in partidos) > D0 + 59 * 3  # el modelo "con vivo" ve días de la capa en vivo
        return modelo_falso(partidos, fecha_ref, xi, ridge, rho, gamma=3.0 if con_vivo else 0.2)

    wf = reajuste.walk_forward_vivo({"T1": maestro}, {"T1": maestro + vivos}, vivos, HP, semanas=52, bloque_dias=14, ajustador=ajustador_malo)
    assert wf["n"] > 0 and wf["log_loss_con_vivo"] > wf["log_loss_maestro"]
    ok, motivo = reajuste.decidir([], wf, min_evaluados=1)
    assert not ok and "peor" in motivo


# --- reajuste de ligas y reemplazo atómico ---------------------------------------------------------

def test_reajustar_solo_toca_las_ligas_pedidas_y_no_avanza_el_corte_con_pocos_vivos():
    maestro, vivos = datos_sinteticos()
    viejo = artefacto(ligas=("T1", "T2"))
    nuevo = reajuste.reajustar_ligas(viejo, {"T1": maestro + vivos}, D0 + 500, ["T1"], ajustador=modelo_falso)
    assert nuevo["ligas"]["T2"] == viejo["ligas"]["T2"]
    t1 = nuevo["ligas"]["T1"]
    assert t1["n_partidos"] == 80 and t1["n_partidos_vivos"] == 20
    assert t1["fecha_corte"] == max(p["dia"] for p in maestro)  # 20 < 30 vivos: el modelo no se declara "al día"
    nuevo2 = reajuste.reajustar_ligas(viejo, {"T1": maestro + vivos}, D0 + 500, ["T1"], ajustador=modelo_falso, min_vivos_corte=10)
    assert nuevo2["ligas"]["T1"]["fecha_corte"] == max(p["dia"] for p in vivos)
    assert viejo["ligas"]["T1"]["n_partidos"] == 60  # el original no se muta


def test_reemplazo_atomico_guarda_copia_y_no_deja_temporales(tmp_path):
    destino = tmp_path / "art" / "dixon_coles_ligas.json"
    destino.parent.mkdir()
    destino.write_text(json.dumps({"v": 1}), encoding="utf-8")
    copia = reajuste.reemplazar_atomico({"v": 2}, destino, tmp_path / "respaldo")
    assert json.loads(destino.read_text(encoding="utf-8")) == {"v": 2}
    assert json.loads(copia.read_text(encoding="utf-8")) == {"v": 1}
    assert not list(destino.parent.glob("*.tmp"))


# --- ajuste real (numpy/scipy) -----------------------------------------------------------------------

def test_un_partido_posterior_no_altera_el_ajuste_anterior():
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    maestro, _ = datos_sinteticos()
    base = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in maestro]
    futuro = base + [(D0 + 9999, "A", "B", 9, 0)]
    a = dixon_coles.ajustar(base, D0 + 400, **HP)
    b = dixon_coles.ajustar(futuro, D0 + 400, **HP)  # el partido de D0+9999 es posterior a fecha_ref: se ignora
    assert a.a_dict() == b.a_dict()


def test_flujo_completo_dry_run_y_aplicar(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from backend.scripts import reajustar_modelos

    maestro, vivos = datos_sinteticos(n_maestro=70, n_vivos=15)
    ruta_maestro, ruta_vivo = tmp_path / "maestro.csv.gz", tmp_path / "vivo.csv.gz"
    campos = dict.fromkeys(vivo.CAMPOS, "")

    def filas(ps, fuente):
        return [{**campos, "liga_codigo": "T1", "liga_nombre": "Torneo", "temporada": "2026", "fecha": p["fecha"].isoformat(),
                 "local": p["local"], "visitante": p["visitante"], "local_canon": p["local"], "visitante_canon": p["visitante"],
                 "goles_local": p["gl"], "goles_visitante": p["gv"], "resultado": p["resultado"], "fuente": fuente} for p in ps]

    vivo.escribir_csv_gz(filas(maestro, "api-football"), ruta_maestro)
    vivo.escribir_csv_gz(filas(vivos, "laplace_vivo"), ruta_vivo)
    base_ajuste = [(p["dia"], p["local"], p["visitante"], p["gl"], p["gv"]) for p in maestro]
    modelo = dixon_coles.ajustar(base_ajuste, max(p["dia"] for p in maestro) + 1, **HP)
    viejo = {"version": "dc-decay-v1", "hiperparametros": dict(HP), "ligas": {"T1": {"nombre": "Torneo", **modelo.a_dict()}}}
    ruta_art = tmp_path / "dixon_coles_ligas.json"
    ruta_art.write_text(json.dumps(viejo), encoding="utf-8")
    original = ruta_art.read_bytes()
    comunes = ["--artefacto", str(ruta_art), "--maestro", str(ruta_maestro), "--vivo", str(ruta_vivo), "--qa", str(tmp_path / "qa"),
               "--min-evaluados", "1", "--tolerancia", "5", "--semanas", "52", "--bloque-dias", "7", "--rapido", "--json"]

    assert reajustar_modelos.main(comunes) == 0  # dry-run por defecto
    assert ruta_art.read_bytes() == original and (tmp_path / "qa" / "dixon_coles_ligas.nuevo.json").exists()

    assert reajustar_modelos.main([*comunes, "--aplicar"]) == 0
    nuevo = json.loads(ruta_art.read_text(encoding="utf-8"))
    assert nuevo["ligas"]["T1"]["n_partidos"] == 85 and nuevo["ligas"]["T1"]["n_partidos_vivos"] == 15
    assert set(nuevo["ligas"]["T1"]["ataque"]) == set(viejo["ligas"]["T1"]["ataque"])
    assert len(list((tmp_path / "qa" / "respaldo").glob("*.json"))) == 1  # copia del anterior
