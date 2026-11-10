"""Registro único de conexiones externas (core/conexiones.py): estructura, alineación con el resto del proyecto y reglas de validez de cada prueba."""
from __future__ import annotations

import io
import re
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

import pytest

from backend.api.core import conexiones as cx
from backend.api.core.config import Settings

RAIZ = Path(__file__).resolve().parents[2]


class _Respuesta:
    def __init__(self, estado: int, cuerpo: str = "{}", cabeceras: dict | None = None):
        self.status = estado
        self.headers = cabeceras or {}
        self._cuerpo = cuerpo.encode()

    def read(self, _n=-1):
        return self._cuerpo

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _abrir(respuesta=None, error=None, capturar=None):
    def abrir(peticion, timeout=None):
        if capturar is not None:
            capturar.append(peticion)
        if error is not None:
            raise error
        return respuesta
    return abrir


# --- estructura -----------------------------------------------------------------------------------------------------------

def test_el_registro_tiene_13_conexiones_numeradas_sin_repetir():
    assert [c.numero for c in cx.CONEXIONES] == list(range(1, 14))
    assert len({c.id for c in cx.CONEXIONES}) == 13 and len({c.variable for c in cx.CONEXIONES}) == 13
    assert {c.grupo for c in cx.CONEXIONES} == {g.id for g in cx.GRUPOS}


def test_cada_prueba_va_por_https_al_host_oficial_y_lleva_la_clave():
    for c in cx.CONEXIONES:
        metodo, url, cabeceras, _ = cx.armar_peticion(c, "CLAVE-DE-PRUEBA-123", "20261109")
        assert url.startswith("https://") and urlparse(url).hostname == c.host, c.id
        visible = url + " ".join(cabeceras.values())
        assert "CLAVE-DE-PRUEBA-123" in visible and "{clave}" not in visible and "{hoy}" not in visible, c.id


def test_toda_prueba_manda_un_user_agent_propio_porque_cloudflare_bloquea_el_de_urllib():
    """Regresión 2026-11-09: Groq respondía 403 (Cloudflare 1010) al User-Agent de urllib y una clave válida salía como inválida."""
    for c in cx.CONEXIONES:
        _, _, cabeceras, _ = cx.armar_peticion(c, "CLAVE-DE-PRUEBA-123", "20261109")
        assert cabeceras.get("User-Agent") == cx.USER_AGENT and "urllib" not in cabeceras["User-Agent"].lower(), c.id


def test_un_403_de_cloudflare_es_un_bloqueo_no_una_clave_invalida():
    r = cx.evaluar(_c("groq"), 403, {}, "error code: 1010")
    assert r.estado == cx.ESTADO_AVISO and "no es un problema de tu clave" in r.detalle
    assert cx.evaluar(_c("groq"), 403, {}, '{"error": "forbidden"}').estado == cx.ESTADO_FALLA  # un 403 normal sigue siendo clave inválida


def test_solo_livescore6_cobra_por_llamada_y_solo_ollama_cuesta_algo():
    assert [c.id for c in cx.CONEXIONES if c.prueba.cobra_por_llamada] == ["livescore6"]
    assert [c.id for c in cx.CONEXIONES if c.prueba.cuesta] == ["ollama_cloud"]


def test_el_enlace_para_conseguir_la_clave_es_https_en_todas():
    assert all(c.enlace.startswith("https://") for c in cx.CONEXIONES)


# --- alineación con el resto del proyecto (lo que se desalineaba antes) ----------------------------------------------------

def test_todas_las_variables_del_registro_existen_como_campo_de_la_configuracion():
    campos = set(Settings.model_fields)
    faltan = sorted(v for v in cx.variables_declaradas() if v not in campos)
    assert not faltan, f"variables del registro que Settings no conoce: {faltan}"


@pytest.mark.parametrize("ruta", [".env.example", "publico/.env.example"])
def test_los_ejemplos_de_env_traen_todas_las_variables_del_registro(ruta):
    if not (RAIZ / ruta).exists():
        pytest.skip(f"{ruta} no existe en este árbol (en el repo público el ejemplo vive en la raíz)")
    texto = (RAIZ / ruta).read_text(encoding="utf-8")
    presentes = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", texto, re.M))
    faltan = sorted(v for v in cx.variables_declaradas() if v not in presentes)
    assert not faltan, f"{ruta} no trae: {faltan}"


def test_los_requisitos_publicos_nombran_todas_las_claves_del_registro():
    ruta = RAIZ / "publico" / "requisitos.md"
    texto = (ruta if ruta.exists() else RAIZ / "requisitos.md").read_text(encoding="utf-8")   # en el repo público vive en la raíz
    faltan = sorted(c.variable for c in cx.CONEXIONES if c.variable not in texto)
    assert not faltan, f"publico/requisitos.md no menciona: {faltan}"


def test_los_proveedores_de_ia_del_registro_son_los_que_conoce_admin_env():
    from backend.api.services import admin_env
    assert {c.ia for c in cx.proveedores_ia()} == set(admin_env.proveedores_permitidos())


# --- reglas de validez ------------------------------------------------------------------------------------------------------

def _c(identificador):
    return cx.por_id(identificador)


@pytest.mark.parametrize("identificador, estado_http, cuerpo, esperado", [
    ("the-odds-api", 200, "[]", cx.ESTADO_OK),
    ("the-odds-api", 401, "{}", cx.ESTADO_FALLA),
    ("football-data", 400, "{}", cx.ESTADO_FALLA),          # football-data y Gemini devuelven 400, no 401
    ("gemini", 400, "{}", cx.ESTADO_FALLA),
    ("groq", 401, "{}", cx.ESTADO_FALLA),
    ("api-football", 200, '{"errors": {"token": "Error/Missing application key"}}', cx.ESTADO_FALLA),  # HTTP 200 + errors = inválida
    ("api-football", 200, '{"errors": []}', cx.ESTADO_OK),
    ("telegram", 200, '{"ok": true}', cx.ESTADO_OK),
    ("telegram", 401, '{"ok": false}', cx.ESTADO_FALLA),
    ("telegram", 200, '{"ok": false}', cx.ESTADO_FALLA),
    ("ollama_cloud", 401, "{}", cx.ESTADO_FALLA),
    ("groq", 429, "{}", cx.ESTADO_AVISO),                    # límite de uso: la clave puede estar bien
    ("bsd", 503, "{}", cx.ESTADO_AVISO),
    ("bsd", 302, "", cx.ESTADO_AVISO),
])
def test_evaluar_aplica_la_regla_de_validez(identificador, estado_http, cuerpo, esperado):
    assert cx.evaluar(_c(identificador), estado_http, {}, cuerpo).estado == esperado


def test_evaluar_lee_la_cuota_restante_de_la_cabecera():
    r = cx.evaluar(_c("the-odds-api"), 200, {"X-Requests-Remaining": "500"}, "[]")
    assert r.estado == cx.ESTADO_OK and "500 créditos" in r.detalle
    r = cx.evaluar(_c("api-football"), 200, {"x-ratelimit-requests-remaining": "92"}, '{"errors": []}')
    assert "92 restantes hoy" in r.detalle


def test_probar_devuelve_ok_con_una_respuesta_valida_y_manda_la_clave_solo_al_host_oficial():
    enviadas = []
    r = cx.probar(_c("the-odds-api"), "CLAVE-SECRETA-123", _abrir(_Respuesta(200, "[]", {"x-requests-remaining": "500"}), capturar=enviadas))
    assert r.estado == cx.ESTADO_OK
    assert urlparse(enviadas[0].full_url).hostname == "api.the-odds-api.com" and "apiKey=CLAVE-SECRETA-123" in enviadas[0].full_url


def test_probar_con_http_error_lo_interpreta_y_nunca_devuelve_la_clave():
    error = urllib.error.HTTPError("https://x", 401, "no", {}, io.BytesIO(b"{}"))
    r = cx.probar(_c("groq"), "CLAVE-SECRETA-123", _abrir(error=error))
    assert r.estado == cx.ESTADO_FALLA and "CLAVE-SECRETA-123" not in r.detalle


def test_probar_sin_red_es_un_aviso_no_una_clave_inválida():
    r = cx.probar(_c("groq"), "CLAVE-SECRETA-123", _abrir(error=urllib.error.URLError("sin red CLAVE-SECRETA-123")))
    assert r.estado == cx.ESTADO_AVISO and "CLAVE-SECRETA-123" not in r.detalle


def test_telegram_pone_el_token_en_la_ruta_y_ollama_manda_un_cuerpo_minimo():
    _, url, _, cuerpo = cx.armar_peticion(_c("telegram"), "123456:ABCDEF-token", "20261109")
    assert url == "https://api.telegram.org/bot123456:ABCDEF-token/getMe" and cuerpo is None
    metodo, _, cabeceras, cuerpo = cx.armar_peticion(_c("ollama_cloud"), "clave-ollama-123", "20261109")
    assert metodo == "POST" and cabeceras["Authorization"] == "Bearer clave-ollama-123" and b'"num_predict": 1' in cuerpo


# --- utilidades --------------------------------------------------------------------------------------------------------------

def test_valor_definido_ignora_marcadores_y_vacios():
    assert cx.valor_definido("gsk_abc123456") and not cx.valor_definido("") and not cx.valor_definido(None)
    assert not cx.valor_definido("your_bot_token") and not cx.valor_definido("replace_with_secret") and not cx.valor_definido("comma,separated,ids")


def test_formato_invalido_rechaza_lo_que_podria_abrir_una_linea_nueva_en_env():
    assert cx.formato_invalido("abc") is not None                      # muy corta
    assert cx.formato_invalido("clave con espacios 12345") is not None
    assert cx.formato_invalido("clave\nOTRA=1") is not None
    assert cx.formato_invalido('clave"comillas"12345') is not None
    assert cx.formato_invalido("gsk_ABCdef123456-_.") is None


def test_lo_minimo_para_pronosticar_son_cuotas_y_un_calendario():
    assert len(cx.faltantes_para_pronosticar(set())) == 2
    assert len(cx.faltantes_para_pronosticar({"the-odds-api"})) == 1 and "calendario" in cx.faltantes_para_pronosticar({"the-odds-api"})[0]
    assert cx.faltantes_para_pronosticar({"the-odds-api", "bsd"}) == []
    assert "cuotas" in cx.faltantes_para_pronosticar({"api-football"})[0]
