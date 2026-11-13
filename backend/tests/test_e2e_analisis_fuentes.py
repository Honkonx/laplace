"""De punta a punta: el análisis que pide una persona por Telegram SIEMPRE termina con un mensaje honesto, aunque las fuentes fallen (hallazgo H-005, 2026-11-11).

Base construida con las migraciones reales; el exterior se falsea con un transporte HTTP que responde 503, agota el tiempo, devuelve JSON vacío o lanza una excepción rara. Antes de la
corrección, con las fuentes caídas el usuario recibía un «análisis» de «Equipo Local vs Equipo Visitante / Competición»: un partido inventado.
"""
import asyncio
import itertools
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.api.db import jobs_repo
from backend.api.models.jobs import Job
from backend.api.models.partidos import PartidoDia
from backend.api.services import analisis_completo, telegram_client


def _cliente(modo: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if modo == "503":
            return httpx.Response(503, text="caído")
        if modo == "timeout":
            raise httpx.ConnectTimeout("sin respuesta")
        if modo == "red":
            raise httpx.ConnectError("sin red")
        if modo == "html":
            return httpx.Response(200, text="<html>mantenimiento</html>")
        return httpx.Response(200, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("modo,conocido", list(itertools.product(["503", "timeout", "red", "html", "vacio"], [False, True])))
def test_con_las_fuentes_caidas_el_usuario_recibe_un_mensaje_honesto_y_el_job_termina(base_migrada, monkeypatch, modo, conocido):
    fabrica = base_migrada("head")
    enviados = []

    async def enviar(client, chat_id, texto, **kwargs):
        enviados.append((chat_id, texto))
        return True

    monkeypatch.setattr(telegram_client, "enviar_mensaje", enviar)
    with fabrica() as db:
        if conocido:
            db.add(PartidoDia(match_id="999", fecha="2026-11-11", status="scheduled", liga_nombre="Premier League", local="Arsenal", visitante="Chelsea", hora_chile="14:00"))
            db.commit()
        job = jobs_repo.crear_job(db, match_id="999", fecha="20261111", chat_id="900", user_id="900", plan="free")

        async def correr():
            async with _cliente(modo) as c:
                await analisis_completo.procesar_job(db, c, job["job_id"])

        asyncio.run(correr())
        estado = db.query(Job).filter(Job.job_id == job["job_id"]).one().status
    assert estado in ("listo", "error"), "el job quedó sin estado terminal"
    assert len(enviados) == 1, "la persona debe recibir exactamente un mensaje"
    texto = enviados[0][1]
    assert "Equipo Local" not in texto and "Equipo Visitante" not in texto, "se inventó un partido"
    if conocido:
        assert "Arsenal" in texto and "Chelsea" in texto and estado == "listo"
    else:
        assert estado == "error" and "No pude identificar ese partido" in texto


def test_dos_clics_seguidos_no_dejan_dos_analisis_en_curso_para_el_mismo_partido(base_migrada, monkeypatch):
    from backend.api.bot import laplace_bot_callbacks as cb
    from backend.api.bot import laplace_bot_usuario
    from backend.api.models.usuarios import Usuario
    from unittest.mock import MagicMock

    fabrica = base_migrada("head")
    for modulo in (cb, laplace_bot_usuario):
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    monkeypatch.setattr(cb, "_procesar_job_en_fondo", AsyncMock())
    monkeypatch.setattr(cb.telegram_client, "responder_callback", AsyncMock())
    with fabrica() as db:
        db.add(Usuario(device_id="900", activo=1, plan="free", creado_en="2026-11-11 10:00:00"))
        db.commit()

    def clic():
        u = MagicMock()
        u.effective_user.id = 900
        u.effective_user.first_name = "Ana"
        u.effective_chat.id = 900
        u.callback_query.id = "c"
        u.callback_query.data = "PREDICT_20261111_m1"
        u.callback_query.message.reply_html = AsyncMock()
        ctx = MagicMock()
        ctx.application.bot_data = {"http_client": MagicMock()}
        asyncio.run(cb.callback_predict(u, ctx))
        return [c.args[0] for c in u.callback_query.message.reply_html.call_args_list]

    primero, segundo = clic(), clic()
    assert "Analizando partido" in primero[0]
    assert "en progreso" in segundo[0], f"el segundo clic debería avisar que ya hay un análisis en curso: {segundo[0][:80]}"
