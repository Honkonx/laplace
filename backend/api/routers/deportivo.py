"""
routers/deportivo.py — Endpoints mínimos de la Parte 1 de la migración.

Reemplaza el núcleo de WF-A2 (acción `prediccion`/`check_job`) sin todavía tocar Telegram
(WF-A) ni Claude (eso es Parte 2). No requiere `x-kairos-key` todavía a nivel de dependency
global — se agrega junto con el resto de la auth cuando se porte el resto de acciones de
WF-A2 (registrar_usuario, activar_codigo, profile, etc.), para no duplicar el mecanismo a
medias en esta parte.

2026-09-09 — rate limit agregado a `POST /analisis` (hallazgo de auditoría: corre el motor
completo — poisson + forma + h2h/odds/tabla + consenso — y persiste en BD por request, sin
auth ni límite). `20/minute` por IP (`core/rate_limit.py::limitar`) — más laxo que
`/simulador` porque el costo por request acá es menor (sin Monte Carlo), pero sigue siendo
cómputo real que no debería quedar sin ningún techo.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.api.core.tiempo import utc_ahora
from backend.api.core.rate_limit import limitar
from backend.api.db.session import get_db
from backend.api.models.predicciones import AnalisisComparativo, AnalisisModulo
from backend.api.schemas.analisis import AnalisisInput
from backend.api.services.motor import analizar_partido

router = APIRouter(prefix="/api/v1", tags=["deportivo"])


def _now() -> str:
    """`creado_en` (analisis_comparativo/analisis_modulos) — normalizado a UTC 2026-09-09 (ver
    docstring de `db/jobs_repo.py::_now_str`). Distinto del campo `fecha` de más abajo (día
    calendario del análisis, negocio local — no se toca)."""
    return utc_ahora().strftime("%Y-%m-%d %H:%M:%S")


def _persistir_analisis(db: Session, resultado: dict) -> None:
    """Guarda el análisis en analisis_comparativo + analisis_modulos.

    Versión inicial de la Parte 1 — cubre los campos del motor Python (pick_python,
    probabilidades, score, picks por módulo). Los campos de Claude/consenso IA
    (pick_claude, peso_ia, bloque_claude_json) se completan en la Parte 2, cuando se
    integre Claude API — hoy quedan NULL, no se inventan valores.
    """
    consenso = resultado["consenso"]
    modulos = resultado["modulos"]
    poisson = modulos.get("poisson", {})

    fila = AnalisisComparativo(
        partido_id=resultado["partido_id"],
        fecha=datetime.now().strftime("%Y-%m-%d"),
        local=resultado["local"],
        visitante=resultado["visitante"],
        liga=resultado["liga"],
        pick_python=consenso.get("pick_final"),
        prob_local_py=poisson.get("prob_local"),
        prob_empate_py=poisson.get("prob_empate"),
        prob_visit_py=poisson.get("prob_visitante"),
        score_py=poisson.get("confianza_score"),
        pick_final=consenso.get("pick_final"),
        fuentes_disp=consenso.get("total_modulos"),
        consenso=consenso.get("nivel"),
        score_final=consenso.get("score_consenso"),
        confianza=consenso.get("confianza_final"),
        pick_h2h=modulos.get("h2h", {}).get("pick"),
        pick_odds=modulos.get("odds", {}).get("pick"),
        pick_tabla=modulos.get("tabla", {}).get("pick"),
        pick_form=modulos.get("forma", {}).get("pick"),
        score_poisson=poisson.get("confianza_score"),
        score_forma=modulos.get("forma", {}).get("confianza_score"),
        score_h2h=modulos.get("h2h", {}).get("confianza_score"),
        score_odds=modulos.get("odds", {}).get("confianza_score"),
        score_tabla=modulos.get("tabla", {}).get("confianza_score"),
        consenso_nivel=consenso.get("nivel"),
        coinciden_modulos=consenso.get("coinciden"),
        total_modulos=consenso.get("total_modulos"),
        over25_pred=poisson.get("over25_prob"),
        btts_pred=poisson.get("btts_prob"),
        creado_en=_now(),
    )
    db.add(fila)

    for nombre_modulo, res_modulo in modulos.items():
        db.add(
            AnalisisModulo(
                partido_id=resultado["partido_id"],
                modulo=nombre_modulo,
                pick=res_modulo.get("pick"),
                prob_local=res_modulo.get("prob_local"),
                prob_empate=res_modulo.get("prob_empate"),
                prob_visitante=res_modulo.get("prob_visitante"),
                score=res_modulo.get("confianza_score"),
                confianza=res_modulo.get("confianza"),
                datos_json=json.dumps(res_modulo, ensure_ascii=False),
                creado_en=_now(),
            )
        )

    db.commit()


@router.post("/analisis")
@limitar("20/minute")
def crear_analisis(request: Request, payload: AnalisisInput, guardar: bool = True, db: Session = Depends(get_db)) -> dict:
    """Corre el motor completo (poisson + forma + h2h/odds/tabla si aplican + consenso)
    sobre un partido ya enriquecido con datos. Reemplaza el núcleo de la acción
    `prediccion` de WF-A2 — sin Claude todavía (Parte 2) y sin la cascada de fuentes
    externas de gateway_unificado.py (también Parte 2) — el caller debe pasar los datos
    del partido ya resueltos (mismo contrato que hoy recibe pronostico.py)."""
    resultado = analizar_partido(payload.model_dump())
    if guardar and resultado["partido_id"]:
        _persistir_analisis(db, resultado)
    return resultado


@router.get("/analisis/{partido_id}")
def leer_analisis(partido_id: str, db: Session = Depends(get_db)) -> dict:
    """Último análisis guardado para un partido — reemplaza el core de `check_job` de
    WF-A2 para el caso 'ya hay resultado' (la cola de jobs asíncrona en sí, con Telegram/
    push, es Parte 2)."""
    fila = (
        db.query(AnalisisComparativo)
        .filter(AnalisisComparativo.partido_id == partido_id)
        .order_by(AnalisisComparativo.id.desc())
        .first()
    )
    if fila is None:
        return {"ok": False, "error": "sin análisis guardado para este partido_id"}

    return {
        "ok": True,
        "partido_id": fila.partido_id,
        "local": fila.local,
        "visitante": fila.visitante,
        "liga": fila.liga,
        "pick_final": fila.pick_final,
        "confianza": fila.confianza,
        "score_final": fila.score_final,
        "consenso": fila.consenso,
        "creado_en": fila.creado_en,
    }
