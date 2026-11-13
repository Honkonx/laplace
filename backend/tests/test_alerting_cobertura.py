"""Cobertura de services/alerting.py: envío, desactivación y fallos de red sin excepción."""
from __future__ import annotations

import logging

import httpx
import pytest

from backend.api.services import alerting

URL = "https://alertas.invalido.test/hook"


class _ClienteFalso:
    """Sustituye httpx.Client y registra lo que se envía."""

    llamadas: list[dict] = []
    timeouts: list[float] = []
    error_post: Exception | None = None
    status: int = 200

    def __init__(self, timeout: float = 0.0) -> None:
        type(self).timeouts.append(timeout)

    def __enter__(self) -> "_ClienteFalso":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, json: dict) -> httpx.Response:
        type(self).llamadas.append({"url": url, "json": json})
        if type(self).error_post is not None:
            raise type(self).error_post
        return httpx.Response(type(self).status, request=httpx.Request("POST", url))


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> type[_ClienteFalso]:
    _ClienteFalso.llamadas = []
    _ClienteFalso.timeouts = []
    _ClienteFalso.error_post = None
    _ClienteFalso.status = 200
    monkeypatch.setattr(alerting.httpx, "Client", _ClienteFalso)
    monkeypatch.setattr(alerting.settings, "ALERTS_ACTIVAS", True)
    monkeypatch.setattr(alerting.settings, "ALERT_WEBHOOK_URL", URL)
    return _ClienteFalso


def test_desactivadas_no_envian(cliente, monkeypatch):
    monkeypatch.setattr(alerting.settings, "ALERTS_ACTIVAS", False)
    assert alerting.emitir_alerta("x", {}) is False
    assert cliente.llamadas == []


def test_sin_url_no_envia(cliente, monkeypatch):
    monkeypatch.setattr(alerting.settings, "ALERT_WEBHOOK_URL", "")
    assert alerting.emitir_alerta("x", {}) is False
    assert cliente.llamadas == []


def test_envio_correcto_con_payload_estructurado(cliente):
    assert alerting.emitir_alerta("fallo_bd", {"tabla": "pronosticos"}) is True
    assert cliente.llamadas == [
        {
            "url": URL,
            "json": {"source": "laplace", "event": "fallo_bd", "detail": {"tabla": "pronosticos"}},
        }
    ]
    assert cliente.timeouts == [3.0]


def test_estado_http_de_error_devuelve_false_y_registra(cliente, caplog):
    cliente.status = 500
    with caplog.at_level(logging.WARNING, logger="laplace.alerting"):
        assert alerting.emitir_alerta("x", {}) is False
    assert "HTTPStatusError" in caplog.text


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("sin red"), httpx.ReadTimeout("lento"), RuntimeError("raro")],
)
def test_fallos_de_red_no_lanzan(cliente, caplog, error):
    cliente.error_post = error
    with caplog.at_level(logging.WARNING, logger="laplace.alerting"):
        assert alerting.emitir_alerta("x", {"k": 1}) is False
    assert type(error).__name__ in caplog.text


def test_log_no_filtra_url_ni_detalle(cliente, caplog):
    cliente.error_post = httpx.ConnectError(f"fallo contra {URL} token=secreto123")
    with caplog.at_level(logging.WARNING, logger="laplace.alerting"):
        alerting.emitir_alerta("x", {"clave": "valor-sensible"})
    assert "secreto123" not in caplog.text
    assert URL not in caplog.text
    assert "valor-sensible" not in caplog.text
