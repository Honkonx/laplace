"""
db/analisis_repo.py — Persistencia de análisis (individual, comparativo, multimodelo) y
caché de consenso.

Port de las funciones equivalentes de db_query.py — llamadas hoy desde WF-B
(`Guardar en BD`, wfb-019) con `body: { cmd: '' }` VACÍO en 7 de sus 7 pasos (confirmado por
grep, ver docs/humano/ de esta ronda): ningún análisis con IA persiste hoy, ningún job de plan
pro/max se marca `listo`. Acá cada función hace el `INSERT`/`UPDATE` real.
"""
from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.db.jobs_repo import rango_utc_dia_chile
from backend.api.models.predicciones import (
    CORTE_MOTOR_CON_PUERTA_CALIDAD,
    AnalisisComparativo,
    AnalisisIndividual,
    AnalisisModulo,
    CacheConsenso,
    CachePrediccion,
    Prediccion,
)

log = logging.getLogger("laplace.analisis_repo")


def _now_str() -> str:
    """`creado_en`/`completado_en` de este módulo — normalizado a UTC 2026-09-09 (ver
    docstring de `jobs_repo._now_str`). Filas anteriores a este commit pueden estar en hora
    local de Chile. `fecha` (día calendario del partido/análisis, distinto de `creado_en`)
    NO se toca acá — sigue siendo negocio en hora local, ver `jobs_repo.rango_utc_dia_chile`."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def guardar_analisis_individual(db: Session, partido_id: str, pick_final: str, confianza: str,
                                 score_final: int, texto_completo: str, fuente: str = "python") -> dict:
    db.add(AnalisisIndividual(partido_id=partido_id, pick_final=pick_final, confianza=confianza,
                               score_final=score_final, texto_completo=texto_completo,
                               fuente=fuente, creado_en=_now_str()))
    db.commit()
    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()
    return {"guardado": True, "total_analisis": total, "partido_id": partido_id}


def verificar_consenso_cache(db: Session, partido_id: str) -> dict:
    """1. Caché consenso activo → servir. 2. Job en vuelo → dedup. 3. Nada → generar."""
    from backend.api.models.jobs import Job

    ahora = _now_str()
    cc = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.partido_id == partido_id, CacheConsenso.expira_en > ahora,
                CacheConsenso.usos < CacheConsenso.max_usos)
        .first()
    )
    if cc is not None:
        cc.usos += 1
        db.commit()
        return {
            "cache_consenso_hit": True, "debe_generar": False, "job_en_vuelo": False,
            "pick_consenso": cc.pick_consenso, "texto_consenso": cc.texto_consenso,
            "total_analisis": cc.total_analisis, "tipo_consenso": cc.tipo_consenso,
            "usos_restantes": cc.max_usos - cc.usos,
        }

    job_en_vuelo = (
        db.query(Job)
        .filter(Job.match_id == partido_id, Job.status.in_(["pendiente", "procesando"]))
        .order_by(Job.creado_en.desc())
        .first()
    )
    if job_en_vuelo is not None:
        return {"cache_consenso_hit": False, "debe_generar": False, "job_en_vuelo": True,
                "pick_consenso": None, "texto_consenso": None, "total_analisis": 0, "usos_restantes": 0}

    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()
    return {"cache_consenso_hit": False, "debe_generar": True, "job_en_vuelo": False,
            "pick_consenso": None, "texto_consenso": None, "total_analisis": total, "usos_restantes": 0}


def activar_cache_consenso(db: Session, partido_id: str, max_usos: int = 5, horas_ttl: int = 3) -> dict:
    """python: 2+ análisis coincidentes activan caché. ia/mixto: 3+. Mismo criterio que el
    original — no relajar el umbral sin que el usuario lo pida."""
    filas = (
        db.query(AnalisisIndividual)
        .filter(AnalisisIndividual.partido_id == partido_id)
        .order_by(AnalisisIndividual.creado_en.desc())
        .limit(3)
        .all()
    )
    if len(filas) < 2:
        return {"activado": False, "razon": f"Solo {len(filas)}/2 análisis disponibles",
                "total_analisis": len(filas)}

    fuentes = {(f.fuente or "python") for f in filas}
    if fuentes <= {"python"}:
        tipo_consenso, min_requerido = "python", 2
    elif fuentes & {"claude", "ia"} and fuentes & {"python"}:
        tipo_consenso, min_requerido = "mixto", 3
    else:
        tipo_consenso, min_requerido = "ia", 3

    if len(filas) < min_requerido:
        return {"activado": False, "razon": f"Solo {len(filas)}/{min_requerido} análisis ({tipo_consenso})",
                "total_analisis": len(filas)}

    picks = [f.pick_final for f in filas[:min_requerido]]
    if len(set(picks)) != 1:
        return {"activado": False, "razon": f"Picks divergen: {picks}", "total_analisis": len(filas)}

    mejor = max(filas[:min_requerido], key=lambda f: f.score_final or 0)
    pick_consenso = picks[0]
    expira = (utc_ahora() + timedelta(hours=horas_ttl)).strftime("%Y-%m-%d %H:%M:%S")
    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()

    existente = db.query(CacheConsenso).filter(CacheConsenso.partido_id == partido_id).first()
    if existente is None:
        db.add(CacheConsenso(partido_id=partido_id, pick_consenso=pick_consenso,
                              texto_consenso=mejor.texto_completo, total_analisis=total, usos=0,
                              max_usos=max_usos, tipo_consenso=tipo_consenso, expira_en=expira,
                              creado_en=_now_str()))
    else:
        existente.pick_consenso = pick_consenso
        existente.texto_consenso = mejor.texto_completo
        existente.total_analisis = total
        existente.usos = 0
        existente.max_usos = max_usos
        existente.tipo_consenso = tipo_consenso
        existente.expira_en = expira
    db.commit()
    return {"activado": True, "pick_consenso": pick_consenso, "total_analisis": total,
            "tipo_consenso": tipo_consenso, "min_requerido": min_requerido, "expira_en": expira,
            "max_usos": max_usos}


def guardar_prediccion(db: Session, partido_id: str, fuente: str, pick: str, confianza: str,
                        score: int, razonamiento: str, texto_completo: str, job_id: str = "") -> dict:
    from backend.api.models.jobs import Job

    db.add(Prediccion(partido_id=partido_id, fuente=fuente, pick=pick, confianza=confianza,
                       confianza_score=score, razonamiento=razonamiento, texto_completo=texto_completo,
                       creado_en=_now_str()))
    if job_id:
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if job is not None:
            job.status = "listo"
            job.completado_en = _now_str()
    db.commit()
    return {"guardado": True}


def guardar_cache(db: Session, input_hash: str, respuesta_json: str, partido_id: str, horas_ttl: int = 6) -> dict:
    expira = (utc_ahora() + timedelta(hours=horas_ttl)).strftime("%Y-%m-%d %H:%M:%S")
    existente = db.query(CachePrediccion).filter(CachePrediccion.input_hash == input_hash).first()
    if existente is None:
        db.add(CachePrediccion(input_hash=input_hash, respuesta_json=respuesta_json,
                                partido_id=partido_id, expira_en=expira, hits=0, creado_en=_now_str()))
    else:
        existente.respuesta_json = respuesta_json
        existente.partido_id = partido_id
        existente.expira_en = expira
    db.commit()
    return {"hash": input_hash, "expira_en": expira}


def verificar_cache(db: Session, match_id: str, fecha: str = "") -> dict:
    import hashlib

    if not match_id:
        return {"cache_hit": False, "respuesta_json": None, "hash": None,
                "error_debug": "match_id vacío — no se puede cachear"}

    h = hashlib.md5(f"{match_id}{fecha}".encode()).hexdigest()
    row = (
        db.query(CachePrediccion)
        .filter(CachePrediccion.input_hash == h, CachePrediccion.expira_en > _now_str())
        .first()
    )
    if row is None:
        return {"cache_hit": False, "respuesta_json": None, "hash": h}
    row.hits += 1
    db.commit()
    return {"cache_hit": True, "respuesta_json": row.respuesta_json, "hash": h}


def existe_comparativo(db: Session, partido_id: str, fecha: str) -> bool:
    """True si ya hay una fila de `analisis_comparativo` para este partido+fecha (sin importar
    quién la generó — un usuario real, o `services/laplace_agents.py`). Usado por
    `laplace_agents.py` para no re-analizar un partido que un usuario real ya pidió (o que la
    propia auto-evaluación ya cubrió en una corrida anterior del día)."""
    return (
        db.query(AnalisisComparativo.id)
        .filter(AnalisisComparativo.partido_id == partido_id, AnalisisComparativo.fecha == fecha)
        .first()
        is not None
    )


def guardar_comparativo(db: Session, **campos) -> dict:
    """`campos` sigue el mismo contrato que el `args` original (ver
    db_query.py:guardar_comparativo) — partido_id, local, visitante, liga,
    pick_python, prob_local_py/prob_empate_py/prob_visit_py, score_py, pick_claude,
    pick_externo, pick_final, fuentes_disponibles, consenso, score_final, confianza,
    peso_python, peso_ia, hora_kickoff."""
    db.add(AnalisisComparativo(
        partido_id=str(campos.get("partido_id", "")),
        fecha=datetime.now().strftime("%Y-%m-%d"),
        local=str(campos.get("local", "")),
        visitante=str(campos.get("visitante", "")),
        liga=str(campos.get("liga", "")),
        pick_python=str(campos.get("pick_python", "")),
        prob_local_py=float(campos.get("prob_local_py") or 0),
        prob_empate_py=float(campos.get("prob_empate_py") or 0),
        prob_visit_py=float(campos.get("prob_visit_py") or 0),
        score_py=int(campos.get("score_py") or 0),
        pick_claude=str(campos.get("pick_claude", "")),
        pick_externo=str(campos.get("pick_externo", "")),
        pick_final=str(campos.get("pick_final", "")),
        fuentes_disp=int(campos.get("fuentes_disponibles") or 0),
        consenso=str(campos.get("consenso", "")),
        score_final=int(campos.get("score_final") or 0),
        confianza=str(campos.get("confianza", "")),
        peso_python=float(campos.get("peso_python") or 0.5),
        peso_ia=float(campos.get("peso_ia") or 0.5),
        hora_kickoff=str(campos.get("hora_kickoff", "")),
        creado_en=_now_str(),
    ))
    db.commit()
    return {"guardado": True}


def guardar_analisis_multimodelo(db: Session, **campos) -> dict:
    """Transacción única: 1 fila en `analisis_comparativo` + 1 fila en `analisis_modulos` por
    cada módulo en `modulos_data`. Ver docstring del original
    (db_query.py:guardar_analisis_multimodelo) para el contrato completo de
    campos — se preserva 1:1.

    2026-09-09 — único caller real hoy es `services/analisis_completo.py::_persistir` (ver
    docstring de `AnalisisModulo` en models/predicciones.py y el registro de decisiones del proyecto: auditoría
    real confirmó `analisis_modulos` en 0 filas en la BD real porque esta función existía pero
    nada del pipeline la llamaba — `_persistir` usaba `guardar_comparativo`, que no toca
    `analisis_modulos`). `consenso`/`peso_python`/`peso_ia` se agregan acá (antes solo los
    ponía `guardar_comparativo`) para que el cambio de caller no pierda esos 3 campos — ninguno
    de los 3 es por-módulo (no son parte de esta normalización), pero si no se preservan acá se
    vuelven NULL en toda fila nueva sin motivo real. `peso_python`/`peso_ia` no los lee ningún
    query hoy (confirmado por grep) — se preservan solo por paridad/honestidad del dato, no
    porque algo dependa de ellos. `consenso` SÍ se lee (`leer_stats_aciertos`, filtro
    `f.consenso == "COINCIDEN"` — valor real que pone `consenso_ia.combinar_con_claude` cuando
    el pick de Claude coincide con el consenso estadístico)."""
    partido_id = str(campos.get("partido_id", ""))
    if not partido_id:
        raise ValueError("partido_id es obligatorio")

    bloque_claude_json = campos.get("bloque_claude_json")
    if isinstance(bloque_claude_json, dict):
        bloque_claude_json = json.dumps(bloque_claude_json, ensure_ascii=False)
    pick_externo_detalle = campos.get("pick_externo_detalle")
    if isinstance(pick_externo_detalle, dict):
        pick_externo_detalle = json.dumps(pick_externo_detalle, ensure_ascii=False)

    over25_pred = campos.get("over25_pred")
    btts_pred = campos.get("btts_pred")

    pick_poisson = campos.get("pick_poisson") or campos.get("pick_python")
    score_poisson = campos.get("score_poisson") or campos.get("score_py")
    pick_forma = campos.get("pick_forma") or campos.get("pick_form")
    score_forma = campos.get("score_forma") or campos.get("score_form")

    fila = AnalisisComparativo(
        partido_id=partido_id,
        fecha=str(campos.get("fecha", datetime.now().strftime("%Y-%m-%d"))),
        local=str(campos.get("local", "")),
        visitante=str(campos.get("visitante", "")),
        liga=str(campos.get("liga", "")),
        pick_python=pick_poisson,
        pick_claude=campos.get("pick_claude"),
        pick_externo=campos.get("pick_externo"),
        pick_final=str(campos.get("pick_final", "")),
        prob_local_py=campos.get("prob_local_py", 0.0),
        prob_empate_py=campos.get("prob_empate_py", 0.0),
        prob_visit_py=campos.get("prob_visit_py", 0.0),
        score_py=score_poisson,
        score_final=int(campos.get("score_final", 0) or 0),
        confianza=str(campos.get("confianza", "")),
        consenso=str(campos.get("consenso") or campos.get("consenso_nivel") or ""),
        peso_python=float(campos.get("peso_python") or 0.5),
        peso_ia=float(campos.get("peso_ia") or 0.5),
        pick_form=pick_forma,
        score_form=score_forma,
        pick_h2h=campos.get("pick_h2h"),
        pick_odds=campos.get("pick_odds"),
        pick_tabla=campos.get("pick_tabla"),
        score_poisson=score_poisson,
        score_forma=score_forma,
        score_h2h=campos.get("score_h2h"),
        score_odds=campos.get("score_odds"),
        score_tabla=campos.get("score_tabla"),
        consenso_nivel=str(campos.get("consenso_nivel", "")),
        coinciden_modulos=int(campos.get("coinciden_modulos", 0) or 0),
        total_modulos=int(campos.get("total_modulos", 0) or 0),
        pick_externo_score=campos.get("pick_externo_score"),
        fuente_externo=str(campos.get("fuente_externo", "")) or None,
        pick_externo_detalle=pick_externo_detalle,
        bloque_claude_json=bloque_claude_json,
        hora_kickoff=str(campos.get("hora_kickoff", "")) or None,
        fuentes_disp=int(campos.get("total_modulos", 0) or 0),
        over25_pred=float(over25_pred) if over25_pred is not None else None,
        btts_pred=float(btts_pred) if btts_pred is not None else None,
        creado_en=_now_str(),
    )
    db.add(fila)
    db.flush()  # obtiene fila.id sin cerrar la transacción

    modulos_insertados = 0
    for m in campos.get("modulos_data", []) or []:
        if not isinstance(m, dict) or not m.get("modulo"):
            continue
        datos_json_m = m.get("datos_json")
        if isinstance(datos_json_m, dict):
            datos_json_m = json.dumps(datos_json_m, ensure_ascii=False)
        db.add(AnalisisModulo(
            partido_id=partido_id, job_id=campos.get("job_id") or None, modulo=str(m["modulo"]),
            pick=m.get("pick"), prob_local=m.get("prob_local"), prob_empate=m.get("prob_empate"),
            prob_visitante=m.get("prob_visitante"), score=m.get("score"), confianza=m.get("confianza"),
            datos_json=datos_json_m, creado_en=_now_str(),
        ))
        modulos_insertados += 1

    db.commit()
    return {"guardado": True, "partido_id": partido_id, "comparativo_id": fila.id,
            "modulos_insertados": modulos_insertados}


def leer_stats(db: Session) -> dict:
    from backend.api.models.jobs import Job

    total = db.query(Prediccion).count()
    alta = db.query(Prediccion).filter(Prediccion.confianza == "ALTA").count()
    media = db.query(Prediccion).filter(Prediccion.confianza == "MEDIA").count()
    baja = db.query(Prediccion).filter(Prediccion.confianza == "BAJA").count()
    completados = db.query(Job).filter(Job.status == "listo").count()
    errores = db.query(Job).filter(Job.status == "error").count()
    pendientes = db.query(Job).filter(Job.status == "pendiente").count()
    return {"predicciones": {"total": total, "alta": alta, "media": media, "baja": baja},
            "jobs": {"completados": completados, "errores": errores, "pendientes": pendientes}}


def leer_stats_aciertos(db: Session, dias: int = 30) -> dict:
    # `desde` se usa contra DOS campos de naturaleza distinta más abajo: `Prediccion.creado_en`
    # (timestamp, ahora UTC) y `AnalisisComparativo.fecha` (día calendario de negocio, local —
    # sin cambios). No hay un único valor que sea exacto para ambos; se deja en hora local
    # (correcto para `fecha`) — el único efecto práctico sobre `creado_en` es un corrimiento de
    # unas pocas horas en el borde de la ventana de reporte de N días (cosmético, no bloquea
    # ninguna decisión de negocio real). Ver docs/humano/ de esta ronda para el detalle.
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    def wr(a, t):
        return round((a or 0) / t * 100, 1) if t else None

    fuentes_out = []
    for fuente, total, aciertos, evaluados in (
        db.query(
            Prediccion.fuente,
            func.count(),
            func.sum(case((Prediccion.pick_correcto == 1, 1), else_=0)),
            func.sum(case((Prediccion.pick_correcto.isnot(None), 1), else_=0)),
        )
        .filter(Prediccion.creado_en >= desde)
        .group_by(Prediccion.fuente)
        .order_by(Prediccion.fuente)
        .all()
    ):
        fuentes_out.append({"fuente": fuente, "total": total or 0, "evaluados": evaluados or 0,
                             "aciertos": aciertos or 0, "winrate": wr(aciertos, evaluados)})

    filas = (
        db.query(AnalisisComparativo)
        .filter(
            AnalisisComparativo.fecha >= desde,
            AnalisisComparativo.creado_en >= CORTE_MOTOR_CON_PUERTA_CALIDAD,
            AnalisisComparativo.pick_correcto.isnot(None),
        )
        .all()
    )
    total = len(filas)
    aciertos = sum(1 for f in filas if f.pick_correcto == 1)
    alta = [f for f in filas if f.confianza == "ALTA"]
    media = [f for f in filas if f.confianza == "MEDIA"]
    consenso = [f for f in filas if f.consenso == "COINCIDEN"]

    return {
        "periodo_dias": dias, "desde": desde, "por_fuente": fuentes_out,
        "pick_final": {
            "total": total, "evaluados": total, "aciertos": aciertos, "winrate": wr(aciertos, total),
            "alta_winrate": wr(sum(1 for f in alta if f.pick_correcto == 1), len(alta)),
            "media_winrate": wr(sum(1 for f in media if f.pick_correcto == 1), len(media)),
            "consenso_winrate": wr(sum(1 for f in consenso if f.pick_correcto == 1), len(consenso)),
        },
    }


def leer_historial_app(db: Session, device_id: str, limit: int = 50) -> dict:
    from backend.api.models.jobs import Job

    jobs = (
        db.query(Job)
        .filter(Job.device_id_app == device_id, Job.origen == "app", Job.status == "listo")
        .order_by(Job.completado_en.desc())
        .limit(limit)
        .all()
    )
    historial = []
    for j in jobs:
        ac = db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == j.match_id).first()
        pick = (ac.pick_final if ac else None) or ""
        confianza = (ac.confianza if ac else None) or ""
        fuente = None
        if j.resultado_app:
            try:
                rd = json.loads(j.resultado_app)
                if isinstance(rd, dict):
                    fuente = rd.get("fuente") or rd.get("source")
                    pick = pick or rd.get("pick") or ""
                    confianza = confianza or rd.get("confianza") or ""
            except Exception:
                log.debug("analisis_repo: resultado_app no interpretable (resumen)", exc_info=True)

        if ac and ac.pick_correcto == 1:
            resultado_str = "acertado"
        elif ac and ac.pick_correcto == 0:
            resultado_str = "fallado"
        else:
            resultado_str = (ac.resultado_real if ac else None) or "pendiente"

        historial.append({
            "job_id": j.job_id, "match_id": j.match_id,
            "local": j.local_app or (ac.local if ac else "") or "",
            "visitante": j.visitante_app or (ac.visitante if ac else "") or "",
            "liga": j.liga_app or (ac.liga if ac else "") or "",
            "pick": pick, "confianza": confianza, "fuente": fuente,
            "resultado": resultado_str, "pick_correcto": ac.pick_correcto if ac else None,
            "fecha": (ac.fecha if ac else None) or j.fecha_partido, "completado_en": j.completado_en,
        })
    return {"historial": historial, "total": len(historial), "device_id": device_id}


def leer_top_picks_app(db: Session, device_id: str, fecha_yyyymmdd: str) -> dict:
    """Carousel de 3 fuentes: canal (WF-D), usuario (jobs propios), compartido (cache_consenso
    con 2+ análisis)."""
    from backend.api.models.jobs import Job
    from backend.api.models.partidos import RecomendacionDia

    fecha_iso = (
        f"{fecha_yyyymmdd[:4]}-{fecha_yyyymmdd[4:6]}-{fecha_yyyymmdd[6:]}"
        if len(fecha_yyyymmdd) == 8 else datetime.now().strftime("%Y-%m-%d")
    )

    recs = (
        db.query(RecomendacionDia)
        .filter(RecomendacionDia.fecha == fecha_yyyymmdd)
        .order_by(RecomendacionDia.hora_chile.asc())
        .limit(5)
        .all()
    )
    picks_canal = []
    for r in recs:
        ac = (
            db.query(AnalisisComparativo)
            .filter(AnalisisComparativo.partido_id == r.fixture_id, AnalisisComparativo.fecha == fecha_iso)
            .first()
        )
        picks_canal.append({
            "match_id": r.fixture_id, "local": r.local, "visitante": r.visitante, "liga": r.liga,
            "hora": r.hora_chile, "pick": (ac.pick_final if ac else None) or "Por definir",
            "confianza": (ac.confianza if ac else None) or "MEDIA",
            "score": ac.score_final if ac else None,
            "consenso": (f"{ac.fuentes_disp}/3" if ac and ac.fuentes_disp else "2/3"),
            "fuente": "canal", "partido": f"{r.local} vs {r.visitante}",
        })
    picks_canal.sort(key=lambda p: (p["score"] is None, -(p["score"] or 0)))

    picks_usuario = []
    if device_id:
        jobs = (
            db.query(Job)
            .filter(Job.device_id_app == device_id, Job.origen == "app", Job.status == "listo",
                    Job.fecha_partido == fecha_iso)
            .order_by(Job.completado_en.desc())
            .limit(3)
            .all()
        )
        for j in jobs:
            ac = db.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == j.match_id,
                                                        AnalisisComparativo.fecha == fecha_iso).first()
            local = j.local_app or (ac.local if ac else "") or ""
            visitante = j.visitante_app or (ac.visitante if ac else "") or ""
            pick_val = (ac.pick_final if ac else None) or ""
            confianza_val = (ac.confianza if ac else None) or ""
            score_val = ac.score_final if ac else None
            fuente_val = "python"
            if j.resultado_app:
                try:
                    rd = json.loads(j.resultado_app)
                    if isinstance(rd, dict):
                        fuente_val = rd.get("fuente") or rd.get("source") or "python"
                        pick_val = pick_val or rd.get("pick") or ""
                        confianza_val = confianza_val or rd.get("confianza") or "MEDIA"
                        score_val = score_val or rd.get("score")
                except Exception:
                    log.debug("analisis_repo: resultado_app no interpretable (pick)", exc_info=True)
            if not pick_val:
                continue
            picks_usuario.append({
                "match_id": j.match_id, "local": local, "visitante": visitante,
                "liga": j.liga_app or (ac.liga if ac else "") or "", "hora": None,
                "pick": pick_val, "confianza": confianza_val or "MEDIA", "score": score_val,
                "consenso": "1/3", "fuente": fuente_val, "partido": f"{local} vs {visitante}",
            })

    ahora = _now_str()
    ccs = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.expira_en > ahora, CacheConsenso.total_analisis >= 2)
        .order_by(CacheConsenso.total_analisis.desc(), CacheConsenso.creado_en.desc())
        .limit(3)
        .all()
    )
    picks_compartido = []
    for cc in ccs:
        ac = (
            db.query(AnalisisComparativo)
            .filter(AnalisisComparativo.partido_id == cc.partido_id, AnalisisComparativo.fecha == fecha_iso)
            .first()
        )
        if not ac or not ac.local:
            continue
        picks_compartido.append({
            "match_id": cc.partido_id, "local": ac.local or "", "visitante": ac.visitante or "",
            "liga": ac.liga or "", "hora": None, "pick": cc.pick_consenso or "Por definir",
            "confianza": ac.confianza or "MEDIA", "score": ac.score_final,
            "consenso": f"{cc.total_analisis}/3", "fuente": f"compartido_{cc.tipo_consenso}",
            "partido": f"{ac.local or ''} vs {ac.visitante or ''}",
        })

    return {"canal": picks_canal, "usuario": picks_usuario, "compartido": picks_compartido,
            "fecha": fecha_iso, "tiene_contenido": bool(picks_canal or picks_usuario or picks_compartido)}


def verificar_partido_completo(db: Session, match_id: str, device_id: str, fecha: str) -> dict:
    """Todo lo que la app necesita para mostrar opciones de análisis de un partido, en una
    sola llamada."""
    from backend.api.models.jobs import Job
    from backend.api.models.usuarios import Usuario

    ahora = _now_str()
    ccs = (
        db.query(CacheConsenso)
        .filter(CacheConsenso.partido_id == match_id, CacheConsenso.expira_en > ahora,
                CacheConsenso.usos < CacheConsenso.max_usos)
        .all()
    )
    consenso_python = {"existe": False, "texto": None, "total": 0, "pick": None}
    consenso_ia = {"existe": False, "texto": None, "total": 0, "pick": None}
    for cc in ccs:
        bloque = {"existe": True, "texto": cc.texto_consenso, "total": cc.total_analisis, "pick": cc.pick_consenso}
        if cc.tipo_consenso == "python":
            consenso_python = bloque
        elif cc.tipo_consenso in ("ia", "mixto"):
            consenso_ia = bloque

    # `Job.completado_en` se persiste en UTC (ver jobs_repo._now_str) — un LIKE 'YYYY-MM-DD%'
    # con `hoy` (día calendario de Chile pasado por el caller) ya no es válido acá; se usa el
    # rango UTC de ese día (ver jobs_repo.rango_utc_dia_chile). `hoy` vacío = sin filtro de
    # fecha (mismo comportamiento que el LIKE '%' original cuando `fecha` venía vacío).
    hoy = fecha[:10]
    job_query = db.query(Job).filter(
        Job.device_id_app == device_id, Job.match_id == match_id, Job.status == "listo"
    )
    if hoy:
        inicio_utc, fin_utc = rango_utc_dia_chile(hoy)
        job_query = job_query.filter(Job.completado_en >= inicio_utc, Job.completado_en < fin_utc)
    job = job_query.order_by(Job.completado_en.desc()).first()
    analisis_propio = {"existe": False, "content": None}
    if job is not None and job.resultado_app:
        try:
            contenido = json.loads(job.resultado_app)
        except Exception:
            contenido = job.resultado_app
        analisis_propio = {"existe": True, "content": contenido}

    usuario = db.query(Usuario).filter(Usuario.device_id == device_id).first()
    plan = usuario.plan if usuario else "free"
    es_admin_rol = usuario is not None and usuario.rol == "admin"
    if usuario and plan != "free" and not es_admin_rol and usuario.activo_hasta and usuario.activo_hasta < hoy:
        plan = "free"
    from backend.api.core.config import settings
    # rol separado de plan desde 2026-09-10 (ver models/usuarios.py §v7) — `es_admin_rol` cubre
    # promociones vía `/gestionarusuario rol:admin`, `settings.admin_ids` sigue cubriendo la
    # lista fija histórica de `.env` — ambas fuentes activan el mismo pseudo-valor "admin" acá
    # (uso interno de este cálculo, nunca se guarda en la columna `plan`).
    if device_id in settings.admin_ids or es_admin_rol:
        plan = "admin"

    limite_ia = {"pro": 6, "max": 9999, "admin": 9999, "free": 0}.get(plan, 0)
    if plan == "pro":
        from backend.api.models.usuarios import UsoDiarioApp
        uso = db.get(UsoDiarioApp, (device_id, hoy))
        cuota_ia_restante = max(0, limite_ia - (uso.predicciones_usadas if uso else 0))
    else:
        cuota_ia_restante = limite_ia

    return {"consenso_python": consenso_python, "consenso_ia": consenso_ia,
            "analisis_propio": analisis_propio, "plan": plan, "cuota_ia_restante": cuota_ia_restante}
