"""routers/track_record.py — GET /api/v1/track-record, PÚBLICO (sin `requerir_admin`).

A diferencia de `GET /api/v1/admin/calibracion` (solo-admin, pensado para diagnóstico interno
del equipo), este endpoint es la pieza que le faltaba a Laplace según la investigación de
repos externos de esta sesión (ver `docs/arquitectura/INVESTIGACION_REPOS_BOTS_DEPORTIVOS_2026-
09.md`): un track record honesto, verificable, mostrado AFUERA — coherente con
`.claude/rules/product-philosophy.md` ("Laplace existe para ser distinto de la mayoría de bots
de predicciones deportivas... sistema honesto y técnico... métricas verificables"). Nunca
esconde una muestra chica ni un winrate malo — cada bloque trae su propio `confiable` +
`muestra_minima_requerida`, igual que `services/calibracion.py`.

Sin rate limit adicional ni auth — es de solo lectura, sin costo real de cómputo (unas pocas
queries agregadas), y es justamente el endpoint que se espera que se linkee/consulte desde
afuera (web, futuro canal público)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.db.session import get_db
from backend.api.services.backtesting import calcular_track_record

router = APIRouter(prefix="/api/v1", tags=["track-record"])


@router.get("/track-record")
def track_record(db: Session = Depends(get_db)) -> dict:
    """Métricas reales del motor (winrate del pick final, Brier score y RPS del módulo
    Poisson, volumen real de datos verificados) — mismo cálculo honesto que
    `GET /api/v1/admin/calibracion`, expuesto sin autenticación porque es justamente lo que se
    quiere mostrar públicamente (ver docstring del módulo)."""
    return calcular_track_record(db)
