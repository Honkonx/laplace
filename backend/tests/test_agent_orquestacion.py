"""Orquestación del agente (MA-10, MA-11, MA-13): registro de piezas con circuit breaker en las llamadas al bot, modelo calculado en el proceso del agente y /estado."""
import asyncio

import pytest

from backend.api.core.config import settings
from backend.api.services import agent_piezas, agent_tools


def _falla(*_a, **_k):
    raise RuntimeError("bot caído")


def test_tras_tres_fallos_seguidos_el_bot_entra_en_pausa_y_no_se_vuelve_a_llamar(monkeypatch):
    llamadas = []

    async def post_http(path, payload, params=None, authorization=None):
        llamadas.append(path)
        raise RuntimeError("bot caído")

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="bot caído"):
            asyncio.run(agent_tools._post("/api/v1/prediccion-web", {}))
    with pytest.raises(agent_tools.PiezaEnPausa):
        asyncio.run(agent_tools._post("/api/v1/prediccion-web", {}))
    assert len(llamadas) == 3  # la cuarta no llegó al bot
    assert agent_tools.registro_de_piezas().estado("bot") == agent_piezas.EstadoPieza.CAIDA
    assert agent_tools.registro_de_piezas().estado("modelo") != agent_piezas.EstadoPieza.CAIDA  # las piezas no se contagian


def test_un_error_4xx_o_de_permiso_no_cuenta_como_falla_de_la_pieza(monkeypatch):
    async def post_http(path, payload, params=None, authorization=None):
        raise PermissionError("destino no confiable")

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    for _ in range(5):
        with pytest.raises(PermissionError):
            asyncio.run(agent_tools._post("/api/v1/prediccion-web", {}, authorization="x"))
    assert agent_tools.registro_de_piezas().estado("bot") == agent_piezas.EstadoPieza.SANA


def test_el_modelo_se_calcula_en_el_proceso_del_agente_sin_pedirlo_al_bot(monkeypatch):
    from backend.api.ml.laplace import servicio

    salida = {"ok": True, "fuente": "modelo_laplace", "degradado": False, "p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}, "validados": [], "confianza": 0.2,
              "goles_esperados": {"local": 1.5, "visitante": 1.1, "total": 2.6}, "btts": {"si": 0.5, "no": 0.5}, "over_under": {}, "marcadores": [], "modelo": {"version": "t"}}
    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: ({"id": 1, "nombre": "x", "version": "t", "estado": "activo"}, {"familia": "x"}, ""))
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, entrada, canal="http": salida)

    async def post_http(*_a, **_k):
        raise AssertionError("no debe pedirlo al bot por HTTP")

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))
    assert r["ok"] and r["via"] == "proceso" and "goles_esperados" not in r  # lo no validado no sale (servicio.publico)
    assert agent_tools.registro_de_piezas().estado("modelo") == agent_piezas.EstadoPieza.SANA


def test_si_el_modelo_no_esta_en_el_proceso_se_intenta_por_http_y_si_se_apaga_el_ajuste_no_se_usa(monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, entrada, canal="http": {"ok": False, "motivo": "sin modelo"})  # sin artefacto cargado: `no_disponible` → se intenta por HTTP

    async def post_http(path, payload, params=None, authorization=None):
        return {"ok": True, "p1x2": {"local": 0.4, "empate": 0.3, "visitante": 0.3}}

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))
    assert r["ok"] and "via" not in r
    monkeypatch.setattr(settings, "AGENT_MODELO_EN_PROCESO", False)
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no se usa")))
    assert asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))["ok"]


def test_estado_de_piezas_comprueba_y_resume_sin_datos_sensibles(monkeypatch):
    async def capacidades():
        return {"available": False, "reason": "ConnectError", "url": "http://127.0.0.1:8000"}

    monkeypatch.setattr(agent_tools, "consultar_capacidades_deportivas", capacidades)
    piezas = asyncio.run(agent_tools.estado_de_piezas())
    por_nombre = {p["nombre"]: p for p in piezas}
    assert set(por_nombre) == {"bot", "modelo", "ia"} and por_nombre["bot"]["motivo"] == "ConnectError"
    assert "http://" not in str(piezas) and "url" not in por_nombre["bot"]


def test_pedir_equipos_que_el_modelo_no_conoce_no_abre_el_breaker_de_nadie(monkeypatch):
    """Revisión de seguridad: la falta de cobertura la decide la entrada del usuario; solo un modelo no cargado o roto cuenta como falla de la pieza."""
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: ({"id": 1, "nombre": "x", "version": "t", "estado": "activo"}, {"familia": "x"}, ""))
    monkeypatch.setattr(servicio, "pronosticar_partido", lambda db, entrada, canal="http": {"ok": False, "motivo": "el modelo no conoce a alguno de los equipos"})

    async def post_http(*_a, **_k):
        raise AssertionError("un partido sin cobertura no se reintenta por HTTP")

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    for _ in range(10):
        r = asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "Equipo Inventado", "visitante": "Otro Inventado"}))
        assert r["ok"] is False and r["degradado"] is True and "no cubre" in r["motivo"]
    assert agent_tools.registro_de_piezas().estado("modelo") == agent_piezas.EstadoPieza.SANA and agent_tools.registro_de_piezas().permitir("modelo")


def test_un_modelo_no_cargado_si_cuenta_como_falla_de_la_pieza(monkeypatch):
    from backend.api.ml.laplace import servicio

    monkeypatch.setattr(servicio, "_modelo_vigente", lambda db: (None, None, "no hay un modelo Laplace activo"))

    async def post_http(*_a, **_k):
        raise RuntimeError("bot caído")

    monkeypatch.setattr(agent_tools, "_post_http", post_http)
    for _ in range(3):
        asyncio.run(agent_tools.ejecutar_herramienta_deportiva("modelo.pronosticar", {"local": "A", "visitante": "B"}))
    assert agent_tools.registro_de_piezas().estado("modelo") == agent_piezas.EstadoPieza.CAIDA
