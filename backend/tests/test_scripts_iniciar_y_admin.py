"""`iniciar` (aviso previo, flags), `laplace configurar` y `create_admin --si-no-hay` del instalador."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RAIZ = Path(__file__).resolve().parents[2]


def _cargar(ruta: str, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def laplace(tmp_path, monkeypatch):
    modulo = _cargar("install/comun/laplace.py", "laplace_iniciar_prueba")
    monkeypatch.setattr(modulo, "RAIZ", tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)   # como en un script o una tubería: nunca debe preguntar ni abrir el navegador
    return modulo


def test_el_aviso_previo_dice_que_falta_para_pronosticar_y_sugiere_configurar(laplace, tmp_path, capsys):
    (tmp_path / ".env").write_text("BSD_API_KEY=\nGROQ_API_KEY=algo-de-ia-12345\n", encoding="utf-8")
    laplace.avisar_antes_de_iniciar()
    salida = capsys.readouterr().out
    assert "cuotas" in salida and "calendario" in salida and "configurar" in salida


def test_el_aviso_previo_calla_cuando_lo_minimo_esta_puesto(laplace, tmp_path, capsys):
    (tmp_path / ".env").write_text("THE_ODDS_API_KEY=clave-cuotas-1234567\nBSD_API_KEY=clave-bsd-1234567\n", encoding="utf-8")
    laplace.avisar_antes_de_iniciar()
    assert capsys.readouterr().out == ""


def test_un_marcador_de_ejemplo_no_cuenta_como_clave_puesta(laplace, tmp_path, capsys):
    (tmp_path / ".env").write_text("THE_ODDS_API_KEY=your_the_odds_api_key\nBSD_API_KEY=your_bsd_api_key\n", encoding="utf-8")
    laplace.avisar_antes_de_iniciar()
    assert "cuotas" in capsys.readouterr().out


def test_un_fallo_al_avisar_nunca_impide_encender(laplace, tmp_path, capsys):
    laplace.avisar_antes_de_iniciar()           # sin .env: no debe lanzar
    assert "Traceback" not in capsys.readouterr().err


def test_sin_terminal_no_se_abre_el_navegador(laplace, monkeypatch):
    abiertas = []
    monkeypatch.setattr(laplace.webbrowser, "open", abiertas.append)
    laplace.abrir_web_al_terminar("127.0.0.1")
    assert abiertas == []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("LAPLACE_NO_ABRIR", "1")
    laplace.abrir_web_al_terminar("127.0.0.1")
    assert abiertas == []                       # y con LAPLACE_NO_ABRIR tampoco, aunque haya terminal
    monkeypatch.delenv("LAPLACE_NO_ABRIR")
    laplace.abrir_web_al_terminar("127.0.0.1")
    assert abiertas == [f"http://127.0.0.1:{laplace.SERVICIOS['backend']['puerto']}/"]


def test_laplace_configurar_pasa_sus_argumentos_tal_cual(laplace, monkeypatch):
    recibidos = []
    monkeypatch.setattr(laplace, "configurar", lambda argumentos=None: recibidos.append(argumentos) or 0)
    monkeypatch.setattr(sys, "argv", ["laplace.py", "configurar", "--probar", "--incluir-costosas"])
    assert laplace.main() == 0 and recibidos == [["--probar", "--incluir-costosas"]]


def test_iniciar_acepta_avisar_y_abrir(laplace, monkeypatch):
    llamadas = []
    monkeypatch.setattr(laplace, "iniciar", lambda lan, con_agente, avisar=False, abrir=False: llamadas.append((lan, con_agente, avisar, abrir)) or 0)
    monkeypatch.setattr(sys, "argv", ["laplace.py", "iniciar", "--avisar", "--abrir", "--sin-agente"])
    assert laplace.main() == 0 and llamadas == [(False, False, True, True)]


# --- create_admin --si-no-hay ---------------------------------------------------------------------------------------------

@pytest.fixture()
def admin(monkeypatch):
    modulo = _cargar("backend/scripts/create_admin.py", "create_admin_prueba")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(modulo, "engine", engine)
    monkeypatch.setattr(modulo, "SessionLocal", sessionmaker(bind=engine))
    return modulo


def _ejecutar(admin, monkeypatch, *argumentos):
    monkeypatch.setattr(sys, "argv", ["create_admin.py", *argumentos])
    admin.main()


def _hash(admin, nombre):
    with admin.SessionLocal() as db:
        return db.query(admin.Usuario).filter(admin.Usuario.username == nombre).one().password_hash


def test_si_no_hay_crea_el_primer_administrador_y_muestra_la_clave_una_vez(admin, monkeypatch, capsys):
    _ejecutar(admin, monkeypatch, "--username", "admin", "--si-no-hay")
    salida = capsys.readouterr().out
    assert "Usuario administrador: admin" in salida and "Contraseña: " in salida and "una sola vez" in salida and "Administración" in salida


def test_si_no_hay_no_toca_a_un_administrador_existente(admin, monkeypatch, capsys):
    _ejecutar(admin, monkeypatch, "--username", "admin", "--si-no-hay")
    antes = _hash(admin, "admin")
    capsys.readouterr()
    _ejecutar(admin, monkeypatch, "--username", "otro", "--si-no-hay")
    salida = capsys.readouterr().out
    assert "Ya hay un administrador (admin)" in salida and "Contraseña" not in salida
    assert _hash(admin, "admin") == antes                                    # reinstalar no resetea la contraseña
    with admin.SessionLocal() as db:
        assert db.query(admin.Usuario).filter(admin.Usuario.username == "otro").first() is None


def test_sin_el_flag_sigue_creando_o_reseteando_como_antes(admin, monkeypatch, capsys):
    _ejecutar(admin, monkeypatch, "--username", "admin")
    antes = _hash(admin, "admin")
    _ejecutar(admin, monkeypatch, "--username", "admin", "--password", "otra-clave-nueva-123")
    assert _hash(admin, "admin") != antes
