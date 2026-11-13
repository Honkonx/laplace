"""Recorrido del agente y barrido de rutas HTTP como lo usa una persona (H-008 en adelante, el plan de pruebas «como usuario» (repositorio de trabajo)).

1. Cada frase de los conjuntos dorados (~190) pasa por el agente REAL sobre una base de migraciones reales, con el bot caído, y en matriz: IA apagada / IA que responde / IA que falla / IA que
   inventa cifras × persona normal / administrador. Contrato: nunca lanza, siempre responde, cabe en un mensaje de Telegram, no filtra trazas ni secretos, y el rechazo de lo interno vale también para el administrador.
2. Una sesión larga (190 mensajes seguidos) no hace crecer sin tope lo que se le manda a la IA.
3. Cada ruta de las dos aplicaciones (backend 9001 y agente 9100) se llama sin autenticación y con cuerpos adversariales: nunca debe responder 5xx ni mostrar una traza.
"""
from __future__ import annotations

import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from backend.api.services import agent_runtime, agent_sesiones
from backend.api.services.ai_client import AnalisisIAError
from backend.tests import test_agent_dorado as d1  # noqa: F401  (misma carpeta: se importa como módulo de pruebas)
from backend.tests import test_agent_dorado2 as d2  # noqa: F401

FRASES = [f for f, _ in d1.DORADO] + [f for f, _ in d2.DORADO2] + d1.BRECHAS_CONOCIDAS + d1.ADVERSARIAS + d2.BRECHAS
INTERNO = re.compile(r"Traceback|sqlalchemy|OperationalError|IntegrityError|NoneType|KeyError|\bsk-[A-Za-z0-9]{10,}|\d{8,10}:[A-Za-z0-9_-]{30,}")
LIMITE_TELEGRAM = 4096


def _ia(modo: str):
    async def ok(prompt, max_tokens=700, rol="agente"):
        return "Respuesta de prueba sin cifras.", "falso", "m"

    async def falla(prompt, max_tokens=700, rol="agente"):
        raise AnalisisIAError("todos los proveedores fallaron")

    async def inventa(prompt, max_tokens=700, rol="agente"):
        return "El local tiene 87% de ganar y un marcador seguro 4-0.", "falso", "m"

    return {"ok": ok, "falla": falla, "inventa": inventa}[modo]


@pytest.mark.parametrize("modo_ia", ["apagada", "ok", "falla", "inventa"])
@pytest.mark.parametrize("es_admin", [False, True])
def test_el_agente_responde_a_cada_frase_sin_romperse(base_migrada, monkeypatch, modo_ia, es_admin):
    from backend.api.core.config import settings

    fabrica = base_migrada("head")
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", modo_ia != "apagada")
    if modo_ia != "apagada":
        monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", _ia(modo_ia))
    fallos = []
    with fabrica() as db:
        for i, frase in enumerate(FRASES):
            try:
                r = asyncio.run(agent_runtime.procesar_mensaje(db, f"u{i % 7}", frase, None, "web", modo_ia != "apagada", es_admin))
            except Exception as exc:  # noqa: BLE001 — es justo lo que se busca
                fallos.append((frase, f"LANZÓ {type(exc).__name__}: {str(exc)[:80]}"))
                continue
            texto = r.get("respuesta") or ""
            if not texto.strip():
                fallos.append((frase, "respuesta vacía"))
            elif len(texto) > LIMITE_TELEGRAM:
                fallos.append((frase, f"respuesta de {len(texto)} caracteres"))
            elif INTERNO.search(texto):
                fallos.append((frase, "filtra un detalle interno"))
            if modo_ia == "inventa" and r.get("herramienta") == "llm.respond" and re.search(r"87%|4-0", texto):  # las cifras de una herramienta (perfil de un equipo) son datos reales, no inventos
                fallos.append((frase, "dejó pasar una cifra inventada por la IA"))
    assert not fallos, f"{len(fallos)} de {len(FRASES)} frases fallaron:\n" + "\n".join(f"  {f!r}: {m}" for f, m in fallos[:15])


def test_lo_interno_se_rechaza_tambien_al_administrador_y_con_ia_encendida(base_migrada, monkeypatch):
    from backend.api.core.config import settings

    fabrica = base_migrada("head")
    monkeypatch.setattr(settings, "AGENT_IA_ACTIVA", True)
    llamadas = []

    async def ia(prompt, max_tokens=700, rol="agente"):
        llamadas.append(prompt)
        return "no debería llamarse", "falso", "m"

    monkeypatch.setattr(agent_runtime, "generar_texto_ia_con_meta", ia)
    with fabrica() as db:
        for frase in d1.ADVERSARIAS:
            for admin in (False, True):
                r = asyncio.run(agent_runtime.procesar_mensaje(db, "adv", frase, None, "web", True, admin))
                assert r["herramienta"] in ("agent.security_refusal", None), (frase, admin, r["herramienta"])
    assert not llamadas, "una petición de datos internos llegó al proveedor de IA"


def test_una_sesion_larga_no_hace_crecer_sin_tope_lo_que_se_manda_a_la_ia(base_migrada):
    fabrica = base_migrada("head")
    with fabrica() as db:
        sid = None
        for frase in FRASES:
            r = asyncio.run(agent_runtime.procesar_mensaje(db, "larga", frase, sid, "web", False, False))
            sid = r["session_id"]
        bloque = agent_sesiones.historial_reciente(db, sid)
    assert len(FRASES) > 150 and len(bloque) < 4000 and bloque.count("Usuario:") <= agent_sesiones.TURNOS_EN_PROMPT


# ---------------------------------------------------------------- rutas HTTP
def _rutas(app):
    visto = set()
    for ruta in app.routes:
        metodos = getattr(ruta, "methods", None)
        path = getattr(ruta, "path", None)
        if not metodos or not path or path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            continue
        for m in sorted(metodos - {"HEAD", "OPTIONS"}):
            visto.add((m, path))
    return sorted(visto)


CUERPOS = [None, {}, [], "texto", {"a": "b"}, {"message": "x" * 20000}, {"n_sim": -1, "tabla": "no es lista"}, {"\u0000": "\u0000"}]


def _barrer(app, monkeypatch, fabrica):
    from backend.api.db.session import SessionLocal, get_db

    original = SessionLocal.kw.get("bind")
    SessionLocal.configure(bind=fabrica.kw["bind"])  # las rutas que abren su propia sesión (sin get_db) también ven la base migrada

    def db_migrada():
        db = fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_migrada
    problemas = []
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            for metodo, path in _rutas(app):
                url = re.sub(r"\{[^}]+\}", "x", path)
                for cuerpo in ([None] if metodo == "GET" else CUERPOS):
                    kwargs = {} if cuerpo is None else ({"content": cuerpo, "headers": {"content-type": "application/json"}} if isinstance(cuerpo, str) else {"json": cuerpo})
                    r = cliente.request(metodo, url, **kwargs)
                    if r.status_code >= 500 or INTERNO.search(r.text[:2000]):
                        problemas.append((metodo, path, r.status_code, str(cuerpo)[:30], r.text[:100]))
    finally:
        app.dependency_overrides.clear()
        SessionLocal.configure(bind=original)
    return problemas


def test_ninguna_ruta_del_backend_responde_5xx_ni_muestra_trazas(base_migrada, monkeypatch):
    from backend.api.main import app

    problemas = _barrer(app, monkeypatch, base_migrada("head"))
    assert not problemas, f"{len(problemas)} respuestas inseguras:\n" + "\n".join(f"  {p}" for p in problemas[:20])


def test_ninguna_ruta_del_agente_responde_5xx_ni_muestra_trazas(base_migrada, monkeypatch):
    from backend.api.agent_main import app

    problemas = _barrer(app, monkeypatch, base_migrada("head"))
    assert not problemas, f"{len(problemas)} respuestas inseguras:\n" + "\n".join(f"  {p}" for p in problemas[:20])
