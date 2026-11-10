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

import asyncio
import logging

import httpx
from sqlalchemy.orm import Session

from backend.api.core.config import settings
from backend.api.db import analisis_repo, consenso_ia_repo, jobs_repo, partidos_repo, usuarios_repo
from backend.api.models.jobs import Job
from backend.api.services import bsd_predictions, consenso as consenso_svc, gateway, h2h_fetch, ligas, motor, odds_fetch, standings_fetch
from backend.api.services import ai_prompts, calidad_datos as calidad_datos_svc, consenso_ia, laboratorio_pronosticos, mensajes_analisis, modelo_historico, nivel_evidencia, telegram_client
from backend.api.services.ai_client import AnalisisIAError, generar_texto_ia

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


async def _resolver_partido(db: Session, client: httpx.AsyncClient, job: Job) -> dict:
    """Devuelve {local, visitante, liga} — desde el propio job si es origen 'app' (WF-A2 ya
    los conocía por venir de `partidos_dia`), o buscando en la cascada de fixtures del día por
    `match_id` si es origen 'telegram' (igual que wfb-006)."""
    if job.origen == "app" and job.local_app and job.visitante_app:
        return {"local": job.local_app, "visitante": job.visitante_app, "liga": job.liga_app or "Competición"}

    stages, _fuente = await gateway.obtener_fixtures_cascada(db, client, job.fecha_partido)
    for stage in stages:
        liga = stage.get("Snm") or stage.get("CompN") or "Competición"
        for evento in stage.get("Events", []):
            if str(evento.get("Eid")) == str(job.match_id):
                local = (evento.get("T1") or [{}])[0].get("Nm", "Local")
                visitante = (evento.get("T2") or [{}])[0].get("Nm", "Visitante")
                return {"local": local, "visitante": visitante, "liga": liga}
    return {"local": "Equipo Local", "visitante": "Equipo Visitante", "liga": "Competición"}


def _texto_odds(odds: dict, local: str, visitante: str) -> str:
    if odds.get("odds_disponibles"):
        return (
            f"{local} @{odds['odds_local']} | Empate @{odds['odds_empate']} | "
            f"{visitante} @{odds['odds_visit']} [{odds.get('odds_source', '')}]"
        )
    return odds.get("odds_info_externo") or "Sin odds disponibles — análisis estadístico puro."


async def _standings_o_none(
    client: httpx.AsyncClient, db: Session, tabla_codigo: str | None, fixture_info: dict
) -> list | None:
    if not tabla_codigo:
        return None
    return await standings_fetch.obtener_standings(
        client, db, tabla_codigo, str(fixture_info.get("apifootball_season") or "current")
    )


async def _bsd_prediccion_segura(client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    """Wrapper de bsd_predictions.obtener_prediccion_externa_bsd que nunca deja que un fallo de
    BSD bloquee el resto del consenso — bsd_ml es un módulo opcional más (mismo criterio que
    h2h/odds/tabla cuando sus propios validar_* dicen que no hay datos suficientes:
    `motor.py::validar_bsd` lo saltea si `bsd_prediccion` queda en None). La función interna ya
    atrapa sus propios errores de red y devuelve None — este wrapper es una segunda red de
    seguridad defensiva ante cualquier excepción no prevista."""
    try:
        return await bsd_predictions.obtener_prediccion_externa_bsd(client, local, visitante, fecha)
    except Exception:
        log.warning(
            "BSD prediction (bsd_ml) fallo local=%s visitante=%s — se omite del consenso",
            local, visitante, exc_info=True,
        )
        return None


async def _bsd_xg_seguro(db: Session, client: httpx.AsyncClient, local: str, visitante: str, fecha: str) -> dict | None:
    """Wrapper de `gateway.enriquecer_bsd()` — trae xG real de BSD para el partido (mismo
    criterio defensivo que `_bsd_prediccion_segura`: nunca deja que un fallo de BSD bloquee el
    resto del consenso). Solo se usan los campos `xg_local`/`xg_visit`/`xg_disponible` de acá —
    `odds_local`/`odds_empate`/`odds_visit` de `enriquecer_bsd()` se ignoran a propósito, la
    cascada real de odds ya vive en `odds_fetch.obtener_odds_partido` (incluye su propia fuente
    BSD, `_bsd_odds`) y no hace falta un segundo camino.

    Hallazgo real 2026-09-09/10 (`INVESTIGACION_MOTOR_PREDICCION_2026-09.md`
    §1.4): `pronostico.py::calcular_lambdas()` ya sabía mezclar xG real (peso 0.30) y
    `gateway.py::enriquecer_bsd()` ya sabía traerlo de BSD — pero ningún caller de producción
    llamaba a `enriquecer_bsd()`, así que `xg_usado` era `False` siempre. Conectado acá."""
    try:
        return await gateway.enriquecer_bsd(db, client, local, visitante, fecha)
    except Exception:
        log.warning(
            "BSD xG fallo local=%s visitante=%s — se omite del consenso (mismo peso 0 que si "
            "xg_local/xg_visit nunca llegan, ver pronostico.calcular_lambdas)",
            local, visitante, exc_info=True,
        )
        return None


async def _enriquecer_partido(db: Session, client: httpx.AsyncClient, partido: dict, match_id: str, fecha: str) -> dict:
    """Arma el dict `d` que espera `services/motor.py` — cascada de standings/odds/H2H/BSD,
    equivalente a wfb-007 (Mapear Liga) + wfb-008..wfb-015 de WF-B (+ wfb-031 para BSD).

    standings/odds/H2H/BSD(pick)/BSD(xG) son 5 fuentes HTTP independientes una vez resuelto
    `fixture_info` — antes corrían con `await` secuenciales (latencia real = suma de todas);
    acá corren en paralelo vía `asyncio.gather` (latencia real = la del más lento de todas)."""
    local, visitante, liga = partido["local"], partido["visitante"], partido["liga"]

    fixture_info = await gateway.buscar_fixture_id(db, client, match_id, local, visitante, fecha)
    # Resolución por league_id numérico (2026-09-09) — prioriza el id real de api-football
    # (inequívoco) sobre el nombre de texto libre (potencialmente ambiguo, ver
    # ligas.CLAVES_AMBIGUAS_EN_ORIGEN). Cae a mapear_liga()/get_liga_avg() de siempre cuando el
    # id no está en la tabla curada — mismo comportamiento que antes para esos casos.
    liga_avg, tabla_codigo, odds_key = ligas.resolver_liga_por_id(
        fixture_info.get("apifootball_league_id"), liga, 2.60
    )
    kick_off_utc = partidos_repo.leer_kick_off_utc(db, match_id, fecha)

    standings, odds, h2h, bsd_prediccion, bsd_xg = await asyncio.gather(
        _standings_o_none(client, db, tabla_codigo, fixture_info),
        odds_fetch.obtener_odds_partido(
            client, db, local, visitante, odds_key, fixture_info.get("apifootball_fixture_id"), fecha,
            kick_off_utc,
        ),
        h2h_fetch.obtener_h2h(
            client, db,
            fixture_info.get("apifootball_team_home"), fixture_info.get("apifootball_team_away"),
            local, visitante, liga, liga_avg,
            league_id=fixture_info.get("apifootball_league_id"), season=fixture_info.get("apifootball_season"),
        ),
        _bsd_prediccion_segura(client, local, visitante, fecha),
        _bsd_xg_seguro(db, client, local, visitante, fecha),
    )

    pos_local = pos_visit = 10
    forma_local_wins = forma_visit_wins = None
    tabla_datos_reales = False
    forma_datos_reales = False
    standings_info = "Datos de tabla no disponibles para esta liga."
    if standings:
        pos_local, forma_local_wins, txt_local = standings_fetch.extraer_posicion_y_forma(standings, local)
        pos_visit, forma_visit_wins, txt_visit = standings_fetch.extraer_posicion_y_forma(standings, visitante)
        standings_info = f"LOCAL {txt_local} | VISITANTE {txt_visit}"
        tabla_datos_reales = "Sin datos en tabla" not in txt_local and "Sin datos en tabla" not in txt_visit
        forma_datos_reales = tabla_datos_reales and "Forma: N/A" not in txt_local and "Forma: N/A" not in txt_visit
        if not tabla_datos_reales:
            # Solo uno de los dos equipos figura en la tabla: la posición por defecto del otro (10) no es un dato.
            # Con una real y otra inventada el módulo `tabla` comparaba contra un 10 falso (auditoría 2026-10-09, C4).
            pos_local = pos_visit = 10
            forma_local_wins = forma_visit_wins = None

    # Los defaults permiten que el pipeline siga operando cuando un proveedor cae, pero no son
    # evidencia suficiente para publicar probabilidades. Antes eran tratados como datos reales y
    # producían la misma predicción para partidos distintos. La puerta (única, compartida con
    # Top Picks: `calidad_datos.calcular_calidad_datos`) cuenta canales independientes — odds y
    # BSD son un solo canal de mercado — y reconoce `historico` cuando valida la liga y equipos.
    fuentes_crudas = {
        "tabla": tabla_datos_reales,
        "odds": bool(odds.get("odds_disponibles", False)),
        "h2h": bool(h2h.get("h2h_disponible", False) and h2h.get("h2h_total", 0) >= 3),
        "estadisticas_equipo": h2h.get("fuente_goles") == "stats_equipo_real",
        "xg": bool((bsd_xg or {}).get("xg_local") and (bsd_xg or {}).get("xg_visit")),
        "bsd": bool(bsd_prediccion),
    }

    datos = {
        "local": local, "visitante": visitante, "liga": liga,
        "partido": f"{local} vs {visitante}", "partido_id": match_id,
        # Id numérico de API-Football: desambigua la liga para el módulo `historico` sin depender del texto.
        "liga_id": fixture_info.get("apifootball_league_id"),
        "pos_local": pos_local, "pos_visit": pos_visit,
        "forma_local_wins": forma_local_wins, "forma_visit_wins": forma_visit_wins,
        "forma_datos_reales": forma_datos_reales,
        "standings_info": standings_info,
        "odds_local": odds.get("odds_local"), "odds_empate": odds.get("odds_empate"),
        "odds_visit": odds.get("odds_visit"), "odds_disponibles": odds.get("odds_disponibles", False),
        "odds_info": _texto_odds(odds, local, visitante),
        "goles_local_avg": h2h["goles_local_avg"], "goles_visit_avg": h2h["goles_visit_avg"],
        "goles_contra_local_avg": h2h["goles_contra_local_avg"], "goles_contra_visit_avg": h2h["goles_contra_visit_avg"],
        "fuente_goles": h2h.get("fuente_goles", "liga_generico"),
        "liga_goles_avg": liga_avg,
        "h2h_local_wins": h2h["h2h_local_wins"], "h2h_visit_wins": h2h["h2h_visit_wins"],
        "h2h_empates": h2h["h2h_empates"], "h2h_total": h2h["h2h_total"],
        "h2h_disponible": h2h["h2h_disponible"], "h2h_resumen": h2h["h2h_resumen"],
        "total_h2h": h2h["h2h_total"],
        "bsd_prediccion": bsd_prediccion,
        "xg_local": (bsd_xg or {}).get("xg_local"),
        "xg_visit": (bsd_xg or {}).get("xg_visit"),
    }
    datos["calidad_datos"] = calidad_datos_svc.calcular_calidad_datos(fuentes_crudas, datos)
    return datos


def _resumen_estadistico(resultado_motor: dict) -> str:
    """Referencia que se inyecta al prompt de IA. Usa la probabilidad ponderada del consenso (la
    que decide el pick público) con su procedencia; el Poisson, si existe, va solo como detalle."""
    consenso = resultado_motor.get("consenso", {})
    texto = consenso_svc.texto_probabilidad_consenso(consenso)
    if not texto:
        return "Motor estadístico no disponible."
    partes = [
        f"Probabilidad ponderada del consenso: {texto}",
        f"Pick: {consenso.get('pick_final', '?')} (score {consenso.get('score_consenso', 0)}/100, "
        f"nivel {consenso.get('nivel', '?')})",
    ]
    poisson = resultado_motor.get("modulos", {}).get("poisson", {})
    if poisson.get("ok"):
        pl = round((poisson.get("prob_local") or 0) * 100, 1)
        pe = round((poisson.get("prob_empate") or 0) * 100, 1)
        pv = round((poisson.get("prob_visitante") or 0) * 100, 1)
        partes.append(f"Detalle Poisson (un módulo más): {pl}% | Empate {pe}% | {pv}%")
    return " | ".join(partes)


def _modulos_data_para_guardar(modulos: dict) -> list[dict]:
    """Arma la lista `modulos_data` que espera `analisis_repo.guardar_analisis_multimodelo` — una
    entrada por módulo que sí corrió (`ok=True`; mismo criterio de filtro que ya usa
    `consenso.calcular_pesos_efectivos`), con el dict completo del módulo como `datos_json` para
    no perder los campos que no tienen columna dedicada en `AnalisisModulo` (`over25_prob`,
    `btts_prob`, `marcador_probable`, etc.). Mismo patrón que ya usaba
    `routers/deportivo.py::_persistir_analisis` (endpoint `/api/v1/analisis`, Parte 1) — acá se
    aplica al pipeline real de Telegram/app (2026-09-09, ver nota en `_persistir` más abajo)."""
    return [
        {
            "modulo": nombre, "pick": res.get("pick"), "prob_local": res.get("prob_local"),
            "prob_empate": res.get("prob_empate"), "prob_visitante": res.get("prob_visitante"),
            "score": res.get("confianza_score"), "confianza": res.get("confianza"), "datos_json": res,
        }
        for nombre, res in modulos.items() if res.get("ok")
    ]


def _persistir(db: Session, match_id: str, resultado_motor: dict, combinado: dict | None,
                pick_final: str, confianza_final: str, score_final: int, texto_final: str,
                datos_enriquecidos: dict, fecha_partido: str) -> None:
    analisis_repo.guardar_analisis_individual(
        db, match_id, pick_final, confianza_final, score_final, texto_final,
        fuente="claude" if combinado else "python",
    )
    modulos = resultado_motor.get("modulos", {})
    poisson = modulos.get("poisson", {})
    forma = modulos.get("forma", {})
    h2h = modulos.get("h2h", {})
    odds = modulos.get("odds", {})
    tabla = modulos.get("tabla", {})
    consenso_est = resultado_motor.get("consenso", {})
    nivel_consenso = combinado["nivel_ia"] if combinado else consenso_est.get("nivel", "")
    prob_consenso = consenso_est.get("prob_ponderada") or {}
    pick_py = poisson.get("pick") or consenso_est.get("pick_final") or ""
    prob_local_py = poisson.get("prob_local") if poisson.get("prob_local") is not None else prob_consenso.get("local")
    prob_empate_py = poisson.get("prob_empate") if poisson.get("prob_empate") is not None else prob_consenso.get("empate")
    prob_visit_py = poisson.get("prob_visitante") if poisson.get("prob_visitante") is not None else prob_consenso.get("visitante")

    # 2026-09-09 — normalización AnalisisComparativo/AnalisisModulo (auditoría real: 54 columnas
    # en AnalisisComparativo, varias redundantes con AnalisisModulo — tabla ya diseñada para
    # esto, pero en la BD real tenía 0 filas: existía `guardar_analisis_multimodelo` (escribe
    # ambas tablas en una transacción) pero ningún caller real la llamaba, solo tests). Decisión
    # (Opción A, no Opción B): NO migrar las 19 filas reales existentes de analisis_comparativo —
    # se confirmó empíricamente contra la BD real que sus columnas por-módulo (pick_h2h,
    # score_poisson, score_h2h, score_odds, score_tabla, consenso_nivel, bloque_claude_json, etc.)
    # ya estaban 100% NULL en esas 19 filas (nunca las pobló el pipeline real) — no había ningún
    # dato real que mover, así que "migrar" sería mover filas vacías con riesgo real y cero
    # beneficio. Paso 1 de 2: conectar `guardar_analisis_multimodelo` acá (ya existía completo,
    # solo faltaba este call site) para que TODO análisis nuevo escriba también su fila por
    # módulo en `analisis_modulos`, sin dejar de escribir las columnas anchas de
    # `analisis_comparativo` (ningún query existente que las lee — leer_stats_aciertos,
    # leer_top_picks_app, leer_historial_app, etc. — se rompe). Paso 2 (dejar de escribir las
    # columnas anchas, migrar esas lecturas a `AnalisisModulo`) queda para cuando el volumen real
    # lo justifique — no forzarlo ahora solo por completar la lista.
    analisis_repo.guardar_analisis_multimodelo(
        db,
        partido_id=match_id, local=resultado_motor.get("local", ""), visitante=resultado_motor.get("visitante", ""),
        liga=resultado_motor.get("liga", ""),
        pick_python=pick_py, prob_local_py=prob_local_py,
        prob_empate_py=prob_empate_py, prob_visit_py=prob_visit_py,
        score_poisson=poisson.get("confianza_score", 0),
        pick_claude=combinado["pick_claude"] if combinado else "",
        pick_final=pick_final,
        total_modulos=consenso_est.get("total_modulos", 0),
        consenso=nivel_consenso, consenso_nivel=nivel_consenso,
        coinciden_modulos=consenso_est.get("coinciden", 0),
        score_final=score_final, confianza=confianza_final,
        peso_python=0.6 if combinado else 1.0, peso_ia=0.4 if combinado else 0.0,
        pick_form=forma.get("pick"), score_form=forma.get("confianza_score"),
        pick_h2h=h2h.get("pick"), score_h2h=h2h.get("confianza_score"),
        pick_odds=odds.get("pick"), score_odds=odds.get("confianza_score"),
        pick_tabla=tabla.get("pick"), score_tabla=tabla.get("confianza_score"),
        over25_pred=poisson.get("over25_prob"), btts_pred=poisson.get("btts_prob"),
        modulos_data=_modulos_data_para_guardar(modulos),
        # Sin la hora de inicio no se puede saber si el análisis se creó DESPUÉS del partido (fuga);
        # los 95 análisis históricos de la BD real no la guardaron. Ver `calibracion.comparativo_valido`.
        hora_kickoff=datos_enriquecidos.get("hora_kickoff") or datos_enriquecidos.get("kick_off_utc") or "",
    )
    # Registro de sombra: usa exactamente la instantánea que vio el motor. No se lee desde
    # consenso.py y por tanto no puede cambiar el pick público ni aunque falle esta evaluación.
    laboratorio_pronosticos.registrar_comparadores_del_motor(
        db, partido_id=match_id, fecha_partido=fecha_partido, local=resultado_motor.get("local", ""),
        visitante=resultado_motor.get("visitante", ""), liga=resultado_motor.get("liga", ""),
        hora_kickoff=datos_enriquecidos.get("hora_kickoff") or datos_enriquecidos.get("kick_off_utc"),
        datos=datos_enriquecidos, modulos=modulos, combinado=combinado,
    )
    db.commit()


def _motivos_sin_pronostico(d: dict, calidad_datos: dict) -> list[str]:
    """Razones concretas (verificables en `d`) por las que no hay pronóstico propio, en lenguaje llano."""
    motivos = []
    if not d.get("odds_disponibles"):
        motivos.append("no hay cuotas reales de este partido")
    motivos += modelo_historico.motivos_sin_historico(d)
    if set(calidad_datos.get("sources", [])) & {"estadisticas_equipo", "h2h", "xg"}:
        motivos.append("hay estadísticas de los equipos, pero medidas contra el histórico rinden peor que la frecuencia de la liga")
    return motivos or ["ninguna fuente medida alcanzó para estimar el resultado"]


def _marcar_sin_pronostico(d: dict, resultado_motor: dict, calidad_datos: dict) -> str:
    """Adjunta la referencia histórica (liga o general) y devuelve el mensaje honesto para el usuario."""
    resultado_motor["referencia_tasa_base"] = modelo_historico.referencia_sin_pronostico(d)
    resultado_motor["motivos_sin_pronostico"] = _motivos_sin_pronostico(d, calidad_datos)
    resultado_motor["nivel_evidencia"] = nivel_evidencia.calcular_nivel_evidencia(resultado_motor)
    log.info(
        "sin_pronostico partido_id=%s liga=%r fuentes=%s motivos=%s", resultado_motor.get("partido_id"),
        resultado_motor.get("liga"), calidad_datos.get("sources"), resultado_motor["motivos_sin_pronostico"],
    )
    return mensajes_analisis.formatear_mensaje_sin_pronostico(
        resultado_motor, resultado_motor["motivos_sin_pronostico"], settings.TELEGRAM_CANAL_ID, settings.TELEGRAM_GRUPO_URL
    )


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
                prompt = ai_prompts.construir_prompt_analisis(d)
                texto_ia = await generar_texto_ia(prompt)
                texto_ia, cifras_descartadas = consenso_ia.depurar_cifras(texto_ia, prompt)
                if cifras_descartadas:
                    log.warning("IA con cifras sin respaldo en el prompt (match_id=%s): se descartaron %d línea(s)", match_id, len(cifras_descartadas))
                combinado = consenso_ia.combinar_con_claude(resultado_motor, texto_ia)
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
    return {
        "resultado_motor": resultado_motor, "combinado": combinado, "ia_llamada_real": ia_llamada_real,
        "pick_final": pick_final, "confianza_final": confianza_final,
        "score_final": score_final, "texto_final": texto_final,
        "resumen_estadistico": d.get("resumen_estadistico", ""), "standings_info": d.get("standings_info", ""), "odds_info": d.get("odds_info", {}), "h2h_resumen": d.get("h2h_resumen", ""),
        "calidad_datos": calidad_datos,
    }


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
    except Exception:
        log.error("procesar_job: fallo procesando job_id=%s", job_id, exc_info=True)
        jobs_repo.actualizar_job(db, job_id, status="error")
        if job.origen == "telegram" and job.chat_id:
            await telegram_client.enviar_mensaje(
                client, job.chat_id,
                "⚠️ Ocurrió un error al analizar este partido. Intenta de nuevo con /juegos.",
            )
