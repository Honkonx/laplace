"""Enfriamiento de alertas: el mismo fallo repetido no inunda el canal, lo suprimido se informa y un envío fallido no se enfría."""
from __future__ import annotations

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.services import alerting


@pytest.fixture()
def canal(monkeypatch):
    enviados = []
    monkeypatch.setattr(settings, "ALERTS_ACTIVAS", True)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "https://alertas.example.test/h")
    monkeypatch.setattr(settings, "ALERT_COOLDOWN_SEGUNDOS", 600)

    class Cliente:
        def __init__(self, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json):
            if enviados and enviados[-1] == "fallar":
                enviados.pop()
                raise httpx.ConnectError("caído")
            enviados.append(json)
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerting.httpx, "Client", Cliente)
    return enviados


def test_el_mismo_evento_dentro_de_la_ventana_se_suprime_y_se_cuenta(canal):
    assert alerting.emitir_alerta("agent.task_failed", {"error_type": "Timeout", "task_id": "1"}) is True
    assert alerting.emitir_alerta("agent.task_failed", {"error_type": "Timeout", "task_id": "2"}) is False
    assert alerting.emitir_alerta("agent.task_failed", {"error_type": "Timeout", "task_id": "3"}) is False
    assert len(canal) == 1


def test_el_siguiente_envio_informa_cuantas_se_suprimieron(canal, monkeypatch):
    alerting.emitir_alerta("e", {"kind": "k"})
    alerting.emitir_alerta("e", {"kind": "k"})
    alerting.emitir_alerta("e", {"kind": "k"})
    monkeypatch.setattr(settings, "ALERT_COOLDOWN_SEGUNDOS", 0)  # pasó la ventana
    assert alerting.emitir_alerta("e", {"kind": "k"}) is True
    assert canal[-1]["detail"]["suprimidas"] == 2


def test_eventos_distintos_o_tipos_de_error_distintos_no_se_enfrian_entre_si(canal):
    assert alerting.emitir_alerta("agent.task_failed", {"error_type": "Timeout"}) is True
    assert alerting.emitir_alerta("agent.task_failed", {"error_type": "ValueError"}) is True
    assert alerting.emitir_alerta("odds_creditos_bajos", {"restante": 3}) is True
    assert len(canal) == 3


def test_sin_enfriamiento_configurado_se_envia_todo(canal, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_COOLDOWN_SEGUNDOS", 0)
    assert alerting.emitir_alerta("e", {}) is True and alerting.emitir_alerta("e", {}) is True


def test_un_envio_fallido_no_cuenta_como_enviado(canal):
    canal.append("fallar")
    assert alerting.emitir_alerta("e", {"kind": "k"}) is False
    assert alerting.emitir_alerta("e", {"kind": "k"}) is True  # el segundo intento no está en enfriamiento


def test_apagadas_no_envian_ni_ocupan_memoria(monkeypatch):
    monkeypatch.setattr(settings, "ALERTS_ACTIVAS", False)
    assert alerting.emitir_alerta("e", {}) is False and alerting._ULTIMO_ENVIO == {}


def test_el_diccionario_de_enfriamiento_tiene_tope(canal):
    for i in range(alerting._MAX_CLAVES + 50):
        alerting.emitir_alerta(f"evento-{i}", {})
    assert len(alerting._ULTIMO_ENVIO) <= alerting._MAX_CLAVES
