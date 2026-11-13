"""routers/simulador.py — Simulador de liga Monte Carlo (probabilidad de campeón/copa/
descenso), ver `services/simulador_liga.py` para el porqué y el diseño completo.

2026-09-09 — rate limit agregado (hallazgo de auditoría, el más urgente de los 3 endpoints
públicos sin protección): este endpoint permite hasta `n_simulaciones=50_000` Monte Carlo por
request, sin auth ni límite — un solo cliente podía forzar cientos de simulaciones de 50.000
corridas cada una en paralelo. `10/minute` por IP (más estricto que `/prediccion-web`, ver
`core/rate_limit.py::limitar` para el mecanismo) — el costo real por request acá es mayor.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.api.core.rate_limit import limitar
from backend.api.db.session import get_db
from backend.api.services import simulador_liga, simulador_propio
from backend.api.core.auth_deps import obtener_usuario_actual
from backend.api.db import usuarios_repo
from fastapi import HTTPException
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

MAX_SIMULACIONES_SIMULTANEAS = 2
_cupo = threading.BoundedSemaphore(MAX_SIMULACIONES_SIMULTANEAS)
_ejecutor = ThreadPoolExecutor(max_workers=MAX_SIMULACIONES_SIMULTANEAS, thread_name_prefix="simulador")


def _lanzar_simulacion(*args):
    """Reserva un cupo y lanza el cálculo en el ejecutor propio; devuelve el futuro o None si está lleno. El cupo lo devuelve el callback del futuro, que se dispara siempre (termina, falla o se cancela): `wait_for` no detiene un hilo y una petición cancelada antes de arrancar no puede dejar el cupo tomado."""
    if not _cupo.acquire(blocking=False):
        return None
    try:
        futuro = _ejecutor.submit(simulador_propio.simular, *args)
    except BaseException:
        _cupo.release()
        raise
    futuro.add_done_callback(lambda _f: _cupo.release())
    return futuro

router = APIRouter(prefix="/api/v1", tags=["simulador"])


@router.get("/simulador")
@limitar("30/minute")
async def ligas_del_simulador(request: Request) -> dict:
    """Qué ligas se pueden simular hoy y a partir de qué plan (público: es solo información; el cálculo exige plan)."""
    ligas = await asyncio.to_thread(simulador_propio.ligas_disponibles)
    return {"ligas": ligas, "requiere": "plan pro o max, o administrador", "mensaje": usuarios_repo.MENSAJE_SIMULADOR}


@router.get("/simulador/{liga_slug}")
@limitar("10/minute")
async def simular_liga(
    request: Request,
    liga_slug: str,
    n_simulaciones: int = Query(simulador_liga.DEFAULT_N_SIMULACIONES, ge=100, le=50_000),
    posiciones_copa: int = Query(simulador_liga.DEFAULT_POSICIONES_COPA, ge=0),
    posiciones_descenso: int = Query(simulador_liga.DEFAULT_POSICIONES_DESCENSO, ge=0),
    n_temporadas_historial: int = Query(
        simulador_liga.DEFAULT_N_TEMPORADAS_HISTORIAL_DESCENSO, ge=0, le=5
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Simula el resto de la temporada actual de `liga_slug` (uno de los slugs de
    `services/top_picks.py::LIGA_SLUG_POR_ID`, ej. `premier`, `laliga`, `seriea`, más
    `liga_profesional` para la Liga Profesional Argentina — ver
    `services/simulador_liga.py::LIGA_ARGENTINA_SLUG`) N veces vía Monte Carlo, usando las
    probabilidades 1X2 que ya calcula el motor Poisson+Dixon-Coles de Laplace para cada partido
    pendiente. Devuelve, por equipo: probabilidad de campeón, de clasificar a copa continental
    (`posiciones_copa`, default top 4) y de descenso (`posiciones_descenso`, default últimos 3),
    más la posición promedio.

    `n_temporadas_historial` (default 2, ignorado para ligas que no sean `liga_profesional`):
    cuántas temporadas previas se suman para la regla real de descenso por promedio
    multi-temporada del fútbol argentino (AFA) — agrega `prob_descenso_por_promedio` por equipo
    cuando hay standings históricos disponibles (ver docstring de `simular_liga_actual()`)."""
    # Solo planes pro/max y administradores (regla simulaciones-internas-y-publicas.md): la sesión se exige y el plan se lee de la base, no del token.
    usuario = obtener_usuario_actual(authorization=request.headers.get("authorization", ""), db=db) if request.headers.get("authorization") else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para usar el simulador: es de los planes pro y max.")
    acceso = usuarios_repo.acceso_simulador(db, usuario.get("sub", ""))
    if not acceso["permitido"]:
        raise HTTPException(status_code=403, detail=acceso["motivo"])
    if liga_slug in simulador_propio.SLUGS:  # motor propio con los datos propios (viejos + actuales), núcleo en Go
        futuro = _lanzar_simulacion(liga_slug, n_simulaciones, posiciones_copa, posiciones_descenso)
        if futuro is None:
            raise HTTPException(status_code=503, detail="Hay simulaciones en curso; inténtalo en unos segundos.", headers={"Retry-After": "10"})
        try:
            return await asyncio.wait_for(asyncio.wrap_future(futuro), timeout=30)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise HTTPException(status_code=504, detail="La simulación tardó demasiado; baja el número de simulaciones.") from None
    async with httpx.AsyncClient() as client:
        return await simulador_liga.simular_liga_actual(
            db, client, liga_slug,
            n_simulaciones=n_simulaciones,
            posiciones_copa=posiciones_copa,
            posiciones_descenso=posiciones_descenso,
            n_temporadas_historial=n_temporadas_historial,
        )
