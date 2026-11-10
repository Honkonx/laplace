"""db/recomendaciones_repo.py — recomendaciones_dia (sobrantes del Top Picks del canal).

Port de `db_query.py::guardar_recomendaciones/leer_recomendaciones` (L1186,
L1369). `leer_top_picks_app` (L1224, usado por WF-A2 acción `top`) no se porta acá completo
porque mezcla 3 fuentes (canal/usuario/compartido) que dependen de repos de otro agente
(`analisis_repo`, `jobs_repo`) — se deja para que el hilo principal la arme combinando esos
repos con `leer_recomendaciones` de este archivo, evitando choque de escritura concurrente
sobre el mismo módulo.
"""
from __future__ import annotations


from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.models.partidos import RecomendacionDia
from backend.api.models.predicciones import AnalisisComparativo, Prediccion


def _now() -> str:
    """`creado_en` — normalizado a UTC 2026-09-09 (ver docstring de `jobs_repo._now_str`).
    Filas anteriores a este commit pueden estar en hora local de Chile."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def _fecha_ac(fecha_yyyymmdd: str) -> str:
    """recomendaciones_dia usa YYYYMMDD; analisis_comparativo usa YYYY-MM-DD."""
    if len(fecha_yyyymmdd) == 8 and fecha_yyyymmdd.isdigit():
        return f"{fecha_yyyymmdd[:4]}-{fecha_yyyymmdd[4:6]}-{fecha_yyyymmdd[6:]}"
    return fecha_yyyymmdd


def guardar_recomendaciones(db: Session, fecha: str, partidos: list[dict]) -> int:
    """Reemplaza las recomendaciones del mismo día (idempotente, igual que el original —
    `DELETE` + reinsertar, no acumula duplicados si WF-D corre dos veces el mismo día)."""
    if not partidos:
        return 0

    db.query(RecomendacionDia).filter(RecomendacionDia.fecha == fecha).delete()

    guardados = 0
    ts = _now()
    for p in partidos:
        fixture_id = str(p.get("fixture_id", ""))
        local = str(p.get("local", ""))
        visitante = str(p.get("visitante", ""))
        if not fixture_id or not local or not visitante:
            continue
        db.add(
            RecomendacionDia(
                fixture_id=fixture_id, local=local, visitante=visitante,
                liga=str(p.get("liga", "")), hora_chile=str(p.get("hora_chile", "")),
                fecha=fecha, creado_en=ts,
            )
        )
        guardados += 1
    db.commit()
    return guardados


def guardar_picks_publicados(db: Session, fecha: str, picks: list[dict]) -> int:
    """Persiste los picks que realmente llegaron al canal para resultado y calibración.

    No reemplaza un análisis existente del mismo fixture: puede contener información más rica
    solicitada antes por un usuario. La fila de `Prediccion` con fuente fija permite medir el
    rendimiento del canal separado de los análisis bajo demanda.
    """
    fecha_iso = _fecha_ac(fecha)
    ts = _now()
    guardados = 0
    for pick in picks:
        fixture_id = str(pick.get("fixture_id", ""))
        if not fixture_id:
            continue
        comparativo = (
            db.query(AnalisisComparativo)
            .filter(AnalisisComparativo.partido_id == fixture_id, AnalisisComparativo.fecha == fecha_iso)
            .first()
        )
        if comparativo is None:
            score = int(pick.get("score_consolidado") or 0)
            db.add(AnalisisComparativo(
                partido_id=fixture_id, fecha=fecha_iso, local=pick.get("local"), visitante=pick.get("visitante"),
                liga=pick.get("liga"), hora_kickoff=pick.get("hora_chile"),
                pick_python=pick.get("pick_python"), pick_form=pick.get("pick_form"),
                pick_claude=pick.get("pick_claude"), pick_externo=pick.get("pick_externo"),
                pick_final=pick.get("pick_final"), score_final=score,
                score_py=int(pick.get("score_py") or 0), score_form=int(pick.get("score_form") or 0),
                prob_local_py=pick.get("prob_local_py"), prob_empate_py=pick.get("prob_empate_py"),
                prob_visit_py=pick.get("prob_visit_py"), consenso=pick.get("nivel_ia"),
                confianza="ALTA" if score >= 65 else "MEDIA",
                fuentes_disp=2 if pick.get("nivel_ia") == "COINCIDEN" else 1,
                creado_en=ts,
            ))
        prediccion = (
            db.query(Prediccion)
            .filter(Prediccion.partido_id == fixture_id, Prediccion.fuente == "top_picks_canal")
            .first()
        )
        if prediccion is None:
            db.add(Prediccion(
                partido_id=fixture_id, fuente="top_picks_canal", pick=pick.get("pick_final"),
                confianza=pick.get("confianza_final") or ("ALTA" if int(pick.get("score_consolidado") or 0) >= 65 else "MEDIA"),
                confianza_score=int(pick.get("score_consolidado") or 0),
                razonamiento=pick.get("razon_ia") or None, texto_completo=None, creado_en=ts,
            ))
        guardados += 1
    db.commit()
    return guardados


def leer_recomendaciones(db: Session, fecha: str) -> list[dict]:
    """`fecha` en formato YYYYMMDD (igual que `recomendaciones_dia.fecha`). Enriquece con
    `analisis_comparativo` si ya existe un análisis para ese partido (LEFT JOIN, igual que el
    original) — WF-A (Telegram) solo usa local/visitante/liga/hora_chile, WF-A2 (app) además
    usa pick_final/confianza/score."""
    fecha_ac = _fecha_ac(fecha)
    filas = (
        db.query(RecomendacionDia, AnalisisComparativo)
        .outerjoin(
            AnalisisComparativo,
            (AnalisisComparativo.partido_id == RecomendacionDia.fixture_id)
            & (AnalisisComparativo.fecha == fecha_ac),
        )
        .filter(RecomendacionDia.fecha == fecha)
        .order_by(RecomendacionDia.hora_chile.asc())
        .all()
    )
    return [
        {
            "fixture_id": rec.fixture_id,
            "local": rec.local,
            "visitante": rec.visitante,
            "liga": rec.liga,
            "hora_chile": rec.hora_chile,
            "pick_final": ac.pick_final if ac else None,
            "confianza": ac.confianza if ac else None,
            "score": ac.score_final if ac else None,
            "consenso": f"{ac.fuentes_disp}/3" if ac and ac.fuentes_disp else None,
        }
        for rec, ac in filas
    ]
