"""Instalación portable (install/): pines con huellas, asistente del .env sin filtrar secretos, control del servicio y diagnóstico."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PLATAFORMAS = {"windows-x64", "windows-arm64", "linux-x64", "linux-arm64", "macos-x64", "macos-arm64"}


def _cargar(ruta: str, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# --- runtime-pins.json --------------------------------------------------------------------------------------------------------

def test_los_pines_cubren_todas_las_plataformas_con_huellas_sha256_validas():
    pines = json.loads((RAIZ / "install" / "runtime-pins.json").read_text(encoding="utf-8"))
    assert pines["python"] and pines["pnpm"]
    for nombre in ("uv", "node"):
        assert "{version}" in pines[nombre]["url"] and "{archivo}" in pines[nombre]["url"]
        assert set(pines[nombre]["archivos"]) == PLATAFORMAS, nombre
        for plataforma, datos in pines[nombre]["archivos"].items():
            assert re.fullmatch(r"[0-9a-f]{64}", datos["sha256"]), (nombre, plataforma)
            if nombre == "node":  # los archivos de uv no llevan la versión en el nombre (va en la URL)
                assert pines[nombre]["version"] in datos["archivo"], (nombre, plataforma)


def test_el_pnpm_fijado_es_el_que_declaran_los_package_json():
    pines = json.loads((RAIZ / "install" / "runtime-pins.json").read_text(encoding="utf-8"))
    for proyecto in ("frontend", "pwa"):
        declarado = json.loads((RAIZ / proyecto / "package.json").read_text(encoding="utf-8"))["packageManager"]
        assert declarado == f"pnpm@{pines['pnpm']}", proyecto


# --- asistente del .env -------------------------------------------------------------------------------------------------------

@pytest.fixture()
def asistente(tmp_path, monkeypatch):
    modulo = _cargar("install/comun/configurar_env.py", "configurar_env_prueba")
    (tmp_path / ".env.example").write_text(
        "SPORTS_ADMIN_IDS=comma,separated,user_ids\nTELEGRAM_BOT_TOKEN=your_bot_token\nKAIROS_AUTH_SECRET=your_kairos_auth_secret\n"
        "WEB_JWT_SECRET=your_web_jwt_secret_min_32_bytes\nOLLAMA_API_KEY=\nAGENT_IA_ACTIVA=false\nCORS_ORIGINS=http://localhost:9002\n", encoding="utf-8")
    monkeypatch.setattr(modulo, "ENV", tmp_path / ".env")
    monkeypatch.setattr(modulo, "EJEMPLO", tmp_path / ".env.example")
    monkeypatch.setattr(modulo.sys, "stdin", type("Sin", (), {"isatty": lambda self: False})())
    return modulo


def test_crea_el_env_sin_placeholders_y_con_secretos_propios(asistente, monkeypatch, capsys):
    monkeypatch.setattr(asistente.sys, "argv", ["configurar_env.py", "--sin-asistente"])
    assert asistente.main() == 0
    texto = asistente.ENV.read_text(encoding="utf-8")
    valores = dict(linea.split("=", 1) for linea in texto.splitlines() if "=" in linea)
    assert valores["TELEGRAM_BOT_TOKEN"] == "" and valores["SPORTS_ADMIN_IDS"] == ""
    assert len(valores["KAIROS_AUTH_SECRET"]) >= 32 and len(valores["WEB_JWT_SECRET"]) >= 32
    assert valores["KAIROS_AUTH_SECRET"] != valores["WEB_JWT_SECRET"]
    assert "http://127.0.0.1:9001" in valores["CORS_ORIGINS"] and "http://localhost:9002" in valores["CORS_ORIGINS"]
    salida = capsys.readouterr().out
    assert valores["KAIROS_AUTH_SECRET"] not in salida and valores["WEB_JWT_SECRET"] not in salida  # nunca se imprime un secreto


def test_un_valor_ya_definido_no_se_pisa_y_el_agente_usa_la_ia_si_hay_clave(asistente, monkeypatch):
    asistente.ENV.write_text("TELEGRAM_BOT_TOKEN=123:ABC\nOLLAMA_API_KEY=clave-real\nAGENT_IA_ACTIVA=false\nKAIROS_AUTH_SECRET=" + "k" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(asistente.sys, "argv", ["configurar_env.py", "--sin-asistente"])
    asistente.main()
    valores = dict(linea.split("=", 1) for linea in asistente.ENV.read_text(encoding="utf-8").splitlines() if "=" in linea)
    assert valores["TELEGRAM_BOT_TOKEN"] == "123:ABC" and valores["KAIROS_AUTH_SECRET"] == "k" * 40
    assert valores["AGENT_IA_ACTIVA"] == "true"  # hay una clave de IA


def test_el_asistente_del_env_ya_no_pregunta_claves_eso_lo_hace_configurar(asistente, monkeypatch, capsys):
    """Desde 2026-11-09 las claves las detecta, prueba y guarda `configurar.py`; el asistente del .env solo crea el archivo y los secretos propios."""
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("el asistente no debe preguntar nada"))
    assert not hasattr(asistente, "getpass") and not hasattr(asistente, "PREGUNTAS")
    lineas = asistente.crear_base()
    asistente.aplicar(lineas, reconfigurar=False)
    assert asistente.valor_de(lineas, "OLLAMA_API_KEY") in (None, "")
    salida = capsys.readouterr().out
    assert "conexiones con clave" in salida and "configurar" in salida
    assert asistente.valor_de(lineas, "KAIROS_AUTH_SECRET") not in salida  # nunca se imprime un secreto


def test_los_instaladores_ofrecen_configurar_y_crear_el_administrador_solo_con_terminal():
    ps1 = (RAIZ / "install" / "windows" / "instalar.ps1").read_text(encoding="utf-8-sig")
    sh = (RAIZ / "install" / "linux" / "instalar.sh").read_text(encoding="utf-8")
    for texto in (ps1, sh):
        assert "install" in texto and "configurar.py" in texto and "create_admin.py" in texto and "--si-no-hay" in texto
        assert "configurar_env.py --reconfigurar" not in texto  # -Reconfigurar ya no regenera los secretos propios
    assert "IsInputRedirected" in ps1 and "[ -t 0 ]" in sh                      # sin terminal (CI, tuberías) no pregunta
    assert "-not $SinAsistente" in ps1 and '"$SIN_ASISTENTE" != 1' in sh          # con -SinAsistente no pregunta nada


def test_los_cuatro_lanzadores_nuevos_existen_y_apuntan_a_los_scripts_correctos():
    contenido = {n: (RAIZ / n).read_text(encoding="utf-8") for n in ("configurar.bat", "configurar.sh", "iniciar.bat", "iniciar.sh")}
    assert all("configurar.py" in contenido[n] for n in ("configurar.bat", "configurar.sh"))
    assert all("laplace.py" in contenido[n] and "iniciar --avisar --abrir" in contenido[n] for n in ("iniciar.bat", "iniciar.sh"))
    assert all("runtime\\venv" in contenido[n] or "runtime/venv" in contenido[n] for n in contenido)


# --- control del servicio y diagnóstico ---------------------------------------------------------------------------------------

def test_el_control_respeta_los_puertos_por_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("LAPLACE_PUERTO_BACKEND", "9555")
    monkeypatch.setenv("LAPLACE_PUERTO_AGENTE", "9556")
    modulo = _cargar("install/comun/laplace.py", "laplace_control_prueba")
    assert modulo.SERVICIOS["backend"]["puerto"] == 9555 and modulo.SERVICIOS["agente"]["puerto"] == 9556


def test_el_control_agrega_los_origenes_cors_sin_quitar_los_existentes(tmp_path, monkeypatch):
    modulo = _cargar("install/comun/laplace.py", "laplace_cors_prueba")
    (tmp_path / ".env").write_text("CORS_ORIGINS=http://a.test,http://b.test\n", encoding="utf-8")
    monkeypatch.setattr(modulo, "RAIZ", tmp_path)
    assert modulo._origenes_cors("http://c.test") == "http://a.test,http://b.test,http://c.test"
    assert modulo._origenes_cors("http://a.test") == "http://a.test,http://b.test"


def test_un_proceso_inexistente_no_esta_vivo():
    modulo = _cargar("install/comun/laplace.py", "laplace_vivo_prueba")
    assert modulo._vivo(2_000_000_000) is False


def test_el_diagnostico_nunca_imprime_valores_de_claves(tmp_path, monkeypatch):
    doctor = _cargar("backend/scripts/doctor.py", "doctor_prueba")
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=123456:TOKEN-SECRETO\nOLLAMA_API_KEY=clave-secreta-ia\nKAIROS_AUTH_SECRET=" + "s" * 40 + "\nWEB_JWT_SECRET=" + "w" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "RAIZ", tmp_path)
    texto = json.dumps(doctor.revisar_env(), ensure_ascii=False)
    assert "TOKEN-SECRETO" not in texto and "clave-secreta-ia" not in texto and ("s" * 40) not in texto
    assert "token definido" in texto and "ollama" in texto


def test_el_diagnostico_marca_fallo_si_falta_el_env(tmp_path, monkeypatch):
    doctor = _cargar("backend/scripts/doctor.py", "doctor_sin_env_prueba")
    monkeypatch.setattr(doctor, "RAIZ", tmp_path)
    assert doctor.revisar_env()[0][1] == "fallo"


# --- empaquetado ---------------------------------------------------------------------------------------------------------------

def test_el_empaquetador_normaliza_los_fines_de_linea(tmp_path):
    empaquetar = _cargar("install/empaquetar.py", "empaquetar_prueba")
    (tmp_path / "a.sh").write_bytes(b"#!/usr/bin/env bash\r\necho hola\r\n")
    (tmp_path / "b.bat").write_bytes(b"@echo off\necho hola\n")
    empaquetar.normalizar_fines_de_linea(tmp_path)
    assert b"\r" not in (tmp_path / "a.sh").read_bytes()
    assert (tmp_path / "b.bat").read_bytes() == b"@echo off\r\necho hola\r\n"


def test_los_scripts_de_instalacion_no_tienen_caracteres_de_control_ni_cr_en_los_sh():
    for ruta in ("instalar.bat", "laplace.bat", "install/windows/instalar.ps1"):
        crudo = (RAIZ / ruta).read_bytes()
        assert not [b for b in crudo if b < 32 and b not in (9, 10, 13)], ruta  # p. ej. un \v dentro de una ruta
    for ruta in ("instalar.sh", "laplace.sh", "install/linux/instalar.sh"):
        assert b"\r" not in (RAIZ / ruta).read_bytes().replace(b"\r\n", b"\n"), ruta  # los .sh se guardan con LF en el índice (.gitattributes)
    assert (RAIZ / "install" / "windows" / "instalar.ps1").read_bytes().startswith(b"\xef\xbb\xbf")  # BOM: PowerShell 5.1 lee bien los acentos


# --- lanzadores: encontrar el entorno y no cerrarse sin dejar leer (defecto real del 2026-11-09) -----------------------------

LANZADORES_BAT = ("instalar.bat", "configurar.bat", "iniciar.bat", "laplace.bat")


def test_los_lanzadores_buscan_el_entorno_en_runtime_y_en_los_venv_de_trabajo():
    """Regresión: configurar.bat solo buscaba runtime\\venv y en la carpeta de trabajo (.venv_backend) imprimía un error y se cerraba."""
    for nombre in ("configurar.bat", "iniciar.bat", "laplace.bat"):
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        assert all(c in texto for c in ('"runtime\\venv"', '".venv"', '".venv_backend"')), nombre
    for nombre in ("configurar.sh", "iniciar.sh", "laplace.sh"):
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        assert "runtime/venv" in texto and ".venv" in texto and ".venv_backend" in texto, nombre


def test_los_bat_esperan_una_tecla_solo_con_doble_clic_y_se_pueden_silenciar():
    for nombre in LANZADORES_BAT:
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        assert "pause" in texto and "cmdcmdline" in texto and "LAPLACE_SIN_PAUSA" in texto, nombre


@pytest.mark.skipif(os.name != "nt", reason="ejecuta un .bat de Windows")
def test_configurar_bat_sin_entorno_dice_que_hacer_y_espera_en_lugar_de_cerrarse(tmp_path):
    import shutil
    import subprocess

    copia = tmp_path / "configurar.bat"
    shutil.copy(RAIZ / "configurar.bat", copia)
    entorno = {k: v for k, v in os.environ.items() if k != "LAPLACE_SIN_PAUSA"}
    # Como lo lanza el Explorador con doble clic: cmd /c ""ruta\configurar.bat" "
    doble_clic = subprocess.run(f'cmd.exe /c ""{copia}" "', capture_output=True, text=True, stdin=subprocess.DEVNULL, env=entorno, timeout=60, check=False)
    salida = doble_clic.stdout + doble_clic.stderr
    assert "no esta instalado" in salida and "instalar.bat" in salida
    assert "tecla" in salida.lower() or "press any key" in salida.lower()          # la ventana espera: el mensaje se alcanza a leer
    entorno["LAPLACE_SIN_PAUSA"] = "1"
    silencioso = subprocess.run(f'cmd.exe /c ""{copia}" "', capture_output=True, text=True, stdin=subprocess.DEVNULL, env=entorno, timeout=60, check=False)
    assert "tecla" not in (silencioso.stdout + silencioso.stderr).lower() and silencioso.returncode == 1
