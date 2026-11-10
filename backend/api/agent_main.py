"""Entrada independiente del agente superior de Laplace.

Este proceso no inicia Telegram, scheduler ni workers deportivos. Puede funcionar aunque el
bot deportivo esté detenido y descubre sus capacidades mediante el endpoint de salud.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from backend.api.core.config import settings
from backend.api.routers import agent
from backend.api.db.session import SessionLocal
from backend.api.services.agent_knowledge import sincronizar_conocimiento_json
from backend.api.services.task_orchestrator import recuperar_tareas_interrumpidas, reencolar_tareas_pendientes

log = logging.getLogger("laplace.agent_main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    recuperar_tareas_interrumpidas()
    try:
        with SessionLocal() as db:
            sincronizar_conocimiento_json(db)
    except Exception:
        log.exception("No se pudo sincronizar el conocimiento al arrancar; el agente continúa")
    if settings.AGENT_LOCAL_EXECUTOR:
        reencolar_tareas_pendientes()
    bot_app = None
    if settings.AGENT_TELEGRAM_BOT_TOKEN:
        from backend.api.bot.laplace_agent_bot import construir_app
        try:
            bot_app = construir_app()
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling()
        except Exception:
            log.exception("El bot Telegram del agente no pudo arrancar; la API del agente continúa disponible")
            bot_app = None
    yield
    if bot_app is not None:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()

app = FastAPI(title="Laplace Agent", description="Agente superior universal de Laplace", version="0.1.0", lifespan=lifespan)
if settings.cors_origins_list:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(agent.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "component": "agent", "version": app.version}


@app.get("/capabilities")
def capabilities() -> dict:
    return {"component": "agent", "independent": True, "capabilities": ["chat", "memory", "knowledge", "runs", "tasks", "subagents", "sports-tools", "admin-routing"], "optional_extensions": ["sports-bot"]}


@app.get("/dependencies/sports")
async def sports_dependency() -> dict:
    url = settings.SPORTS_BACKEND_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url}/capabilities")
            response.raise_for_status()
            return {"available": True, "url": url, "capabilities": response.json()}
    except Exception as exc:
        return {"available": False, "url": url, "reason": type(exc).__name__}
