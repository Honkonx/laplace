"""MM-41: el núcleo Monte Carlo en Go es estadísticamente equivalente al de Python, se desactiva solo si falta o falla, y nunca se usa con filtros."""
import math

import pytest

from backend.api.ml.laplace import liga, motor_go, motor_rust

requiere_go = pytest.mark.skipif(not motor_go.disponible(), reason="sin binario de Go (python backend/scripts/construir_go.py)")


@pytest.fixture(autouse=True)
def _con_motor_real(monkeypatch):
    monkeypatch.delenv("LAPLACE_MOTOR_SIM", raising=False)


def _mundo(n=6):
    eq = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    pend = [{"local": a, "visitante": b} for a in eq for b in eq if a != b]
    return tabla, pend, lambda l, v: (1.5 if l == "E0" else 1.2, 0.9 if v == "E0" else 1.1)


@requiere_go
def test_go_y_python_dan_las_mismas_distribuciones_dentro_del_error_montecarlo():
    tabla, pend, lam = _mundo(6)
    n = 12000
    py = liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=4, motor="python")
    go = liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=4, motor="go")
    assert py["motor"] == "python" and go["motor"] == "go" and py["huella_salida"] != go["huella_salida"]
    se = math.sqrt(0.25 / n)
    for e in py["resultado"]["posiciones"]:
        for a, b in zip(py["resultado"]["posiciones"][e], go["resultado"]["posiciones"][e]):
            assert abs(a - b) < 5.5 * se * math.sqrt(2) / 1.0, (e, a, b)
        assert abs(py["resultado"]["puntos"][e]["media"] - go["resultado"]["puntos"][e]["media"]) < 0.6


@requiere_go
def test_go_respeta_la_misma_semilla_y_el_resultado_fijo():
    tabla, pend, lam = _mundo(5)
    a = liga.simular_temporada(tabla, pend, lam, n_sim=800, semilla=9, motor="go")
    assert a["huella_salida"] == liga.simular_temporada(tabla, pend, lam, n_sim=800, semilla=9, motor="go")["huella_salida"]
    esc = liga.simular_escenario({"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 600, "semilla": 2, "motor": "go"}, [{"local": "E0", "visitante": "E1", "gl": 6, "gv": 0}])
    assert esc["motor"] == "go" and esc["resultado"]["puntos"]["E1"]["p05"] >= 0


@requiere_go
def test_el_modo_filtrar_siempre_usa_python_porque_los_filtros_son_funciones():
    tabla, pend, lam = _mundo(5)
    r = liga.simular_escenario({"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 800, "semilla": 2}, [{"local": "E0", "visitante": "E1", "resultado": "1"}], modo="filtrar")
    assert r["motor"] == "python"


def test_si_el_binario_falta_o_falla_se_simula_en_python(monkeypatch, tmp_path):
    tabla, pend, lam = _mundo(5)
    monkeypatch.setenv("LAPLACE_GO_LSIM", str(tmp_path / "no_existe.exe"))
    monkeypatch.setattr(motor_go, "RAIZ", tmp_path)
    monkeypatch.setattr(motor_rust, "RAIZ", tmp_path)  # sin ningún núcleo nativo
    monkeypatch.setenv("LAPLACE_RUST_LSIM", str(tmp_path / "no_existe.exe"))
    assert not motor_go.disponible()
    assert liga.simular_temporada(tabla, pend, lam, n_sim=300, semilla=1)["motor"] == "python"
    falso = tmp_path / "falso.exe"
    falso.write_text("no es un ejecutable", encoding="utf-8")
    monkeypatch.setenv("LAPLACE_GO_LSIM", str(falso))
    with pytest.raises(motor_go.MotorNoDisponible):
        motor_go.correr([{"pts": 0, "gf": 0, "gc": 0}], [], 10, 1, ("puntos",), 0.0, 0.05)
    r = liga.simular_temporada(tabla, pend, lam, n_sim=300, semilla=1, motor="go")  # forzado, pero el binario roto cae a Python
    assert r["ok"] and r["resultado"]["posiciones"]


def test_la_variable_de_entorno_python_desactiva_el_motor(monkeypatch):
    monkeypatch.setenv("LAPLACE_MOTOR_SIM", "python")
    assert motor_go.ruta_binario() is None and liga.motor_para({}) == "python"


# ---------- revisión de seguridad: el tope grande solo vale si el cálculo irá en Go ----------
def test_el_tope_interno_de_python_corta_un_pedido_que_cayo_de_go_a_python(monkeypatch):
    monkeypatch.setattr(liga, "PRESUPUESTO_PYTHON", 1000)
    tabla, pend, lam = _mundo(5)
    with pytest.raises(liga.ErrorEntrada) as e:
        liga.simular_temporada(tabla, pend, lam, n_sim=500, semilla=1, motor="python")  # 500 × 20 > 1000
    assert e.value.como_dict()["error"] == "limite_excedido"


def test_el_router_usa_el_tope_chico_si_no_hay_go_o_si_el_modo_es_filtrar(monkeypatch):
    from backend.api.routers import ml_capacidades as r

    pendientes = [{"local": "A", "visitante": "B"}] * 380
    monkeypatch.setattr(r.liga.motor_rust, "disponible", lambda: False)  # el tope grande depende de que haya un núcleo nativo; aquí solo cuenta Go
    monkeypatch.setattr(r.liga.motor_go, "disponible", lambda: True)
    r._presupuesto(10_000, pendientes)  # 3,8 M: pasa con Go
    with pytest.raises(r.liga.ErrorEntrada):
        r._presupuesto(10_000, pendientes, motor_python=True)  # el mismo pedido en Python no
    monkeypatch.setattr(r.liga.motor_go, "disponible", lambda: False)
    with pytest.raises(r.liga.ErrorEntrada):
        r._presupuesto(10_000, pendientes)


def test_el_plazo_del_motor_es_menor_que_el_del_router():
    from backend.api.routers import ml_capacidades as r

    assert motor_go.PLAZO_SEGUNDOS < r.PLAZO_SEGUNDOS
