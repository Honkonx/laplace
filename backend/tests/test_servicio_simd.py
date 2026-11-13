"""Microservicio en Go (`modelo/go/simd`) con el núcleo Rust real: responde el mismo cálculo, solo escucha en local, respeta el cupo y su plazo MATA el proceso del cálculo."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from backend.api.ml.laplace import liga, motor_nativo, motor_rust

BIN_GO = motor_nativo.RAIZ / "modelo" / "go" / "bin" / ("simd" + motor_nativo.EXTENSION)
requiere_ambos = pytest.mark.skipif(not (BIN_GO.is_file() and motor_rust.ruta_binario()), reason="falta simd o el núcleo Rust (python backend/scripts/construir_go.py y construir_rust.py)")


@pytest.fixture(autouse=True)
def _con_motor_real(monkeypatch):
    monkeypatch.delenv("LAPLACE_MOTOR_SIM", raising=False)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def servicio(monkeypatch):
    puerto = _puerto_libre()
    entorno = {**os.environ, "LAPLACE_SIMD_ADDR": f"127.0.0.1:{puerto}", "LAPLACE_SIMD_NUCLEO": str(motor_rust.ruta_binario()), "LAPLACE_SIMD_MAX": "1", "LAPLACE_SIMD_PLAZO": "2"}
    proceso = subprocess.Popen([str(BIN_GO)], env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(50):
        try:
            urllib.request.urlopen(url + "/salud", timeout=0.5).read()  # noqa: S310
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    else:
        proceso.kill()
        pytest.fail("simd no arrancó")
    yield url
    proceso.kill()
    proceso.wait(5)


def _mundo(n=5):
    eq = [f"E{i}" for i in range(n)]
    tabla = [{"equipo": e, "pj": 0, "pts": 0, "gf": 0, "gc": 0} for e in eq]
    pend = [{"local": a, "visitante": b} for a in eq for b in eq if a != b]
    return tabla, pend, lambda l, v: (1.4, 1.1)


def _carga(n_sim):
    return json.dumps({"equipos": [{"pts": 0, "gf": 0, "gc": 0}] * 4, "partidos": [{"h": 0, "a": 1, "lh": 1.4, "la": 1.1, "fijo": None}], "n_sim": n_sim, "semilla": 1, "desempates": ["puntos"], "sigma": 0.0, "paso": 0.05}).encode()


def _post(url, cuerpo, plazo=10):
    return urllib.request.urlopen(urllib.request.Request(url + "/v1/simular", data=cuerpo, method="POST"), timeout=plazo)  # noqa: S310


@requiere_ambos
def test_el_servicio_devuelve_el_mismo_calculo_que_el_binario(servicio, monkeypatch):
    monkeypatch.setenv("LAPLACE_SIMD_URL", servicio)
    tabla, pend, lam = _mundo()
    por_servicio = liga.simular_temporada(tabla, pend, lam, n_sim=3000, semilla=5, motor="rust")
    monkeypatch.delenv("LAPLACE_SIMD_URL")
    directo = liga.simular_temporada(tabla, pend, lam, n_sim=3000, semilla=5, motor="rust")
    assert por_servicio["motor"] == "rust" and por_servicio["huella_salida"] == directo["huella_salida"], "mismo núcleo y misma semilla: mismo resultado"


@requiere_ambos
def test_si_el_servicio_esta_apagado_se_usa_el_binario_directo(monkeypatch):
    monkeypatch.setenv("LAPLACE_SIMD_URL", f"http://127.0.0.1:{_puerto_libre()}")
    tabla, pend, lam = _mundo()
    r = liga.simular_temporada(tabla, pend, lam, n_sim=500, semilla=1, motor="rust")
    assert r["ok"] and r["motor"] == "rust"


def test_solo_se_llama_al_servicio_por_la_interfaz_local():
    with pytest.raises(motor_nativo.MotorNoDisponible):
        motor_nativo.correr_servicio("http://example.com:9200", [{"pts": 0, "gf": 0, "gc": 0}], [], 10, 1, ("puntos",), 0.0, 0.05)


@requiere_ambos
def test_el_plazo_del_servicio_responde_504_y_mata_el_proceso_del_calculo(servicio):
    try:
        _post(servicio, _carga(2_000_000_000))  # horas de cálculo: el plazo del servicio es 2 s
        pytest.fail("debía vencer el plazo")
    except urllib.error.HTTPError as e:
        assert e.code == 504
    time.sleep(0.5)
    vivos = subprocess.run(["tasklist", "/FI", "IMAGENAME eq lsim.exe"], capture_output=True, text=True, check=False).stdout if os.name == "nt" else subprocess.run(["pgrep", "-x", "lsim"], capture_output=True, text=True, check=False).stdout  # noqa: S603, S607
    assert "lsim" not in vivos.replace("INFO: No tasks", ""), "el proceso del cálculo debía morir con el plazo"
    assert json.loads(_post(servicio, _carga(100)).read())["utiles"] == 100, "y el cupo volvió"


@requiere_ambos
def test_con_el_cupo_lleno_la_segunda_recibe_503(servicio):
    import threading

    primera = threading.Thread(target=lambda: _intentar(servicio))
    primera.start()
    time.sleep(0.5)
    try:
        _post(servicio, _carga(100))
        pytest.fail("debía rechazarse con 503")
    except urllib.error.HTTPError as e:
        assert e.code == 503 and e.headers.get("Retry-After")
    primera.join(10)


def _intentar(url):
    try:
        _post(url, _carga(2_000_000_000), plazo=5)
    except (urllib.error.URLError, OSError):
        pass


@requiere_ambos
def test_el_servicio_rechaza_una_entrada_que_no_es_json(servicio):
    try:
        _post(servicio, b"no es json")
        pytest.fail("debía rechazarse con 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400
