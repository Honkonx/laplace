"""test_resultados_scheduler.py — orquestador de WF-E (fecha objetivo, resumen, ciclo
completo con red mockeada — nunca golpea BSD/api-football/Telegram reales aunque `.env`
tenga keys reales, porque el `httpx.AsyncClient` de estos tests usa `MockTransport`)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from backend.api.models.predicciones import AnalisisComparativo
from backend.api.services import resultados_scheduler

TZ_CHILE = ZoneInfo("America/Santiago")


def test_calcular_fecha_objetivo_corrida_manana_usa_ayer():
    ahora = datetime(2026, 6, 2, 7, 0, tzinfo=TZ_CHILE)  # 07:00 Chile -> corrida "mañana"
    fecha, corrida = resultados_scheduler._calcular_fecha_objetivo(ahora)
    assert fecha == "2026-06-01"
    assert corrida == "manana"


def test_calcular_fecha_objetivo_corrida_noche_usa_hoy():
    ahora = datetime(2026, 6, 2, 20, 0, tzinfo=TZ_CHILE)  # 20:00 Chile -> corrida "noche"
    fecha, corrida = resultados_scheduler._calcular_fecha_objetivo(ahora)
    assert fecha == "2026-06-02"
    assert corrida == "noche"


def test_formatear_resumen_incluye_pendientes_y_cancelados():
    texto = resultados_scheduler._formatear_resumen(
        "2026-06-01", "noche",
        {"total": 5, "actualizados": 2, "pendientes": 2, "cancelados": 1, "sin_datos": 0},
    )
    assert "Actualizados: 2/5" in texto
    assert "Aún en juego: 2" in texto
    assert "Cancelados: 1" in texto
    assert "Sin datos" not in texto  # sin_datos=0 no se muestra


def test_ejecutar_ciclo_sin_pendientes_no_llama_red(db_session, monkeypatch):
    monkeypatch.setattr(resultados_scheduler.settings, "SPORTS_ADMIN_ID", "999")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no debería llamar a la red sin pendientes: {request.url}")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await resultados_scheduler.ejecutar_ciclo_resultados(db_session, client)

    resultado = asyncio.run(_run())
    assert resultado["sin_pendientes"] is True


def test_ejecutar_ciclo_con_pendiente_sin_datos_api_no_envia_push_ni_admin(db_session, monkeypatch):
    """Sin BSD/api-football key configuradas (se fuerzan vacías acá para no depender del
    .env real del repo) el fixture queda 'sin_datos_api' — no hay push que enviar, y sin
    SPORTS_ADMIN_ID no se notifica a nadie, todo sin tocar la red."""
    monkeypatch.setattr(resultados_scheduler.settings, "BSD_API_KEY", "")
    monkeypatch.setattr(resultados_scheduler.settings, "SPORTS_API_KEY", "")
    monkeypatch.setattr(resultados_scheduler.settings, "SPORTS_ADMIN_ID", "")

    ahora = datetime(2026, 6, 2, 20, 0, tzinfo=TZ_CHILE)
    db_session.add(AnalisisComparativo(
        partido_id="f1", fecha="2026-06-02", local="River", visitante="Boca", liga="L",
        creado_en="2026-06-02 10:00:00",
    ))
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no debería llamar a la red: {request.url}")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await resultados_scheduler.ejecutar_ciclo_resultados(db_session, client, ahora)

    resultado = asyncio.run(_run())
    assert resultado["sin_pendientes"] is False
    assert resultado["resumen"]["sin_datos"] == 1
    assert resultado["push_enviados"] == 0
    assert resultado["admin_notificado"] is False
