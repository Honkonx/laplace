"""routers/app_gateway.py — Gateway HTTP para LaplaceApp (reemplaza WF-A2 completo).

Mantiene EXACTAMENTE el mismo contrato externo que WF-A2 (`POST /deportivo`, header
`x-kairos-key`, body `{action, params, device_id, timestamp}`, respuesta
`{type, title, data}`) para que la app Android no necesite ningún cambio — la app-android
queda fuera del alcance de esta ronda (mejoras de app son trabajo futuro, ver `.memory/
decisiones.md`). Solo cambia lo que hay DETRÁS del endpoint: Python directo en vez de
`db_query <función> '<json>'` vía el bridge `127.0.0.1:8765/api/exec`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
import jwt
import pydantic
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.auth_deps import ALGORITMO_JWT
from backend.api.core.config import settings
from backend.api.db.session import get_db
from backend.api.db import analisis_repo, codigos_repo, jobs_repo, partidos_repo, tokens_repo, usuarios_repo
from backend.api.schemas.app_gateway import ACCIONES_CON_PARAMS, DeportivoRequest
from backend.api.services import analisis_completo, gateway
from backend.api.bot import ligas as ligas_bot

log = logging.getLogger("laplace.app_gateway")

router = APIRouter(prefix="/api/v1", tags=["app"])


async def _get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def _verificar_auth(x_kairos_key: str | None) -> None:
    if x_kairos_key != settings.KAIROS_AUTH_SECRET:
        raise HTTPException(status_code=401, detail={"type": "error", "title": "No autorizado", "data": {"message": "Token inválido"}})


def _resolver_device_id(request: Request, db: Session, body_device_id: str) -> str:
    """Si la app envía `device_id` vacío o el placeholder compartido `'laplace'`, intenta
    recuperar el `device_id` canónico desde el claim `sub` del JWT (`Authorization: Bearer`)."""
    limpio = (body_device_id or "").strip()
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            try:
                payload = jwt.decode(token, settings.WEB_JWT_SECRET, algorithms=[ALGORITMO_JWT])
                jti = payload.get("jti")
                if not (jti and tokens_repo.esta_revocado(db, jti)):
                    sub = str(payload.get("sub") or "").strip()
                    if sub and (not limpio or limpio.lower() == "laplace"):
                        return sub
            except Exception:
                log.debug("app_gateway: token no válido al resolver usuario", exc_info=True)
    return limpio


async def _accion_juegos(db: Session, client: httpx.AsyncClient, params: dict) -> dict:
    fecha_iso = params.get("date") or datetime.now().strftime("%Y-%m-%d")
    fecha_bd = fecha_iso.replace("-", "")
    liga_slug = params.get("league")
    resultado = partidos_repo.leer_partidos_dia_agrupado(db, fecha_bd, liga_slug)
    if resultado["total"] == 0:
        # Sin caché local todavía (antes del scheduler diario, o partido fuera de las ligas
        # que WF-D precarga) — fallback a la cascada de fixtures en vivo, igual que WF-A2
        # original cuando `from_db=false`.
        stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, fecha_bd)
        ligas = ligas_bot.ligas_con_partidos(stages, solo_prioritarias=not liga_slug)
        if liga_slug:
            buttons = []
            for stage in stages:
                if ligas_bot.slug_de_stage(stage) != liga_slug:
                    continue
                for ev in stage.get("Events", []):
                    if ev.get("Eps") != "NS":
                        continue
                    buttons.append({
                        "match_id": ev.get("Eid"),
                        "local": (ev.get("T1") or [{}])[0].get("Nm", "Local"),
                        "visitante": (ev.get("T2") or [{}])[0].get("Nm", "Visitante"),
                    })
            resultado = {"buttons": buttons, "ligas": {}, "total": len(buttons), "from_local_db": False}
        else:
            resultado = {"buttons": [{"id": l["slug"], "label": l["nombre"], "params": {"league": l["slug"]}} for l in ligas],
                         "ligas": {}, "total": len(ligas), "from_local_db": False}
    return {"type": "button_list", "title": "Partidos", "data": resultado}


async def _accion_prediccion(db: Session, client: httpx.AsyncClient, device_id: str, params: dict) -> dict:
    match_id = str(params.get("match_id", "")).strip()
    fecha = str(params.get("date", "")).replace("-", "")[:8]
    if not match_id or not device_id:
        return {"type": "error", "title": "Parámetro faltante", "data": {"message": "match_id y device_id requeridos"}}

    limite = usuarios_repo.verificar_limite_app(db, device_id)
    plan = limite["plan"]
    if not limite["puede"]:
        return {"type": "error", "title": "Límite diario alcanzado", "data": {"message": "Alcanzaste tu límite de predicciones por hoy.", "upgrade": True, "plan": plan}}

    activo = jobs_repo.verificar_job_activo(db, match_id)
    if activo["job_activo"]:
        return {"type": "prediction", "title": "Análisis en progreso", "data": {"job_id": activo["job_id"], "status": "procesando", "message": "Tu predicción ya está en proceso."}}

    if not params.get("force_new"):
        cache = analisis_repo.verificar_consenso_cache(db, match_id)
        if cache.get("cache_consenso_hit"):
            return {"type": "prediction", "title": "Análisis disponible", "data": {
                "job_id": "cache", "status": "listo", "from_cache": True,
                "content": cache.get("texto_consenso", ""), "plan": plan,
                "message": "Resultado desde caché de consenso.",
            }}

    job_id = jobs_repo.crear_job_app(
        db, match_id=match_id, fecha=fecha, device_id=device_id, plan=plan,
        local=str(params.get("local", "")), visitante=str(params.get("visitante", "")),
        liga=str(params.get("league", params.get("liga", ""))),
    )["job_id"]
    usuarios_repo.registrar_uso_app(db, device_id)
    asyncio.create_task(_procesar_job_app(client, job_id))
    return {"type": "prediction", "title": "Análisis iniciado", "data": {"job_id": job_id, "status": "pendiente", "plan": plan, "message": "Analizando partido... El resultado estará listo en unos segundos."}}


async def _procesar_job_app(client: httpx.AsyncClient, job_id: str) -> None:
    from backend.api.db.session import SessionLocal
    with SessionLocal() as db:
        await analisis_completo.procesar_job(db, client, job_id)


def _accion_check_job(db: Session, device_id: str, params: dict) -> dict:
    job_id = str(params.get("job_id", "")).strip()
    if not job_id or not device_id:
        return {"type": "error", "title": "Parámetro faltante", "data": {"message": "job_id y device_id requeridos"}}
    info = jobs_repo.leer_job_especifico(db, job_id, device_id)
    if not info or not info.get("encontrado"):
        return {"type": "error", "title": "Job no encontrado", "data": {"job_id": job_id, "message": "No se encontró este análisis. Puede que haya expirado."}}
    mensajes = {"pendiente": "Análisis en cola, procesando pronto...", "procesando": "Analizando partido... un momento más.", "listo": "Análisis completado.", "error": "Ocurrió un error al analizar el partido."}
    return {"type": "prediction", "title": "Estado del análisis", "data": {
        "job_id": job_id, "status": info.get("status"), "content": info.get("content"),
        "match_id": info.get("match_id"), "plan": info.get("plan", "free"),
        "message": mensajes.get(info.get("status"), "Estado desconocido."),
    }}


def _accion_top(db: Session, device_id: str) -> dict:
    fecha = datetime.now().strftime("%Y%m%d")
    return {"type": "top_picks_carousel", "title": "Top Picks del dia", "data": analisis_repo.leer_top_picks_app(db, device_id, fecha)}


def _accion_stats(db: Session) -> dict:
    stats = analisis_repo.leer_stats(db)
    aciertos = analisis_repo.leer_stats_aciertos(db, dias=30)
    return {"type": "text", "title": "Estadísticas del Bot", "data": {
        "predicciones": stats["predicciones"], "jobs": stats["jobs"],
        "winrate": aciertos["pick_final"], "por_fuente": aciertos["por_fuente"],
        "periodo_dias": aciertos["periodo_dias"],
    }}


def _accion_profile(db: Session, device_id: str) -> dict:
    perfil = usuarios_repo.obtener_usuario_app(db, device_id)
    racha = usuarios_repo.leer_racha(db, device_id)
    historial = analisis_repo.leer_historial_app(db, device_id, limit=500)
    return {"type": "text", "title": "Perfil", "data": {**perfil, "picks_total": historial["total"], "racha_user": racha}}


def _accion_activar_codigo(db: Session, device_id: str, params: dict) -> dict:
    codigo = str(params.get("codigo", "")).strip().upper()
    if not codigo:
        return {"type": "error", "title": "Código requerido", "data": {"activado": False, "success": False, "message": "Ingresa tu código de activación.", "error": "Ingresa tu código de activación."}}
    if not device_id or device_id.strip().lower() == "laplace":
        msg = "Debes iniciar sesión o tener un identificador de dispositivo válido antes de activar un código."
        return {"type": "error", "title": "Identidad requerida", "data": {"activado": False, "success": False, "mensaje": msg, "message": msg, "error": msg}}
    resultado = codigos_repo.activar_codigo(db, codigo, device_id)
    activado = bool(resultado.get("activado"))
    mensaje = resultado.get("mensaje") or ("Plan activado correctamente." if activado else "Código inválido o ya utilizado.")
    data_out = {**resultado, "success": activado, "message": mensaje}
    if not activado:
        data_out["error"] = mensaje
    if activado:
        return {"type": "text", "title": "¡Plan activado!", "data": data_out}
    return {"type": "error", "title": "Código inválido", "data": data_out}


def _accion_registrar_usuario(db: Session, device_id: str, params: dict) -> dict:
    nickname = str(params.get("nickname", "")).strip()
    if not (3 <= len(nickname) <= 20):
        return {"type": "error", "title": "Nombre inválido", "data": {"message": "El nombre debe tener entre 3 y 20 caracteres.", "error": "nickname_longitud"}}
    resultado = usuarios_repo.registrar_usuario_app(db, device_id, nickname)
    if not resultado.get("registrado"):
        return {"type": "error", "title": "Error al registrar", "data": resultado}
    return {"type": "text", "title": "Registro exitoso", "data": {**resultado, "message": f"¡Bienvenido, {nickname}!"}}


def _accion_verificar_partido(db: Session, device_id: str, params: dict) -> dict:
    match_id = str(params.get("match_id", "")).strip()
    fecha = str(params.get("date", params.get("fecha", "")))
    return {"type": "partido_info", "title": "Info del partido", "data": analisis_repo.verificar_partido_completo(db, match_id, device_id, fecha)}


def _accion_historial(db: Session, device_id: str, params: dict) -> dict:
    limit = int(params.get("limit", 50))
    return {"type": "button_list", "title": "Mi historial", "data": analisis_repo.leer_historial_app(db, device_id, limit)}


def _accion_guardar_partidos(db: Session, params: dict) -> dict:
    fecha = (params.get("fecha") or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    partidos = params.get("partidos", [])[:500]
    guardados = partidos_repo.guardar_partidos_dia(db, fecha, partidos)
    return {"type": "text", "title": "OK", "data": {"guardados": guardados}}


def _error_validacion(status_code: int, titulo: str, mensaje: str, exc: pydantic.ValidationError) -> HTTPException:
    return HTTPException(status_code=status_code, detail={
        "type": "error", "title": titulo,
        "data": {"message": mensaje, "errors": exc.errors(include_url=False)},
    })


@router.post("/deportivo")
async def deportivo(
    request: Request,
    db: Session = Depends(get_db),
    x_kairos_key: str | None = Header(default=None, alias="x-kairos-key"),
):
    _verificar_auth(x_kairos_key)
    body_crudo = await request.json()
    try:
        body = DeportivoRequest.model_validate(body_crudo)
    except pydantic.ValidationError as exc:
        raise _error_validacion(422, "Request inválido", "El body no cumple el contrato esperado.", exc) from exc

    action = body.action.lower().strip()
    schema_params = ACCIONES_CON_PARAMS.get(action)
    if schema_params is None:
        raise HTTPException(status_code=404, detail={
            "type": "error", "title": "Acción no soportada",
            "data": {"message": f"La acción '{action}' no existe."},
        })

    try:
        params = schema_params.model_validate(body.params).model_dump()
    except pydantic.ValidationError as exc:
        raise _error_validacion(422, "Parámetros inválidos", f"Los params de la acción '{action}' no son válidos.", exc) from exc

    device_id = _resolver_device_id(request, db, body.device_id)
    client = await _get_http_client(request)

    if action == "juegos":
        return await _accion_juegos(db, client, params)
    if action == "prediccion":
        return await _accion_prediccion(db, client, device_id, params)
    if action == "check_job":
        return _accion_check_job(db, device_id, params)
    if action == "top":
        return _accion_top(db, device_id)
    if action == "stats":
        return _accion_stats(db)
    if action == "profile":
        return _accion_profile(db, device_id)
    if action == "activar_codigo":
        return _accion_activar_codigo(db, device_id, params)
    if action == "registrar_usuario":
        return _accion_registrar_usuario(db, device_id, params)
    if action == "verificar_partido":
        return _accion_verificar_partido(db, device_id, params)
    if action == "historial":
        return _accion_historial(db, device_id, params)
    if action == "guardar_partidos":
        return _accion_guardar_partidos(db, params)
    if action == "ping":
        return {"type": "text", "title": "Pong", "data": {"ok": True, "ts": utc_ahora().isoformat(), "version": "app-gateway-py-1.0"}}

    # Inalcanzable: `action` ya se validó contra ACCIONES_CON_PARAMS arriba — todo action ahí
    # tiene una rama explícita en este if-chain. Se deja como red de seguridad si se agrega una
    # entrada nueva a ACCIONES_CON_PARAMS sin su rama correspondiente acá.
    raise HTTPException(status_code=500, detail={
        "type": "error", "title": "Acción sin implementar",
        "data": {"message": f"La acción '{action}' está declarada pero no tiene despacho."},
    })
