"""Script `configurar` (install/comun/configurar.py): detectar, probar, guardar sin filtrar claves, y el recorrido de la lista numerada."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from backend.api.core import conexiones as cx

RAIZ = Path(__file__).resolve().parents[2]
CLAVE_BUENA = "buena-clave-de-prueba-1234567890"
CLAVE_MALA = "mala-clave-de-prueba-1234567890"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("configurar_prueba", RAIZ / "install" / "comun" / "configurar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    env = tmp_path / ".env"
    env.write_text("KAIROS_AUTH_SECRET=" + "k" * 40 + "\nTELEGRAM_BOT_TOKEN=\nAGENT_IA_ACTIVA=false\nSPORTS_ADMIN_IDS=\n", encoding="utf-8")
    monkeypatch.setattr(modulo.entorno, "ENV", env)
    return modulo


def probar_falso(conexion, clave):
    return cx.Resultado(cx.ESTADO_FALLA, "clave inválida (HTTP 401)", 401) if clave.startswith("mala") else cx.Resultado(cx.ESTADO_OK, "válida · 500 créditos", 200)


class Guion:
    """Simula el teclado: devuelve respuestas en orden y recuerda todo lo que se le preguntó."""
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.preguntas: list[str] = []

    def __call__(self, texto):
        self.preguntas.append(texto)
        if not self.respuestas:
            raise EOFError
        return self.respuestas.pop(0)


def sesion(cfg, entradas=(), claves=(), probar=probar_falso, abrir=None):
    salida: list[str] = []
    s = cfg.Sesion(entrada=Guion(*entradas), clave=Guion(*claves), pantalla=cfg.Pantalla(salida.append, color=False), probar=probar, abrir_url=abrir or (lambda url: None))
    return s, salida


def leer_env(cfg):
    return cfg.entorno.ENV.read_text(encoding="utf-8")


# --- .env ------------------------------------------------------------------------------------------------------------------

def test_guardar_env_es_atomico_y_no_deja_temporales(cfg):
    lineas = cfg.cargar_env()
    cfg.entorno.poner(lineas, "BSD_API_KEY", CLAVE_BUENA)
    cfg.guardar_env(lineas)
    assert f"BSD_API_KEY={CLAVE_BUENA}" in leer_env(cfg) and "KAIROS_AUTH_SECRET=" in leer_env(cfg)
    assert not list(cfg.entorno.ENV.parent.glob("*.tmp"))
    if os.name != "nt":
        assert (cfg.entorno.ENV.stat().st_mode & 0o777) == 0o600


def test_poner_clave_valida_el_formato_y_completa_modelo_y_agente(cfg):
    lineas = cfg.cargar_env()
    ollama = cx.por_id("ollama_cloud")
    assert cfg.poner_clave(lineas, ollama, "con espacios no vale 12345") is not None
    assert cfg.entorno.valor_de(lineas, "OLLAMA_API_KEY") is None            # no se tocó nada
    assert cfg.poner_clave(lineas, ollama, CLAVE_BUENA) is None
    assert cfg.entorno.valor_de(lineas, "OLLAMA_CLOUD_MODEL") == "gpt-oss:120b"   # modelo por defecto
    assert cfg.entorno.valor_de(lineas, "AGENT_IA_ACTIVA") == "true"              # hay una clave de IA: el agente la usa


def test_las_claves_de_ejemplo_no_cuentan_como_puestas(cfg):
    lineas = cfg.cargar_env()
    cfg.entorno.poner(lineas, "BSD_API_KEY", "your_bsd_api_key")
    assert "bsd" not in cfg.definidas(lineas)


# --- detección -------------------------------------------------------------------------------------------------------------

def test_detectar_sin_claves_marca_todo_sin_clave_y_sin_tocar_la_red(cfg):
    llamadas = []
    estados = cfg.detectar(cfg.cargar_env(), probar=lambda c, k: llamadas.append(c.id) or probar_falso(c, k))
    assert len(estados) == 13 and all(r.estado == cx.ESTADO_FALLA and r.detalle == "sin clave" for r in estados.values()) and llamadas == []


def test_detectar_prueba_las_gratuitas_y_deja_las_de_coste_como_aviso(cfg):
    lineas = cfg.cargar_env()
    for variable in ("THE_ODDS_API_KEY", "LIVESCORE6_KEY", "OLLAMA_API_KEY", "GROQ_API_KEY"):
        cfg.entorno.poner(lineas, variable, CLAVE_BUENA)
    cfg.entorno.poner(lineas, "GROQ_API_KEY", CLAVE_MALA)
    probadas = []
    estados = cfg.detectar(lineas, probar=lambda c, k: probadas.append(c.id) or probar_falso(c, k))
    assert sorted(probadas) == ["groq", "the-odds-api"]                       # LiveScore6 y Ollama NO se tocan sin permiso
    assert estados["the-odds-api"].estado == cx.ESTADO_OK and estados["groq"].estado == cx.ESTADO_FALLA
    assert estados["livescore6"].estado == cx.ESTADO_AVISO and "cobra por llamada" in estados["livescore6"].detalle
    assert estados["ollama_cloud"].estado == cx.ESTADO_AVISO and "≈ 1 token" in estados["ollama_cloud"].detalle
    de_pago = cfg.detectar(lineas, probar=probar_falso, costosas={"livescore6", "ollama_cloud"})
    assert de_pago["livescore6"].estado == cx.ESTADO_OK and de_pago["ollama_cloud"].estado == cx.ESTADO_OK


def test_detectar_sin_red_solo_dice_que_hay_algo_puesto(cfg):
    lineas = cfg.cargar_env()
    cfg.entorno.poner(lineas, "BSD_API_KEY", CLAVE_BUENA)
    estados = cfg.detectar(lineas, probar=lambda *_: pytest.fail("no debe conectarse"), con_red=False)
    assert estados["bsd"].detalle == "configurada (sin probar)" and estados["telegram"].detalle == "sin clave"


# --- recorrido interactivo -------------------------------------------------------------------------------------------------

def test_pegar_una_clave_valida_la_prueba_la_guarda_y_nunca_la_muestra(cfg):
    s, salida = sesion(cfg, entradas=["4", "p", "v", "q"], claves=[CLAVE_BUENA])
    assert s.ejecutar() == 0
    assert f"THE_ODDS_API_KEY={CLAVE_BUENA}" in leer_env(cfg)
    texto = "\n".join(salida)
    assert CLAVE_BUENA not in texto and "✓ válida · 500 créditos" in texto and "Cambios guardados en .env" in texto
    assert "THE ODDS API" in texto.upper() and "https://the-odds-api.com" in texto


def test_una_clave_invalida_no_se_guarda_y_no_pisa_la_anterior(cfg):
    s, salida = sesion(cfg, entradas=["4", "p", "p", "v", "q"], claves=[CLAVE_BUENA, CLAVE_MALA])
    s.ejecutar()
    assert f"THE_ODDS_API_KEY={CLAVE_BUENA}" in leer_env(cfg) and CLAVE_MALA not in leer_env(cfg)
    texto = "\n".join(salida)
    assert CLAVE_MALA not in texto and "No se guardó nada" in texto
    assert s.estados["the-odds-api"].estado == cx.ESTADO_OK


def test_un_formato_imposible_se_rechaza_sin_llamar_a_la_red(cfg):
    s, salida = sesion(cfg, entradas=["4", "p", "v", "q"], claves=["tiene espacios y no sirve 123"], probar=lambda *_: pytest.fail("no debe probar"))
    s.ejecutar()
    assert "THE_ODDS_API_KEY=\n" not in leer_env(cfg) or "THE_ODDS_API_KEY=tiene" not in leer_env(cfg)
    assert "No se guardó nada" in "\n".join(salida)


def test_borrar_una_clave_pide_confirmacion(cfg):
    s, _ = sesion(cfg, entradas=["4", "p", "b", "n", "b", "s", "v", "q"], claves=[CLAVE_BUENA])
    s.ejecutar()
    assert "THE_ODDS_API_KEY=\n" in leer_env(cfg) + "\n" and CLAVE_BUENA not in leer_env(cfg)


def test_las_pruebas_con_coste_solo_se_hacen_si_el_usuario_las_acepta(cfg):
    lineas = cfg.cargar_env()
    cfg.entorno.poner(lineas, "LIVESCORE6_KEY", CLAVE_BUENA)
    cfg.entorno.poner(lineas, "OLLAMA_API_KEY", CLAVE_BUENA)
    cfg.guardar_env(lineas)
    probadas = []
    s, salida = sesion(cfg, entradas=["n", "q"], probar=lambda c, k: probadas.append(c.id) or probar_falso(c, k))
    s.ejecutar()
    assert probadas == [] and any("LiveScore6" in x and "Ollama" in x for x in s.entrada.preguntas)  # se avisó del coste antes de preguntar
    s2, _ = sesion(cfg, entradas=["s", "q"], probar=lambda c, k: probadas.append(c.id) or probar_falso(c, k))
    s2.ejecutar()
    assert sorted(probadas) == ["livescore6", "ollama_cloud"]


def test_abrir_el_enlace_solo_si_se_confirma(cfg):
    abiertas = []
    s, _ = sesion(cfg, entradas=["4", "a", "n", "a", "s", "v", "q"], abrir=abiertas.append)
    s.ejecutar()
    assert abiertas == ["https://the-odds-api.com"]


def test_cambiar_el_orden_de_la_ia_escribe_los_cuatro_roles(cfg):
    s, salida = sesion(cfg, entradas=["o", "3 1", "v", "q"])
    s.ejecutar()
    esperado = "gemini,ollama_cloud,groq,openrouter,claude"
    for rol in cx.ROLES_IA:
        assert f"{rol}={esperado}" in leer_env(cfg), rol
    assert cfg.orden_ia(cfg.cargar_env())[0] == "gemini"


def test_el_id_de_administrador_solo_acepta_numeros(cfg):
    s, _ = sesion(cfg, entradas=["a", "abc", "a", "123456789, 987654321", "q"])
    s.ejecutar()
    assert "SPORTS_ADMIN_IDS=123456789,987654321" in leer_env(cfg)


def test_canal_y_grupo_se_pueden_poner_y_vaciar(cfg):
    s, _ = sesion(cfg, entradas=["c", "@mi_canal", "https://t.me/mi_grupo", "Mi comunidad", "c", "-", "", "", "q"])
    s.ejecutar()
    texto = leer_env(cfg)
    assert "TELEGRAM_CANAL_ID=\n" in texto and "TELEGRAM_GRUPO_URL=https://t.me/mi_grupo" in texto and "TELEGRAM_GRUPO_NOMBRE=Mi comunidad" in texto


def test_ctrl_c_o_ctrl_z_en_medio_no_revientan_ni_dejan_a_medias(cfg):
    s, _ = sesion(cfg, entradas=["4"])   # se acaba la entrada dentro del detalle: EOF
    assert s.ejecutar() == 0


def test_solo_con_un_id_desconocido_lo_dice_y_devuelve_error(cfg):
    s, salida = sesion(cfg)
    assert s.ejecutar(solo="no-existe") == 2 and "No conozco" in "\n".join(salida)


def test_la_lista_dice_que_falta_para_pronosticar_y_marca_lo_principal(cfg):
    s, salida = sesion(cfg, entradas=["q"])
    s.ejecutar()
    texto = "\n".join(salida)
    assert "aún falta" in texto and "lo principal" in texto and texto.count("✗ sin clave") == 13


# --- línea de comandos ------------------------------------------------------------------------------------------------------

def test_main_sin_env_pide_instalar_primero(cfg, monkeypatch, capsys):
    cfg.entorno.ENV.unlink()
    monkeypatch.setattr(sys, "argv", ["configurar.py", "--estado"])
    assert cfg.main() == 1 and "instalador" in capsys.readouterr().err


def test_main_estado_no_se_conecta_a_nada_ni_imprime_claves(cfg, monkeypatch, capsys):
    lineas = cfg.cargar_env()
    cfg.entorno.poner(lineas, "BSD_API_KEY", CLAVE_BUENA)
    cfg.guardar_env(lineas)
    monkeypatch.setattr(cfg.cx, "probar", lambda *_: pytest.fail("--estado no debe conectarse"))
    monkeypatch.setattr(sys, "argv", ["configurar.py", "--estado"])
    assert cfg.main() == 0
    salida = capsys.readouterr().out
    assert CLAVE_BUENA not in salida and "configurada (sin probar)" in salida


def test_main_interactivo_exige_terminal(cfg, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["configurar.py"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cfg.main() == 1 and "terminal" in capsys.readouterr().err
