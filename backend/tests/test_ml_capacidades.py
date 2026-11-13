"""Contrato `ml-2` (MM-20, MM-21, MM-22, MM-23): clave interna, esquema cerrado, límites, errores tipados, reproducibilidad y verificación de afirmaciones de una IA."""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.core.config import settings
from backend.api.ml.laplace import servicio

CLAVE = "clave-de-prueba-ml2"
H = {"x-laplace-ml-key": CLAVE}
EQ = ["A", "B", "C", "D"]
TABLA = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in EQ]
PEND = [{"local": a, "visitante": b} for a in EQ for b in EQ if a != b]
LAMBDAS = [{"local": a, "visitante": b, "lam_local": 1.4, "lam_visitante": 1.1} for a in EQ for b in EQ if a != b]
CUERPO_SIM = {"tabla": TABLA, "pendientes": PEND, "lambdas": LAMBDAS, "n_sim": 500, "semilla": 5, "cupos": [{"etiqueta": "titulo", "posiciones": [1, 1]}]}


@pytest.fixture()
def cliente(monkeypatch):
    from backend.api.main import app

    app.state.http_client = httpx.AsyncClient()
    monkeypatch.setattr(settings, "ML_API_KEY", CLAVE)
    return TestClient(app)


def test_sin_clave_configurada_los_endpoints_no_existen_y_con_clave_mala_son_401(cliente, monkeypatch):
    assert cliente.get("/api/v2/ml/capacidades", headers=H).status_code == 200
    assert cliente.get("/api/v2/ml/capacidades", headers={"x-laplace-ml-key": "otra"}).status_code == 401
    assert cliente.post("/api/v2/ml/sim/temporada", json=CUERPO_SIM).status_code == 401
    monkeypatch.setattr(settings, "ML_API_KEY", "")
    assert cliente.get("/api/v2/ml/capacidades", headers=H).status_code == 404 and cliente.post("/api/v2/ml/verificar", json={}, headers=H).status_code == 404


def test_las_capacidades_y_las_herramientas_se_publican_en_los_dos_formatos(cliente):
    cap = cliente.get("/api/v2/ml/capacidades", headers=H).json()
    assert cap["contrato"] == "ml-2" and {c["nombre"] for c in cap["capacidades"]} >= {"simular_temporada", "verificar_afirmacion", "comparar_pronosticos"}
    herr = cliente.get("/api/v2/ml/tools", headers=H).json()
    nombres = {t["name"] for t in herr["anthropic"]}
    assert nombres == {"laplace_pronosticar", "laplace_simular_temporada", "laplace_verificar_afirmacion"} and {t["function"]["name"] for t in herr["openai"]} == nombres
    assert all("input_schema" in t and t["description"] for t in herr["anthropic"])


def test_simular_temporada_es_reproducible_y_trae_version_semilla_y_huellas(cliente):
    a, b = cliente.post("/api/v2/ml/sim/temporada", json=CUERPO_SIM, headers=H), cliente.post("/api/v2/ml/sim/temporada", json=CUERPO_SIM, headers=H)
    assert a.status_code == 200 and a.json() == b.json()
    r = a.json()
    assert r["contrato"] == "ml-2" and r["capacidad"] == "simular_temporada" and r["semilla"] == 5 and r["validado"] is False
    assert r["huella_entrada"].startswith("sha256:") and r["huella_salida"].startswith("sha256:") and r["supuestos"] and r["limitaciones"]
    otra = cliente.post("/api/v2/ml/sim/temporada", json={**CUERPO_SIM, "semilla": 6}, headers=H).json()
    assert otra["huella_salida"] != r["huella_salida"]


@pytest.mark.parametrize(("cambio", "error", "campo"), [
    ({"n_sim": 10**6}, "limite_excedido", "n_sim"), ({"semilla": "x"}, "entrada_invalida", "semilla"), ({"tabla": None}, "entrada_invalida", "tabla"),
    ({"lambdas": [{"local": "A", "visitante": "B", "lam_local": 99, "lam_visitante": 1}]}, "entrada_invalida", None), ({"lambdas": "no"}, "entrada_invalida", "lambdas"),
])
def test_los_errores_son_cerrados_y_tipados_nunca_un_resultado_parcial(cliente, cambio, error, campo):
    r = cliente.post("/api/v2/ml/sim/temporada", json={**CUERPO_SIM, **cambio}, headers=H)
    cuerpo = r.json()
    assert r.status_code == 422 and cuerpo["ok"] is False and cuerpo["error"] == error and "corregible" in cuerpo and cuerpo["contrato"] == "ml-2"
    if campo:
        assert cuerpo["campo"] == campo


def test_un_cuerpo_enorme_o_que_no_es_json_se_rechaza(cliente):
    enorme = cliente.post("/api/v2/ml/sim/temporada", content=b'{"x": "' + b"a" * 1_100_000 + b'"}', headers={**H, "content-type": "application/json"})
    assert enorme.status_code == 422 and enorme.json()["error"] == "limite_excedido"
    roto = cliente.post("/api/v2/ml/sim/temporada", content=b"{no es json", headers={**H, "content-type": "application/json"})
    assert roto.status_code == 422 and roto.json()["error"] == "entrada_invalida"


def test_lambdas_de_modelo_usa_el_modelo_y_si_no_cubre_el_partido_lo_dice(cliente, monkeypatch):
    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: {"goles_esperados": {"local": 1.5, "visitante": 1.1, "total": 2.6}})
    r = cliente.post("/api/v2/ml/sim/temporada", json={**{k: v for k, v in CUERPO_SIM.items() if k != "lambdas"}, "lambdas_de_modelo": True, "liga": "Liga X"}, headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True
    monkeypatch.setattr(servicio, "pronostico_propio", lambda entrada: None)
    r = cliente.post("/api/v2/ml/sim/temporada", json={**{k: v for k, v in CUERPO_SIM.items() if k != "lambdas"}, "lambdas_de_modelo": True}, headers=H)
    assert r.status_code == 422 and r.json()["error"] == "datos_insuficientes" and r.json()["corregible"] is False


def test_escenario_forzado_baja_la_probabilidad_del_equipo_que_pierde_y_los_caminos_suman_uno(cliente):
    fijos = [{"local": "A", "visitante": b, "gl": 0, "gv": 3} for b in ("B", "C", "D")]
    esc = cliente.post("/api/v2/ml/sim/escenario", json={"base": {**CUERPO_SIM, "n_sim": 2000}, "resultados_fijos": fijos, "modo": "forzar"}, headers=H)
    assert esc.status_code == 200 and esc.json()["capacidad"] == "simular_escenario"
    pend = [{"local": "A", "visitante": "B"}, {"local": "B", "visitante": "C"}, {"local": "C", "visitante": "A"}]
    cam = cliente.post("/api/v2/ml/sim/caminos", json={"tabla": TABLA, "pendientes": pend, "lambdas": LAMBDAS, "objetivo": {"equipo": "A", "evento": "titulo", "posiciones": [1, 1]}}, headers=H)
    assert cam.status_code == 200 and abs(cam.json()["suma_probabilidades"] - 1) < 1e-9 and cam.json()["n_caminos_total"] == 27
    assert cliente.post("/api/v2/ml/sim/escenario", json={"resultados_fijos": []}, headers=H).json()["campo"] == "base"


# ---------- comparar pronósticos (eval) ----------
def _partidos(n):
    a = [[0.4, 0.3, 0.3]] * n
    b = [[0.6, 0.2, 0.2] if i % 2 == 0 else [0.2, 0.2, 0.6] for i in range(n)]
    return a, b, ["H" if i % 2 == 0 else "A" for i in range(n)]


def test_comparar_pronosticos_dice_quien_es_mejor_con_significancia(cliente):
    a, b, res = _partidos(400)
    r = cliente.post("/api/v2/ml/eval/comparar", json={"a": a, "b": b, "resultados": res}, headers=H)
    cuerpo = r.json()
    assert r.status_code == 200 and cuerpo["diferencia_media"] > 0.2 and cuerpo["cumple_puerta"] is True and cuerpo["z"] > 3 and len(cuerpo["ic95"]) == 2
    assert cuerpo["huella_salida"] != cuerpo["huella_entrada"]
    assert r.json() == cliente.post("/api/v2/ml/eval/comparar", json={"a": a, "b": b, "resultados": res}, headers=H).json()


@pytest.mark.parametrize("cuerpo", [{"a": [[0.5, 0.5, 0.5]] * 5, "b": [[0.4, 0.3, 0.3]] * 5, "resultados": ["H"] * 5}, {"a": [[0.4, 0.3, 0.3]] * 5, "b": [[0.4, 0.3, 0.3]] * 4, "resultados": ["H"] * 5},
                                    {"a": [[0.4, 0.3, 0.3]] * 5, "b": [[0.4, 0.3, 0.3]] * 5, "resultados": ["X"] * 5}, {"a": [[0.4, 0.3, 0.3]] * 2, "b": [[0.4, 0.3, 0.3]] * 2, "resultados": ["H"] * 2}])
def test_comparar_rechaza_probabilidades_que_no_suman_listas_dispares_y_pocos_partidos(cliente, cuerpo):
    r = cliente.post("/api/v2/ml/eval/comparar", json=cuerpo, headers=H)
    assert r.status_code == 422 and r.json()["ok"] is False


# ---------- verificar afirmación (la IA propone, el modelo calcula, la IA critica) ----------
def _modelo_falso(monkeypatch, p=(0.50, 0.30, 0.20), validados=("btts", "o25")):
    salida = {"ok": True, "fuente": "modelo_laplace", "degradado": False, "p1x2": {"local": p[0], "empate": p[1], "visitante": p[2]}, "validados": list(validados), "confianza": 0.2,
              "goles_esperados": {"local": 1.5, "visitante": 1.1, "total": 2.6}, "btts": {"si": 0.52, "no": 0.48}, "over_under": {"2.5": {"mas": 0.55, "menos": 0.45}}, "marcadores": [], "modelo": {"version": "t"}}
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, entrada, canal="http": salida)


def test_verificar_dice_coincide_o_difiere_sin_corregir_la_cifra(cliente, monkeypatch):
    _modelo_falso(monkeypatch)
    ok = cliente.post("/api/v2/ml/verificar", json={"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": 0.51}}, headers=H).json()
    assert ok["coincide"] is True and ok["valor_modelo"] == 0.5 and ok["valor_afirmado"] == 0.51 and ok["capacidad"] == "verificar_afirmacion"
    mal = cliente.post("/api/v2/ml/verificar", json={"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": 0.62}}, headers=H).json()
    assert mal["coincide"] is False and mal["diferencia"] == pytest.approx(0.12) and mal["valor_modelo"] == 0.5
    estricta = cliente.post("/api/v2/ml/verificar", json={"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": 0.51}, "tolerancia": 0.005}, headers=H).json()
    assert estricta["coincide"] is False


def test_verificar_solo_campos_validados_y_rechaza_entradas_raras(cliente, monkeypatch):
    _modelo_falso(monkeypatch, validados=())  # `servicio.publico` quita lo no validado
    r = cliente.post("/api/v2/ml/verificar", json={"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "btts.si", "valor": 0.5}}, headers=H)
    assert r.status_code == 422 and r.json()["error"] == "no_validado"
    for cuerpo in ({"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "drop table", "valor": 0.5}}, {"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": "alto"}},
                   {"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": 0.5}, "tolerancia": 5}, {"entrada": "x", "afirmacion": {}}):
        assert cliente.post("/api/v2/ml/verificar", json=cuerpo, headers=H).status_code == 422


def test_verificar_sin_modelo_dice_modelo_no_disponible(cliente, monkeypatch):
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, entrada, canal="http": {"ok": False, "motivo": "no hay un modelo Laplace activo"})
    r = cliente.post("/api/v2/ml/verificar", json={"entrada": {"local": "A", "visitante": "B"}, "afirmacion": {"campo": "p1x2.local", "valor": 0.5}}, headers=H)
    assert r.status_code == 422 and r.json()["error"] == "modelo_no_disponible" and r.json()["corregible"] is False


# ---------- revisión de seguridad: presupuesto de trabajo, hilo con plazo y tope del cuerpo ----------
def test_el_presupuesto_limita_el_trabajo_total_aunque_cada_factor_cumpla_su_limite(cliente):
    eq = [f"E{i}" for i in range(20)]
    pend = [{"local": a, "visitante": b} for a in eq for b in eq if a != b][:380]
    lam = [{"local": p["local"], "visitante": p["visitante"], "lam_local": 1.4, "lam_visitante": 1.1} for p in pend]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    r = cliente.post("/api/v2/ml/sim/temporada", json={"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 20000}, headers=H)  # 20.000 × 380 = 7,6 M de sorteos
    assert r.status_code == 422 and r.json()["error"] == "limite_excedido" and r.json()["campo"] == "n_sim" and r.json()["maximo"] == 2_000_000 // 380
    ok = cliente.post("/api/v2/ml/sim/temporada", json={"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 2000}, headers=H)  # 760.000 sorteos: dentro del presupuesto
    assert ok.status_code == 200
    esc = cliente.post("/api/v2/ml/sim/escenario", json={"base": {"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 3000}, "resultados_fijos": []}, headers=H)  # ×2: 2,28 M
    assert esc.status_code == 422 and esc.json()["error"] == "limite_excedido"


def test_el_cuerpo_demasiado_grande_se_rechaza_por_la_cabecera_sin_leerlo(cliente):
    r = cliente.post("/api/v2/ml/sim/temporada", content=b"{}", headers={**H, "content-type": "application/json", "content-length": "5000000"})
    assert r.status_code in (422, 400) or r.json().get("error") == "limite_excedido"


def test_un_calculo_que_supera_el_plazo_responde_504_cerrado(cliente, monkeypatch):
    import time

    from backend.api.routers import ml_capacidades

    monkeypatch.setattr(ml_capacidades, "PLAZO_SEGUNDOS", 0.05)
    monkeypatch.setattr(ml_capacidades.liga, "simular_temporada", lambda *a, **k: time.sleep(0.5) or {})
    r = cliente.post("/api/v2/ml/sim/temporada", json=CUERPO_SIM, headers=H)
    assert r.status_code == 504 and r.json()["error"] == "limite_excedido" and r.json()["campo"] == "plazo"
