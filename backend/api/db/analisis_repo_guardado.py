"""
db/analisis_repo_guardado.py — Escritura de análisis individual, predicción, comparativo y multimodelo. Dividido de `analisis_repo.py` sin cambiar comportamiento;
`analisis_repo.py` reexporta estos nombres.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from backend.api.db.analisis_repo_comun import _now_str
from backend.api.models.predicciones import AnalisisComparativo, AnalisisIndividual, AnalisisModulo, Prediccion


def guardar_analisis_individual(db: Session, partido_id: str, pick_final: str, confianza: str,
                                 score_final: int, texto_completo: str, fuente: str = "python") -> dict:
    db.add(AnalisisIndividual(partido_id=partido_id, pick_final=pick_final, confianza=confianza,
                               score_final=score_final, texto_completo=texto_completo,
                               fuente=fuente, creado_en=_now_str()))
    db.commit()
    total = db.query(AnalisisIndividual).filter(AnalisisIndividual.partido_id == partido_id).count()
    return {"guardado": True, "total_analisis": total, "partido_id": partido_id}


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
