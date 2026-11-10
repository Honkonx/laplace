"""test_push_repo_service.py — push_repo (SQLAlchemy) + push_service (Expo, httpx mockeado).

IMPORTANTE: `settings` carga `.env` real (que en este repo SÍ tiene API keys/tokens reales) —
todos los tests de red acá usan `httpx.MockTransport` explícito, nunca dependen de que las
keys estén vacías, para no golpear la API real de Expo por accidente durante `pytest`.
"""
from __future__ import annotations

import asyncio

import httpx

from backend.api.db import push_repo
from backend.api.models.jobs import Job
from backend.api.services import push_service


def test_guardar_y_leer_push_token(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "ExponentPushToken[aaa]", "android")
    tokens = push_repo.leer_push_tokens(db_session, "dev1")
    assert tokens == [{"device_id": "dev1", "expo_push_token": "ExponentPushToken[aaa]", "platform": "android"}]


def test_guardar_push_token_upsert(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "token-viejo")
    push_repo.guardar_push_token(db_session, "dev1", "token-nuevo")
    tokens = push_repo.leer_push_tokens(db_session, "dev1")
    assert len(tokens) == 1
    assert tokens[0]["expo_push_token"] == "token-nuevo"


def test_leer_push_tokens_todos_para_broadcast(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "t1")
    push_repo.guardar_push_token(db_session, "dev2", "t2")
    assert len(push_repo.leer_push_tokens(db_session)) == 2


def test_leer_match_subscriptores_solo_jobs_app_listos(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "t1")
    db_session.add(Job(job_id="j1", match_id="m1", fecha_partido="2026-06-01", chat_id="",
                        origen="app", status="listo", creado_en="2026-06-01 10:00:00",
                        device_id_app="dev1"))
    db_session.add(Job(job_id="j2", match_id="m1", fecha_partido="2026-06-01", chat_id="",
                        origen="app", status="pendiente", creado_en="2026-06-01 10:00:00",
                        device_id_app="dev2"))
    db_session.add(Job(job_id="j3", match_id="m1", fecha_partido="2026-06-01", chat_id="123",
                        origen="telegram", status="listo", creado_en="2026-06-01 10:00:00"))
    db_session.commit()

    subs = push_repo.leer_match_subscriptores(db_session, "m1")

    assert subs == [{"device_id": "dev1", "expo_push_token": "t1", "platform": "android"}]


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_enviar_push_batch_exito():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(push_service.EXPO_PUSH_URL)
        return httpx.Response(200, json={"data": [{"status": "ok"}]})

    async def _run():
        async with _mock_client(handler) as client:
            return await push_service.enviar_push(client, "ExponentPushToken[x]", "Título", "Cuerpo")

    assert asyncio.run(_run()) is True


def test_enviar_push_batch_error_ticket():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"status": "error", "message": "DeviceNotRegistered"}]})

    async def _run():
        async with _mock_client(handler) as client:
            return await push_service._enviar_batch(client, ["tok1"], "T", "B")

    resultado = asyncio.run(_run())
    assert resultado == {"enviados": 0, "fallos": 1, "detalle": [{"status": "error", "message": "DeviceNotRegistered"}]}


def test_enviar_push_sin_tokens_no_hace_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no debería llamar a Expo sin tokens")

    async def _run():
        async with _mock_client(handler) as client:
            return await push_service._enviar_batch(client, [], "T", "B")

    assert asyncio.run(_run()) == {"enviados": 0, "fallos": 0, "error": "sin_tokens"}


def test_enviar_push_a_device_lee_tokens_de_bd(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "tokA")

    llamados = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamados.append(request)
        return httpx.Response(200, json={"data": [{"status": "ok"}]})

    async def _run():
        async with _mock_client(handler) as client:
            return await push_service.enviar_push_a_device(client, db_session, "dev1", "T", "B")

    resultado = asyncio.run(_run())
    assert resultado["enviados"] == 1
    assert len(llamados) == 1


def test_enviar_push_broadcast_cuenta_enviados(db_session):
    push_repo.guardar_push_token(db_session, "dev1", "t1")
    push_repo.guardar_push_token(db_session, "dev2", "t2")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"status": "ok"}, {"status": "error"}]})

    async def _run():
        async with _mock_client(handler) as client:
            return await push_service.enviar_push_broadcast(client, db_session, "T", "B")

    assert asyncio.run(_run()) == 1
