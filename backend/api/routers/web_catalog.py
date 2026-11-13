"""Contrato de catálogo para la web.

La SPA no debe interpretar feeds de proveedores. Esta capa entrega partidos estables, con
logos, filtros y una política visible de relevancia que comparte datos con app y bot.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.api.db.session import get_db
from backend.api.models.partidos import PartidoDia
from backend.api.models.predicciones import HistorialPrediccionWeb, PrediccionVarianteAgente
from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.services import ligas_ident
from backend.api.services.gateway import obtener_fixtures_cascada
from backend.api.services.top_picks import LIGAS_OK
from backend.api.db import recomendaciones_repo

log = logging.getLogger("laplace.web_catalog")

router = APIRouter(prefix="/api/v1/web", tags=["web-catalog"])

# Misma selección inicial que top_picks; el usuario puede abrir "todas" explícitamente.
PRIORITY_EXACT = frozenset({
    "la liga", "laliga", "serie a", "bundesliga", "ligue 1", "primeira liga",
    "uefa champions league", "uefa europa league", "copa libertadores", "mls", "liga mx",
    # Ligas hispanohablantes y de mayor interés (2026-10-07). Se comparan por el nombre BASE (sin la fase
    # tras los dos puntos: "Liga MX: Apertura" -> "liga mx"). Los nombres genéricos de varios países
    # ("Primera Division", "Premier League") siguen fuera: sin id canónico son ambiguos.
    "liga profesional", "liga profesional argentina", "primera a", "liga 1", "primera division de chile",
    "liga betplay", "brasileirao", "campeonato brasileiro serie a", "eredivisie", "super lig", "süper lig",
    "saudi professional league", "saudi pro league", "k league 1", "j1 league", "copa sudamericana",
    "conmebol sudamericana", "conmebol libertadores", "concacaf champions cup", "uefa conference league",
    "liga profesional de futbol", "primera division argentina",
})
PRIORITY_REJECTED = ("women", "femenil", "u17", "u19", "u20", "u21", "u23", "reserve", "reserves", "cup", "group",
                     "friendl", "youth", "juvenil", "amistoso")
FALLBACK_MAX = 30  # selección editorial acotada cuando el día no tiene ligas relevantes


@router.get("/top-picks")
def top_picks_publicados(date: str = Query(..., pattern=r"^\d{8}$"), db: Session = Depends(get_db)) -> dict:
    """Devuelve solamente picks ya guardados; jamás genera ni publica desde una lectura."""
    return {"date": date, "picks": recomendaciones_repo.leer_recomendaciones(db, date)}


def _nombre_base(name: str | None) -> str:
    """Nombre de la competición sin la fase ("Liga MX: Apertura" -> "liga mx"), en minúsculas y sin guiones."""
    base = (name or "").split(":", 1)[0]
    return " ".join(base.casefold().replace("-", " ").split())


def _is_priority(name: str | None, codigo: str | None = None) -> bool:
    """Competición relevante para el usuario. Por id canónico de API-Football (`LIGAS_OK`) cuando existe y,
    como las filas sin id son la mayoría, por nombre base. Excluye femenino, juveniles, reservas, copas
    menores, fases de grupos y amistosos."""
    normalized = _nombre_base(name)
    if any(term in normalized for term in PRIORITY_REJECTED):
        return False
    # "Premier League" sin país es ambiguo en los feeds de LiveScore. No se presenta como
    # relevante hasta que el proveedor nos entregue un ID canónico verificable.
    if codigo is not None and str(codigo) in {str(item) for item in LIGAS_OK}:
        return True
    return normalized in PRIORITY_EXACT


def _pronosticable(row: PartidoDia) -> bool:
    """El bot tiene modelo histórico para este partido (liga y equipos). Solo informa: las cuotas reales también bastan al analizar."""
    from backend.api.services import modelo_historico

    try:
        return bool(modelo_historico.validar_historico({"liga": row.liga_nombre or "", "local": row.local or "", "visitante": row.visitante or ""})[0])
    except Exception:  # noqa: BLE001 — un fallo del histórico nunca debe romper el catálogo
        log.debug("web_catalog: validación histórica falló", exc_info=True)
        return False


def _fixture(row: PartidoDia) -> dict:
    return {
        "pronosticable": _pronosticable(row),
        "id": row.match_id,
        "date": row.fecha,
        "kickoff": row.kick_off_utc or row.hora_chile,
        "status": row.status,
        "score": {"home": row.goles_local, "away": row.goles_visitante},
        "league": {"id": row.liga_slug or "otras", "name": ligas_ident.nombre_visible(row.liga_nombre or row.liga_slug or "Otras ligas", row.liga_pais), "country": row.liga_pais, "logo": row.liga_logo},
        "home": {"name": row.local or "Local", "logo": row.logo_local},
        "away": {"name": row.visitante or "Visitante", "logo": row.logo_visitante},
    }


@router.get("/history/accuracy")
def history_accuracy(usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """"Mis picks": acierto real de los pronósticos que consultó el usuario (solo partidos terminados con marcador)."""
    from backend.api.services.precision_usuario import calcular_precision_usuario

    return calcular_precision_usuario(db, usuario["sub"])


@router.get("/history")
def history(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    query = db.query(HistorialPrediccionWeb).filter(HistorialPrediccionWeb.user_id == usuario["sub"])
    total = query.count()
    rows = query.order_by(HistorialPrediccionWeb.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [{"id": row.id, "date": row.fecha, "league": row.liga, "home": row.local, "away": row.visitante, "pick": row.pick, "confidence": row.confianza, "created_at": row.creado_en} for row in rows]}


@router.get("/agent-predictions")
def agent_predictions(match_id: str | None = Query(None, max_length=255), limit: int = Query(30, ge=1, le=100), usuario: dict = Depends(obtener_usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Variantes privadas del agente; nunca alimentan el consenso público por lectura."""
    query = db.query(PrediccionVarianteAgente).filter(PrediccionVarianteAgente.user_id == usuario["sub"])
    if match_id:
        query = query.filter(PrediccionVarianteAgente.partido_id == match_id)
    rows = query.order_by(PrediccionVarianteAgente.id.desc()).limit(limit).all()
    return {"items": [{"id": row.id, "match_id": row.partido_id, "date": row.fecha, "home": row.local, "away": row.visitante, "via": row.via, "pick": row.pick, "scoreline": row.marcador_probable, "confidence": row.confianza, "provider": row.proveedor, "model": row.modelo, "created_at": row.creado_en} for row in rows]}


@router.get("/fixtures")
async def fixtures(
    date: str = Query(..., pattern=r"^\d{8}$"),
    scope: str = Query("priority", pattern="^(priority|all)$"),
    league: str | None = Query(None, max_length=120),
    q: str | None = Query(None, max_length=120),
    status: str | None = Query(None, max_length=40),
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
) -> dict:
    # valida calendario sin convertir el endpoint en una consulta amplia accidental.
    datetime.strptime(date, "%Y%m%d")
    date_db = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    # La web es un consumidor de primera clase: si la caché está vacía, activa la misma
    # cascada del bot. Antes dependía por error de que otro canal hubiese consultado primero.
    if not db.query(PartidoDia.match_id).filter(PartidoDia.fecha == date_db, PartidoDia.cache_invalidado == 0).first():
        async with httpx.AsyncClient() as client:
            await obtener_fixtures_cascada(db, client, date)
    query = db.query(PartidoDia).filter(PartidoDia.fecha == date_db, PartidoDia.cache_invalidado == 0)
    # Con búsqueda de texto se busca en TODAS las competiciones: filtrar antes por "relevantes" hacía que
    # buscar un equipo de una liga no destacada (p. ej. "Brann") devolviera 0 resultados.
    aplicar_relevancia = scope == "priority" and not q
    if league:
        query = query.filter(PartidoDia.liga_slug == league)
    if status:
        query = query.filter(PartidoDia.status == status)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(PartidoDia.local.ilike(term), PartidoDia.visitante.ilike(term), PartidoDia.liga_nombre.ilike(term)))
    rows_candidatos = query.order_by(PartidoDia.kick_off_utc.asc(), PartidoDia.hora_chile.asc()).all()
    if aplicar_relevancia:
        # El proveedor no garantiza slugs estables ni trae siempre el id de liga: se combina id y nombre base.
        rows_candidatos = [row for row in rows_candidatos if _is_priority(row.liga_nombre, row.liga_codigo)]
    total = len(rows_candidatos)
    # En fechas sin ligas prioritarias (por ejemplo, ventanas FIFA), mostrar una selección
    # editorial limitada en lugar de una pantalla vacía. La respuesta lo declara.
    effective_scope = scope
    if aplicar_relevancia and total == 0 and not league:
        query = db.query(PartidoDia).filter(PartidoDia.fecha == date_db, PartidoDia.cache_invalidado == 0)
        rows_candidatos = [
            row for row in query.order_by(PartidoDia.kick_off_utc.asc(), PartidoDia.hora_chile.asc()).all()
            if not any(term in _nombre_base(row.liga_nombre) for term in PRIORITY_REJECTED)
        ][:FALLBACK_MAX]
        total = len(rows_candidatos)
        effective_scope = "fallback"
    rows = rows_candidatos[offset:offset + limit]
    all_leagues = (
        db.query(PartidoDia.liga_slug, PartidoDia.liga_nombre, PartidoDia.liga_logo, func.count(PartidoDia.match_id), PartidoDia.liga_pais)
        .filter(PartidoDia.fecha == date_db, PartidoDia.cache_invalidado == 0)
        .group_by(PartidoDia.liga_slug, PartidoDia.liga_nombre, PartidoDia.liga_logo, PartidoDia.liga_pais)
        .order_by(PartidoDia.liga_nombre.asc())
        .all()
    )
    return {
        "date": date,
        "scope": effective_scope,
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
        "fixtures": [_fixture(row) for row in rows],
        "leagues": [{"id": slug or "otras", "name": ligas_ident.nombre_visible(name or slug or "Otras ligas", pais), "country": pais, "logo": logo, "count": count, "priority": _is_priority(name)} for slug, name, logo, count, pais in all_leagues],
    }
