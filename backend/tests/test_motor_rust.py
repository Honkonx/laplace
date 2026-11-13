"""El núcleo Monte Carlo en Rust es estadísticamente equivalente a Python y a Go, es reproducible, encabeza la cadena Rust → Go → Python y declara el motor que de verdad corrió."""
import math

import pytest

from backend.api.ml.laplace import liga, motor_go, motor_rust

requiere_rust = pytest.mark.skipif(not motor_rust.disponible(), reason="sin binario de Rust (python backend/scripts/construir_rust.py)")


@pytest.fixture(autouse=True)
def _con_motor_real(monkeypatch):
    monkeypatch.delenv("LAPLACE_MOTOR_SIM", raising=False)


def _mundo(n=6):
    eq = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    pend = [{"local": a, "visitante": b} for a in eq for b in eq if a != b]
    return tabla, pend, lambda l, v: (1.5 if l == "E0" else 1.2, 0.9 if v == "E0" else 1.1)


def _cerca(a, b, n, tolerancia_se=5.5):
    se = math.sqrt(0.25 / n)
    for e in a["resultado"]["posiciones"]:
        for x, y in zip(a["resultado"]["posiciones"][e], b["resultado"]["posiciones"][e]):
            assert abs(x - y) < tolerancia_se * se * math.sqrt(2), (e, x, y)
        assert abs(a["resultado"]["puntos"][e]["media"] - b["resultado"]["puntos"][e]["media"]) < 0.6


@requiere_rust
def test_rust_y_python_dan_las_mismas_distribuciones_dentro_del_error_montecarlo():
    tabla, pend, lam = _mundo(6)
    n = 12000
    py = liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=4, motor="python")
    rs = liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=4, motor="rust")
    assert py["motor"] == "python" and rs["motor"] == "rust" and py["huella_salida"] != rs["huella_salida"]
    _cerca(py, rs, n)


@requiere_rust
@pytest.mark.skipif(not motor_go.disponible(), reason="sin binario de Go")
def test_rust_y_go_coinciden_entre_si():
    tabla, pend, lam = _mundo(6)
    n = 12000
    _cerca(liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=11, motor="go"), liga.simular_temporada(tabla, pend, lam, n_sim=n, semilla=11, motor="rust"), n)


@requiere_rust
def test_rust_es_reproducible_con_la_misma_semilla_y_respeta_el_resultado_fijado():
    tabla, pend, lam = _mundo(5)
    a = liga.simular_temporada(tabla, pend, lam, n_sim=2000, semilla=9, motor="rust")
    b = liga.simular_temporada(tabla, pend, lam, n_sim=2000, semilla=9, motor="rust")
    assert a["huella_salida"] == b["huella_salida"]
    esc = liga.simular_escenario({"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 600, "semilla": 2}, [{"local": "E0", "visitante": "E1", "gl": 6, "gv": 0}])
    assert esc["motor"] == "rust" and esc["resultado"]["puntos"]["E1"]["p05"] >= 0


@requiere_rust
def test_el_motor_por_defecto_es_rust_y_con_filtros_siempre_python():
    assert liga.motor_para({}) == "rust" and liga.motor_para({1: lambda a, b: True}) == "python"
    tabla, pend, lam = _mundo(5)
    r = liga.simular_escenario({"tabla": tabla, "pendientes": pend, "lambdas": lam, "n_sim": 800, "semilla": 2}, [{"local": "E0", "visitante": "E1", "resultado": "1"}], modo="filtrar")
    assert r["motor"] == "python"


def test_si_rust_falta_o_falla_la_cadena_sigue_y_la_respuesta_dice_que_motor_corrio(monkeypatch, tmp_path):
    tabla, pend, lam = _mundo(5)
    falso = tmp_path / "falso.exe"
    falso.write_text("no es un ejecutable", encoding="utf-8")
    monkeypatch.setenv("LAPLACE_RUST_LSIM", str(falso))
    with pytest.raises(motor_rust.MotorNoDisponible):
        motor_rust.correr([{"pts": 0, "gf": 0, "gc": 0}], [], 10, 1, ("puntos",), 0.0, 0.05)
    r = liga.simular_temporada(tabla, pend, lam, n_sim=300, semilla=1, motor="rust")  # Rust roto: cae a Go si existe y si no a Python
    assert r["ok"] and r["resultado"]["posiciones"]
    assert r["motor"] == ("go" if motor_go.disponible() else "python"), "declara el motor que de verdad corrió, no el pedido"
    monkeypatch.setenv("LAPLACE_GO_LSIM", str(falso))
    assert liga.simular_temporada(tabla, pend, lam, n_sim=300, semilla=1, motor="rust")["motor"] == "python"


def test_sin_ningun_binario_se_simula_en_python(monkeypatch, tmp_path):
    monkeypatch.setattr(motor_rust, "RAIZ", tmp_path)
    monkeypatch.setattr(motor_go, "RAIZ", tmp_path)
    monkeypatch.setenv("LAPLACE_RUST_LSIM", str(tmp_path / "no.exe"))
    monkeypatch.setenv("LAPLACE_GO_LSIM", str(tmp_path / "no.exe"))
    assert not liga.motor_nativo_disponible() and liga.motor_para({}) == "python"
    tabla, pend, lam = _mundo(5)
    assert liga.simular_temporada(tabla, pend, lam, n_sim=300, semilla=1)["motor"] == "python"


def test_la_variable_python_apaga_los_dos_nucleos(monkeypatch):
    monkeypatch.setenv("LAPLACE_MOTOR_SIM", "python")
    assert motor_rust.ruta_binario() is None and motor_go.ruta_binario() is None and liga.motor_para({}) == "python"
