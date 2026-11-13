"""Pruebas del registro de piezas del agente (breaker, EWMA, alertas), con reloj falso."""

import asyncio

import pytest

from backend.api.services import agent_piezas as ap
from backend.api.services.agent_piezas import (
    EstadoPieza,
    RegistroPiezas,
    ejecutar_con_breaker,
    registro_global,
    resetear_registro_global,
)


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def registro(reloj: Reloj) -> RegistroPiezas:
    r = RegistroPiezas(reloj=reloj)
    r.registrar("bot", "bot")
    return r


def _fallar(registro: RegistroPiezas, n: int, nombre: str = "bot") -> None:
    for _ in range(n):
        registro.fallo(nombre, "error")


def test_abre_tras_tres_fallos_en_la_ventana(registro, reloj):
    _fallar(registro, 2)
    assert registro.permitir("bot")
    registro.fallo("bot", "error")
    assert registro.estado("bot") == EstadoPieza.CAIDA
    assert not registro.permitir("bot")


def test_no_abre_si_los_fallos_estan_fuera_de_la_ventana(registro, reloj):
    registro.fallo("bot", "e")
    reloj.avanzar(30)
    registro.fallo("bot", "e")
    reloj.avanzar(35)  # el primero ya salió de la ventana de 60 s
    registro.fallo("bot", "e")
    assert registro.permitir("bot")
    assert registro.estado("bot") != EstadoPieza.CAIDA


def test_semiabierto_permite_una_sola_llamada_y_cierra_con_exito(registro, reloj):
    _fallar(registro, 3)
    reloj.avanzar(29)
    assert not registro.permitir("bot")
    reloj.avanzar(2)
    assert registro.permitir("bot")  # llamada de prueba
    assert not registro.permitir("bot")  # solo una
    assert registro.estado("bot") == EstadoPieza.DEGRADADA
    registro.exito("bot", 10)
    assert registro.permitir("bot")
    assert registro.resumen()[0]["breaker"] == "cerrado"


def test_reabre_con_espera_nueva_si_falla_la_prueba(registro, reloj):
    _fallar(registro, 3)
    reloj.avanzar(31)
    assert registro.permitir("bot")
    registro.fallo("bot", "sigue caido")
    assert registro.estado("bot") == EstadoPieza.CAIDA
    reloj.avanzar(29)
    assert not registro.permitir("bot")
    reloj.avanzar(2)
    assert registro.permitir("bot")


def test_exito_en_cerrado_reinicia_el_conteo(registro):
    _fallar(registro, 2)
    registro.exito("bot", 5)
    _fallar(registro, 2)
    assert registro.permitir("bot")


def test_ewma_con_alfa_03(registro):
    registro.exito("bot", 100)
    assert registro.resumen()[0]["latencia_ewma_ms"] == 100.0
    registro.exito("bot", 200)
    assert registro.resumen()[0]["latencia_ewma_ms"] == pytest.approx(130.0)


def test_tasa_de_error_en_cinco_minutos(registro, reloj):
    registro.fallo("bot", "e")
    registro.exito("bot", 1)
    registro.exito("bot", 1)
    registro.exito("bot", 1)
    assert registro.resumen()[0]["tasa_error_5min"] == pytest.approx(0.25)
    assert registro.estado("bot") == EstadoPieza.DEGRADADA
    reloj.avanzar(301)
    assert registro.resumen()[0]["tasa_error_5min"] == 0.0
    assert registro.estado("bot") == EstadoPieza.SANA


def test_estado_inicial_desconocida_y_luego_sana(registro):
    assert registro.estado("bot") == EstadoPieza.DESCONOCIDA
    registro.exito("bot", 3)
    assert registro.estado("bot") == EstadoPieza.SANA


def test_tipo_invalido_falla(registro):
    with pytest.raises(ValueError):
        registro.registrar("x", "otro")


def test_comprobar_todas_aisla_excepciones_y_plazos(reloj):
    registro = RegistroPiezas(reloj=reloj)

    async def sana():
        return {"ok": True}

    async def rota():
        raise RuntimeError("explotó")

    async def colgada():
        await asyncio.sleep(10)

    async def mala():
        return False

    registro.registrar("a", "bot", sana)
    registro.registrar("b", "modelo", rota)
    registro.registrar("c", "ia", colgada)
    registro.registrar("d", "laboratorio", mala)
    registro.registrar("e", "conocimiento")  # sin comprobar: no se toca
    asyncio.run(registro.comprobar_todas(plazo_segundos=0.05))
    assert registro.estado("a") == EstadoPieza.SANA
    assert registro.estado("b") == EstadoPieza.DEGRADADA  # un fallo no abre el breaker
    por_nombre = {p["nombre"]: p for p in registro.resumen()}
    assert "RuntimeError" in por_nombre["b"]["motivo"]
    assert "tiempo" in por_nombre["c"]["motivo"]
    assert por_nombre["d"]["tasa_error_5min"] == 1.0
    assert por_nombre["e"]["ultima_comprobacion"] is None


def test_alertas_una_vez_por_cambio(reloj):
    eventos = []
    registro = RegistroPiezas(reloj=reloj, alertar=eventos.append)
    registro.registrar("bot", "bot")
    registro.exito("bot", 5)
    registro.exito("bot", 5)  # sin cambio: no alerta
    assert [(e["antes"], e["despues"]) for e in eventos] == [("desconocida", "sana")]
    _fallar(registro, 3)
    assert eventos[-1]["despues"] == "caida"
    cantidad = len(eventos)
    registro.permitir("bot")  # sigue abierto: sin cambio
    assert len(eventos) == cantidad
    assert set(eventos[-1]) == {"pieza", "antes", "despues", "motivo", "en"}


def test_alertar_que_lanza_no_rompe(reloj):
    def mala(_evento):
        raise RuntimeError("alerta rota")

    registro = RegistroPiezas(reloj=reloj, alertar=mala)
    registro.registrar("bot", "bot")
    registro.exito("bot", 1)
    _fallar(registro, 3)
    assert registro.estado("bot") == EstadoPieza.CAIDA


def test_ejecutar_con_breaker_sin_permiso_no_llama(registro):
    _fallar(registro, 3)
    llamadas = []

    async def trabajo():
        llamadas.append(1)
        return 1

    r = asyncio.run(ejecutar_con_breaker(registro, "bot", trabajo, 1))
    assert r == {"ok": False, "motivo": "pieza en pausa", "pieza": "bot"}
    assert llamadas == []


def test_ejecutar_con_breaker_exito_fallo_y_plazo(registro):
    async def bien():
        return 42

    async def mal():
        raise ValueError("no")

    async def lenta():
        await asyncio.sleep(10)

    assert asyncio.run(ejecutar_con_breaker(registro, "bot", bien, 1)) == {"ok": True, "valor": 42}
    r = asyncio.run(ejecutar_con_breaker(registro, "bot", mal, 1))
    assert r["ok"] is False and "ValueError" in r["motivo"]
    r = asyncio.run(ejecutar_con_breaker(registro, "bot", lenta, 0.02))
    assert r == {"ok": False, "motivo": "plazo agotado", "pieza": "bot"}


def test_ejecutar_con_breaker_propaga_cancelacion(registro):
    async def cancelada():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ejecutar_con_breaker(registro, "bot", cancelada, 1))


def test_resumen_sin_datos_sensibles(registro):
    registro.fallo("bot", "fallo en C:" + chr(92) + "Users" + chr(92) + "yo" + chr(92) + "secreto.txt con clave " + "sk-" + "abcdefghijklmnopqrstuvwxyz0123456789")
    fila = registro.resumen()[0]
    assert set(fila) == {
        "nombre", "tipo", "estado", "ultima_comprobacion",
        "latencia_ewma_ms", "tasa_error_5min", "motivo", "breaker",
    }
    assert "Users" not in fila["motivo"]
    assert "sk-abcdef" not in fila["motivo"]


def test_aislamiento_entre_piezas(registro):
    registro.registrar("modelo", "modelo")
    _fallar(registro, 3, "bot")
    assert not registro.permitir("bot")
    assert registro.permitir("modelo")
    assert registro.estado("modelo") == EstadoPieza.DESCONOCIDA


def test_registro_global_es_singleton_y_se_resetea():
    resetear_registro_global()
    a = registro_global()
    assert registro_global() is a
    resetear_registro_global()
    assert registro_global() is not a
    resetear_registro_global()
    assert ap._registro_global is None
