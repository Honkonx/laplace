"""services/analisis_completo.py — Orquesta un análisis completo de partido: reemplaza la
cadena de nodos de WF-B desde `Extraer Info Partido` (wfb-006) hasta `Guardar en BD` (wfb-019),
para un job ya creado (por el bot de Telegram o el gateway de la app).

Cambio arquitectónico deliberado vs. WF-B: en n8n, WF-B es un cron cada 15s que hace polling de
`jobs` — WF-A/WF-A2 solo crean la fila y esperan. Acá el job se procesa en la misma tarea async
que lo creó (`asyncio.create_task`, ver `backend/api/bot/laplace_bot.py` y
`routers/app_gateway.py`), sin cola ni polling: elimina la latencia de hasta 15s Y la clase
entera de bug encontrada en WF-B (`Guardar en BD` con 7 llamadas `cmd: ''` vacías — el job de un
análisis con IA nunca se marcaba `listo`). El `try/finally` de `procesar_job` garantiza que el
job SIEMPRE queda en un estado terminal (`listo` o `error`), se haya podido llamar a Claude o no.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import consenso_ia_repo, jobs_repo, usuarios_repo
from backend.api.models.jobs import Job
from backend.api.services import ai_critico
from backend.api.services import consenso_ia, gateway, laboratorio_pronosticos, mensajes_analisis, motor, nivel_evidencia, telegram_client
from backend.api.services import ai_prompts, ai_salida
from backend.api.services import calidad_datos as calidad_datos_svc  # noqa: F401  (las pruebas lo leen como analisis_completo.calidad_datos_svc)
from backend.api.services.ai_client import AnalisisIAError, generar_texto_ia

# Reexportados: el código vive en `analisis_completo_enriquecimiento`, `_textos` y `_persistencia`.
# Se importan los módulos de datos (`bsd_predictions`, `h2h_fetch`, `odds_fetch`, `standings_fetch`)
# porque las pruebas los parchean como `analisis_completo.<modulo>.<función>`.
# `_enriquecer_partido` y `generar_texto_ia` se resuelven acá (en `analizar_y_persistir`), por eso
# parchearlos sobre este módulo surte efecto; `_standings_o_none` y `_bsd_*` los llama
# `_enriquecer_partido` desde su propio módulo: se parchean en `analisis_completo_enriquecimiento`.
from backend.api.services import bsd_predictions, h2h_fetch, odds_fetch, standings_fetch  # noqa: F401
from backend.api.services.analisis_completo_enriquecimiento import (  # noqa: F401
    _bsd_prediccion_segura,
    _bsd_xg_seguro,
    _enriquecer_partido,
    _standings_o_none,
    _texto_odds,
)
from backend.api.services.analisis_completo_persistencia import _modulos_data_para_guardar, _persistir  # noqa: F401
from backend.api.services.analisis_completo_textos import (  # noqa: F401
    _marcar_sin_pronostico,
    _motivos_sin_pronostico,
    _resumen_estadistico,
)

log = logging.getLogger("laplace.analisis")


def _puede_usar_ia(db: Session, job: Job) -> bool:
    """free NUNCA usa IA (solo estadístico Python) — pro/max/admin sí, sujeto a su límite
    diario. `usuarios_repo.verificar_limite` devuelve `puede=True` para free porque esa función
    describe si el usuario puede SEGUIR el flujo (siempre puede, con o sin IA) — la decisión de
    si esta ronda en particular usa IA es la de acá."""
    if job.origen == "app":
        return usuarios_repo.verificar_limite_ia_app(db, job.device_id_app or job.user_id or "")["puede"]
    if job.plan == "free":
        return False
    return usuarios_repo.verificar_limite(db, job.user_id or "", job.plan)["puede"]


async def _resolver_partido(db: Session, client: httpx.AsyncClient, job: Job) -> dict | None:
    """Devuelve {local, visitante, liga} — desde el propio job si es origen 'app' (WF-A2 ya
    los conocía por venir de `partidos_dia`), o buscando en la cascada de fixtures del día por
    `match_id` si es origen 'telegram' (igual que wfb-006)."""
    if job.origen == "app" and job.local_app and job.visitante_app:
        return {"local": job.local_app, "visitante": job.visitante_app, "liga": job.liga_app or "Competición"}

    from backend.api.models.partidos import PartidoDia

    fila = db.query(PartidoDia).filter(PartidoDia.match_id == str(job.match_id)).first()  # los partidos del día ya guardados: no depende de que las fuentes respondan ahora
    if fila is not None and fila.local and fila.visitante:
        return {"local": fila.local, "visitante": fila.visitante, "liga": fila.liga_nombre or "Competición"}
    stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, job.fecha_partido)
    for stage in stages:
        liga = stage.get("Snm") or stage.get("CompN") or "Competición"
        for evento in stage.get("Events", []):
            if str(evento.get("Eid")) == str(job.match_id):
                local = (evento.get("T1") or [{}])[0].get("Nm", "Local")
                visitante = (evento.get("T2") or [{}])[0].get("Nm", "Visitante")
                return {"local": local, "visitante": visitante, "liga": liga}
    return None  # antes se inventaba «Equipo Local vs Equipo Visitante» y se le mandaba al usuario un análisis de un partido que no existe (hallazgo H-005, 2026-11-11)


async def analizar_y_persistir(
    db: Session, client: httpx.AsyncClient, *, match_id: str, local: str, visitante: str,
    liga: str, fecha: str, con_ia: bool, usuario_id: str = "", datos_enriquecidos: dict | None = None,
) -> dict:
    """Núcleo reusable de "analizar un partido y guardarlo en `analisis_comparativo`" —
    extraído de `procesar_job` (2026-09-09) para que `laplace_agents.py` (auto-evaluación
    diaria, sin usuario real detrás) use EXACTAMENTE la misma lógica que un request real de
    usuario, en vez de reimplementarla — es la misma lección del fix de consistencia entre
    `top_picks.py`/`analisis_completo.py` de una ronda anterior: una sola fuente de verdad de
    "cómo se analiza y guarda un partido", no una tercera implementación divergente.

    No hace I/O de job (no actualiza `jobs`, no envía Telegram) — eso queda en el caller
    (`procesar_job` para requests reales; `laplace_agents` solo loguea/registra el run).
    `con_ia=False` es el modo real que usa la auto-evaluación (no gasta cuota de IA en partidos
    que nadie pidió); un request de usuario real decide `con_ia` con `_puede_usar_ia`."""
    partido = {"local": local, "visitante": visitante, "liga": liga}
    d = datos_enriquecidos or await _enriquecer_partido(db, client, partido, match_id, fecha)

    calidad_datos = d.get("calidad_datos", {"eligible": True, "sources": [], "source_count": 0, "reason": None})
    if calidad_datos.get("source_count", 0) == 0:
        resultado_motor = {
            "partido_id": match_id,
            "local": local,
            "visitante": visitante,
            "liga": liga,
            "modulos": {},
            "modulos_skip": {"quality_gate": str(calidad_datos.get("reason") or "Datos insuficientes")},
            "consenso": {
                "pick_final": "Sin pronóstico",
                "nivel": "DATOS_INSUFICIENTES",
                "coinciden": 0,
                "total_modulos": 0,
                "detalle": str(calidad_datos.get("reason") or "Datos insuficientes"),
                "score_consenso": 0,
                "confianza_final": "SIN DATOS",
            },
            "calidad_datos": calidad_datos,
        }
        texto_sin_pronostico = _marcar_sin_pronostico(d, resultado_motor, calidad_datos)
        return {
            "resultado_motor": resultado_motor, "combinado": None, "ia_llamada_real": False,
            "pick_final": "Sin pronóstico", "confianza_final": "SIN DATOS", "score_final": 0,
            "texto_final": texto_sin_pronostico,
            "resumen_estadistico": "No se publicó un pronóstico: faltan fuentes independientes.",
            "standings_info": d.get("standings_info", ""), "odds_info": d.get("odds_info", {}),
            "h2h_resumen": d.get("h2h_resumen", ""), "calidad_datos": calidad_datos,
        }

    resultado_motor = motor.analizar_partido(d)
    resultado_motor["calidad_datos"] = calidad_datos
    resultado_motor["nivel_evidencia"] = nivel_evidencia.calcular_nivel_evidencia(resultado_motor)
    if calidad_datos.get("tier") == "exploratoria" and resultado_motor.get("consenso", {}).get("nivel") != "SIN_MODULOS":
        consenso = resultado_motor.get("consenso", {})
        consenso["confianza_final"] = "BAJA"
        consenso["score_consenso"] = min(int(consenso.get("score_consenso", 0)), 39)
        consenso["detalle"] = f"{consenso.get('detalle', 'Análisis parcial')}. Solo {calidad_datos['source_count']} fuente real: resultado exploratorio."
    d["resumen_estadistico"] = _resumen_estadistico(resultado_motor)

    combinado = None
    ia_llamada_real = False  # True solo si se llamó de verdad al proveedor de IA en esta
    # corrida — distinto de "combinado no es None", que también es True cuando el resultado
    # vino servido del consenso ya validado por otro usuario (ahí NO se llamó al proveedor).
    # `procesar_job` usa este flag, no la presencia de `combinado`, para decidir si consume
    # cupo de IA del plan del usuario (ver nota real de 2026-08 sobre `registrar_uso_ia_app`
    # más abajo en `procesar_job`).
    if resultado_motor.get("consenso", {}).get("nivel") == "SIN_MODULOS":
        con_ia = False  # sin pronóstico propio la IA no tiene qué contrastar: no se gasta cupo ni se arriesga un pick inventado
    if con_ia:
        # Consenso "N usuarios validan el mismo pick de IA" (2026-09-09, ver
        # db/consenso_ia_repo.py) — distinto de CacheConsenso (esa cuenta análisis, no
        # usuarios distintos). Si 2+ usuarios distintos ya coincidieron en el pick de IA
        # de este partido dentro del TTL, se sirve ese resultado sin llamar al proveedor
        # de IA real — ahorra la llamada, nunca la duplica.
        validado = consenso_ia_repo.leer_validado(db, match_id)
        if validado:
            combinado = consenso_ia.combinar_con_claude(resultado_motor, validado["texto_ia"])
        else:
            try:
                prompt = ai_prompts.construir_prompt_analisis(d, estructurado=settings.AI_ANALISIS_JSON)
                texto_ia = await generar_texto_ia(prompt)
                try:
                    texto_ia, formato_ia = ai_salida.normalizar_salida_analisis(texto_ia, d)
                except ai_salida.SalidaInvalida as exc:
                    log.warning("analizar_y_persistir: salida de IA inválida (match_id=%s): %s — se degrada a solo estadístico", match_id, exc)
                    raise AnalisisIAError("salida de IA inválida") from exc
                texto_ia, cifras_descartadas = consenso_ia.depurar_cifras(texto_ia, prompt)
                if cifras_descartadas:
                    log.warning("IA con cifras sin respaldo en el prompt (match_id=%s): se descartaron %d línea(s)", match_id, len(cifras_descartadas))
                combinado = consenso_ia.combinar_con_claude(resultado_motor, texto_ia)
                combinado["prompt_version"] = ai_prompts.PROMPT_VERSION_JSON if settings.AI_ANALISIS_JSON else ai_prompts.PROMPT_VERSION_TEXTO
                combinado["formato_ia"] = formato_ia
                if settings.AI_CRITICO:  # informativo: se registra con el resultado, no cambia nada
                    combinado["critico"] = await ai_critico.criticar(d.get("resumen_estadistico", ""), texto_ia)
                ia_llamada_real = True
                consenso_ia_repo.registrar_resultado_ia(
                    db, match_id, combinado["pick_claude"], combinado["confianza_final"],
                    combinado["score_consolidado"], texto_ia, usuario_id,
                )
            except AnalisisIAError:
                log.warning("analizar_y_persistir: todos los proveedores de IA fallaron para match_id=%s — degradando a solo estadístico", match_id, exc_info=True)

    if combinado:
        texto_final = mensajes_analisis.formatear_mensaje_con_ia(
            resultado_motor, combinado, settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL
        )
        pick_final, confianza_final, score_final = combinado["pick_unificado"], combinado["confianza_final"], combinado["score_consolidado"]
    else:
        texto_final = mensajes_analisis.formatear_mensaje_free(
            resultado_motor, settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL
        )
        consenso = resultado_motor.get("consenso", {})
        pick_final = consenso.get("pick_final") or ""
        confianza_final = consenso.get("confianza_final") or "BAJA"
        score_final = consenso.get("score_consenso", 0)

    if str(pick_final or "").startswith("Sin pronóstico") or resultado_motor.get("consenso", {}).get("nivel") == "SIN_MODULOS":
        texto_final = _marcar_sin_pronostico(d, resultado_motor, calidad_datos)
        pick_final, confianza_final, score_final = "Sin pronóstico", "SIN DATOS", 0
    elif calidad_datos.get("tier") == "exploratoria":
        confianza_final, score_final = "BAJA", min(int(score_final or 0), 39)
        texto_final = f"Análisis exploratorio con confianza baja: {calidad_datos['reason']}\n\n{texto_final}"

    tiene_consenso_real = (
        resultado_motor.get("consenso", {}).get("total_modulos", 0) > 0
        and pick_final not in ("", "Sin pronóstico")
    )
    if calidad_datos.get("eligible", True) and tiene_consenso_real:
        _persistir(
            db, match_id, resultado_motor, combinado, pick_final, confianza_final, score_final,
            texto_final, d, fecha,
        )
    elif calidad_datos.get("source_count", 0) > 0:
        # La salida exploratoria no va a las tablas de rendimiento público ni a Top Picks,
        # pero sí queda en el laboratorio. Sin esta evidencia nunca podríamos comprobar si
        # una fuente aislada aporta señal o sólo repite el sesgo hacia el empate.
        laboratorio_pronosticos.registrar_comparadores_del_motor(
            db, partido_id=match_id, fecha_partido=fecha, local=resultado_motor.get("local", ""),
            visitante=resultado_motor.get("visitante", ""), liga=resultado_motor.get("liga", ""),
            hora_kickoff=d.get("hora_kickoff") or d.get("kick_off_utc"),
            datos={**d, "calidad_datos": calidad_datos, "estado": "exploratorio"},
            modulos=resultado_motor.get("modulos", {}), combinado=None,
        )
        db.commit()
    # versión sin IA del mismo análisis, para quien esperó este partido sin tener derecho a la IA (revisión de seguridad 2026-11-11)
    texto_estadistico = mensajes_analisis.formatear_mensaje_free(resultado_motor, settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL) if combinado else texto_final
    return {
        "texto_estadistico": texto_estadistico,
        "resultado_motor": resultado_motor, "combinado": combinado, "ia_llamada_real": ia_llamada_real,
        "pick_final": pick_final, "confianza_final": confianza_final,
        "score_final": score_final, "texto_final": texto_final,
        "resumen_estadistico": d.get("resumen_estadistico", ""), "standings_info": d.get("standings_info", ""), "odds_info": d.get("odds_info", {}), "h2h_resumen": d.get("h2h_resumen", ""),
        "calidad_datos": calidad_datos,
    }


def _texto_para(db: Session, espera: Job, texto_ia: str, texto_estadistico: str) -> str:
    """La versión CON IA solo la recibe quien tiene derecho a ella (plan de pago y dentro de su límite diario); el resto recibe la versión estadística del mismo análisis."""
    if texto_ia == texto_estadistico or espera.plan == "free":
        return texto_estadistico
    try:
        return texto_ia if usuarios_repo.verificar_limite(db, espera.user_id or "", espera.plan)["puede"] else texto_estadistico
    except Exception:  # noqa: BLE001 — ante la duda, la versión sin IA
        return texto_estadistico


async def _atender_esperas(db: Session, client: httpx.AsyncClient, job: Job, texto_ia: str, estado: str, texto_estadistico: str | None = None) -> None:
    """Entrega el análisis a quienes pidieron este partido mientras se analizaba (H-011), cada quien según su propio plan; un envío fallido deja esa espera en `error`, nunca en silencio."""
    texto_estadistico = texto_ia if texto_estadistico is None else texto_estadistico
    for espera in jobs_repo.esperas_de(db, job.match_id):
        if espera.job_id == job.job_id or not espera.chat_id:
            continue
        try:
            ok = await telegram_client.enviar_mensaje(client, espera.chat_id, _texto_para(db, espera, texto_ia, texto_estadistico))
        except Exception:  # noqa: BLE001
            ok = False
        jobs_repo.actualizar_job(db, espera.job_id, status=estado if ok else "error")


async def procesar_job(db: Session, client: httpx.AsyncClient, job_id: str) -> None:
    """Punto de entrada único: procesa un job de principio a fin y SIEMPRE lo deja en un
    estado terminal. Se llama desde el bot de Telegram o desde el router de la app
    inmediatamente después de crear el job (`asyncio.create_task`, sin cola de por medio)."""
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if job is None:
        log.error("procesar_job: job_id=%s no existe", job_id)
        return

    jobs_repo.actualizar_job(db, job_id, status="procesando")
    try:
        partido = await _resolver_partido(db, client, job)
        if partido is None:
            jobs_repo.actualizar_job(db, job_id, status="error")
            if job.origen == "telegram" and job.chat_id:
                await telegram_client.enviar_mensaje(client, job.chat_id, "⚠️ No pude identificar ese partido ahora: las fuentes de datos no respondieron. No te muestro un análisis inventado; intenta de nuevo en unos minutos con /juegos.")
            await _atender_esperas(db, client, job, "⚠️ No pude identificar ese partido ahora: las fuentes de datos no respondieron. Intenta de nuevo en unos minutos con /juegos.", "error")
            return
        con_ia = _puede_usar_ia(db, job)
        usuario_id = job.user_id or job.device_id_app or job.chat_id or ""

        resultado = await analizar_y_persistir(
            db, client, match_id=job.match_id, local=partido["local"], visitante=partido["visitante"],
            liga=partido["liga"], fecha=job.fecha_partido, con_ia=con_ia, usuario_id=usuario_id,
        )
        pick_final, confianza_final, score_final, texto_final = (
            resultado["pick_final"], resultado["confianza_final"], resultado["score_final"], resultado["texto_final"]
        )

        if resultado["ia_llamada_real"] and job.origen == "app":
            # Bug real encontrado en la auditoría de permisos 2026-09-08: `usuarios_repo.
            # registrar_uso_ia_app` existía pero nada la llamaba, así que `UsoDiarioIaApp`
            # nunca se incrementaba — el límite de 10 IA/día del plan `pro` en la app quedaba
            # sin aplicar de verdad (siempre `usados_hoy=0`), a diferencia de Telegram, donde
            # `usuarios_repo.verificar_limite` sí cuenta jobs reales del día. Incrementa SOLO
            # cuando `analizar_y_persistir` llamó de verdad al proveedor de IA
            # (`ia_llamada_real`, ver ese docstring) — nunca cuando el resultado vino servido
            # del consenso validado de otro usuario ni cuando el proveedor falló: servir desde
            # el consenso no debería consumir cupo del plan del usuario, es justamente el
            # ahorro que ese mecanismo existe para dar.
            usuarios_repo.registrar_uso_ia_app(db, job.device_id_app or job.user_id or "")

        if job.origen == "app":
            rm = resultado["resultado_motor"]
            desglose_app = {
                "partido_id": job.match_id,
                "local": partido["local"],
                "visitante": partido["visitante"],
                "liga": partido["liga"],
                "modulos": rm.get("modulos", {}),
                "modulos_skip": rm.get("modulos_skip", {}),
                "consenso": rm.get("consenso", {}),
                "standings_info": rm.get("standings_info", ""),
                "odds_info": rm.get("odds_info", ""),
                "h2h_resumen": rm.get("h2h_resumen", ""),
                "tasa_base_liga": rm.get("tasa_base_liga"),
                "calidad_datos": resultado.get("calidad_datos"),
            }
            jobs_repo.actualizar_job_app(db, job_id, status="listo", resultado={
                "pick": pick_final, "confianza": confianza_final, "score": score_final,
                "fuente": "claude" if resultado["combinado"] else "python", "texto_completo": texto_final,
                "desglose": desglose_app,
            })
        else:
            await telegram_client.enviar_mensaje(client, job.chat_id, texto_final)
            jobs_repo.actualizar_job(db, job_id, status="listo")
            await _atender_esperas(db, client, job, texto_final, "listo", resultado.get("texto_estadistico", texto_final))
    except Exception:
        log.error("procesar_job: fallo procesando job_id=%s", job_id, exc_info=True)
        jobs_repo.actualizar_job(db, job_id, status="error")
        if job.origen == "telegram" and job.chat_id:
            await telegram_client.enviar_mensaje(
                client, job.chat_id,
                "⚠️ Ocurrió un error al analizar este partido. Intenta de nuevo con /juegos.",
            )
        await _atender_esperas(db, client, job, "⚠️ Ocurrió un error al analizar este partido. Intenta de nuevo con /juegos.", "error")
